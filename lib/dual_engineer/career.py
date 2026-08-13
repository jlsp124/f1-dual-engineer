# MIT License
# Copyright (c) 2026 F1 Dual Engineer contributors

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .championship import PointsRules


@dataclass(frozen=True, slots=True)
class CareerResult:
    driver_key: str
    driver_name: str
    position: int
    team: Optional[str] = None
    grid_position: Optional[int] = None
    classified: bool = True
    fastest_lap: bool = False
    dnf: bool = False
    qualifying_gap_ms: Optional[float] = None
    race_pace_gap_ms: Optional[float] = None


class CareerDatabase:
    """SQLite-backed optional career companion.

    The game result packet is stored as an observed event. Manual corrections
    update our local database only and never claim to modify an EA save file.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser().resolve(strict=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS careers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    season_name TEXT NOT NULL,
                    game_version TEXT NOT NULL,
                    driver_a_key TEXT NOT NULL,
                    driver_b_key TEXT NOT NULL,
                    current_round INTEGER NOT NULL DEFAULT 0,
                    calendar_json TEXT NOT NULL DEFAULT '[]',
                    scoring_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS career_drivers (
                    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
                    driver_key TEXT NOT NULL,
                    driver_name TEXT NOT NULL,
                    team TEXT,
                    starting_points INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (career_id, driver_key)
                );

                CREATE TABLE IF NOT EXISTS constructor_bases (
                    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
                    team TEXT NOT NULL,
                    starting_points INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (career_id, team)
                );

                CREATE TABLE IF NOT EXISTS career_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    career_id INTEGER NOT NULL REFERENCES careers(id) ON DELETE CASCADE,
                    session_uid TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    track TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    raw_classification_json TEXT NOT NULL,
                    UNIQUE (career_id, session_uid, event_type)
                );

                CREATE TABLE IF NOT EXISTS career_results (
                    event_id INTEGER NOT NULL REFERENCES career_events(id) ON DELETE CASCADE,
                    driver_key TEXT NOT NULL,
                    driver_name TEXT NOT NULL,
                    team TEXT,
                    position INTEGER NOT NULL,
                    grid_position INTEGER,
                    points INTEGER NOT NULL,
                    classified INTEGER NOT NULL,
                    fastest_lap INTEGER NOT NULL,
                    dnf INTEGER NOT NULL,
                    qualifying_gap_ms REAL,
                    race_pace_gap_ms REAL,
                    manual INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (event_id, driver_key)
                );

                CREATE TABLE IF NOT EXISTS recorded_sessions (
                    session_uid TEXT PRIMARY KEY,
                    folder TEXT NOT NULL,
                    track TEXT,
                    session_type TEXT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    finalized INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES('version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(self.SCHEMA_VERSION),),
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_career(
        self,
        season_name: str,
        game_version: str,
        driver_a_key: str,
        driver_b_key: str,
        *,
        calendar: Sequence[str] = (),
        rules: PointsRules = PointsRules(),
    ) -> int:
        if not season_name.strip():
            raise ValueError("season_name must not be empty")
        if driver_a_key == driver_b_key:
            raise ValueError("career drivers must be different")
        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO careers(
                    season_name, game_version, driver_a_key, driver_b_key,
                    calendar_json, scoring_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    season_name.strip(),
                    game_version.strip(),
                    driver_a_key,
                    driver_b_key,
                    json.dumps(list(calendar)),
                    json.dumps(asdict(rules)),
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def list_careers(self) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM careers ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [self._career_row(row) for row in rows]

    def get_career(self, career_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM careers WHERE id = ?", (career_id,)).fetchone()
        return self._career_row(row) if row else None

    @staticmethod
    def _career_row(row: sqlite3.Row) -> Dict[str, Any]:
        value = dict(row)
        value["calendar"] = json.loads(value.pop("calendar_json"))
        value["scoring"] = json.loads(value.pop("scoring_json"))
        return value

    def import_standings(
        self,
        career_id: int,
        drivers: Sequence[Mapping[str, Any]],
        constructors: Mapping[str, int],
        *,
        current_round: int,
    ) -> None:
        if current_round < 0:
            raise ValueError("current_round cannot be negative")
        with self._connect() as connection:
            if not connection.execute("SELECT 1 FROM careers WHERE id = ?", (career_id,)).fetchone():
                raise KeyError(f"Unknown career {career_id}")
            for driver in drivers:
                connection.execute(
                    """
                    INSERT INTO career_drivers(career_id, driver_key, driver_name, team, starting_points)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(career_id, driver_key) DO UPDATE SET
                        driver_name=excluded.driver_name,
                        team=excluded.team,
                        starting_points=excluded.starting_points
                    """,
                    (
                        career_id,
                        str(driver["driver_key"]),
                        str(driver["driver_name"]),
                        driver.get("team"),
                        int(driver.get("points", 0)),
                    ),
                )
            for team, points in constructors.items():
                connection.execute(
                    """
                    INSERT INTO constructor_bases(career_id, team, starting_points)
                    VALUES (?, ?, ?)
                    ON CONFLICT(career_id, team) DO UPDATE SET starting_points=excluded.starting_points
                    """,
                    (career_id, team, int(points)),
                )
            connection.execute(
                "UPDATE careers SET current_round = ?, updated_at = ? WHERE id = ?",
                (current_round, self._now(), career_id),
            )

    def ingest_event(
        self,
        career_id: int,
        session_uid: int | str,
        round_number: int,
        track: str,
        event_type: str,
        results: Sequence[CareerResult],
        *,
        source: str = "F1 final classification UDP",
        observed_at: Optional[str] = None,
    ) -> int:
        career = self.get_career(career_id)
        if not career:
            raise KeyError(f"Unknown career {career_id}")
        rules = PointsRules(**career["scoring"])
        normalized_type = event_type.casefold()
        raw = json.dumps([asdict(result) for result in results], sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO career_events(
                    career_id, session_uid, round_number, track, event_type,
                    observed_at, source, raw_classification_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(career_id, session_uid, event_type) DO UPDATE SET
                    round_number=excluded.round_number,
                    track=excluded.track,
                    observed_at=excluded.observed_at,
                    source=excluded.source,
                    raw_classification_json=excluded.raw_classification_json
                """,
                (
                    career_id,
                    str(session_uid),
                    round_number,
                    track,
                    normalized_type,
                    observed_at or self._now(),
                    source,
                    raw,
                ),
            )
            event_id = int(
                connection.execute(
                    "SELECT id FROM career_events WHERE career_id=? AND session_uid=? AND event_type=?",
                    (career_id, str(session_uid), normalized_type),
                ).fetchone()["id"]
            )
            connection.execute("DELETE FROM career_results WHERE event_id = ?", (event_id,))
            for result in results:
                connection.execute(
                    """
                    INSERT INTO career_drivers(career_id, driver_key, driver_name, team, starting_points)
                    VALUES (?, ?, ?, ?, 0)
                    ON CONFLICT(career_id, driver_key) DO UPDATE SET
                        driver_name=excluded.driver_name,
                        team=COALESCE(excluded.team, career_drivers.team)
                    """,
                    (career_id, result.driver_key, result.driver_name, result.team),
                )
                points = (
                    rules.points_for(result.position, normalized_type, result.fastest_lap)
                    if result.classified and normalized_type in {"race", "sprint"}
                    else 0
                )
                connection.execute(
                    """
                    INSERT INTO career_results(
                        event_id, driver_key, driver_name, team, position,
                        grid_position, points, classified, fastest_lap, dnf,
                        qualifying_gap_ms, race_pace_gap_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        result.driver_key,
                        result.driver_name,
                        result.team,
                        result.position,
                        result.grid_position,
                        points,
                        int(result.classified),
                        int(result.fastest_lap),
                        int(result.dnf),
                        result.qualifying_gap_ms,
                        result.race_pace_gap_ms,
                    ),
                )
            connection.execute(
                "UPDATE careers SET current_round = MAX(current_round, ?), updated_at = ? WHERE id = ?",
                (round_number, self._now(), career_id),
            )
        return event_id

    def correct_result(self, event_id: int, driver_key: str, **changes: Any) -> None:
        allowed = {
            "driver_name",
            "team",
            "position",
            "grid_position",
            "points",
            "classified",
            "fastest_lap",
            "dnf",
            "qualifying_gap_ms",
            "race_pace_gap_ms",
        }
        invalid = set(changes) - allowed
        if invalid or not changes:
            raise ValueError(f"Unsupported correction fields: {sorted(invalid)}")
        assignments = ", ".join(f"{name} = ?" for name in changes)
        values = [int(value) if name in {"classified", "fastest_lap", "dnf"} else value for name, value in changes.items()]
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE career_results SET {assignments}, manual = 1 WHERE event_id = ? AND driver_key = ?",
                (*values, event_id, driver_key),
            )
            if cursor.rowcount != 1:
                raise KeyError("Result to correct was not found")

    def driver_standings(self, career_id: int) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    d.driver_key,
                    d.driver_name,
                    d.team,
                    d.starting_points + COALESCE(SUM(r.points), 0) AS points,
                    COALESCE(SUM(CASE WHEN e.event_type='race' AND r.position=1 THEN 1 ELSE 0 END), 0) AS wins,
                    COALESCE(SUM(CASE WHEN e.event_type='race' AND r.position<=3 AND r.classified=1 THEN 1 ELSE 0 END), 0) AS podiums,
                    COALESCE(SUM(CASE WHEN e.event_type LIKE '%qual%' AND r.position=1 THEN 1 ELSE 0 END), 0) AS poles,
                    COALESCE(SUM(r.fastest_lap), 0) AS fastest_laps,
                    COALESCE(SUM(r.dnf), 0) AS dnfs
                FROM career_drivers d
                LEFT JOIN career_events e ON e.career_id = d.career_id
                LEFT JOIN career_results r ON r.event_id = e.id AND r.driver_key = d.driver_key
                WHERE d.career_id = ?
                GROUP BY d.career_id, d.driver_key
                ORDER BY points DESC, wins DESC, d.driver_name COLLATE NOCASE
                """,
                (career_id,),
            ).fetchall()
        return [{"rank": index, **dict(row)} for index, row in enumerate(rows, start=1)]

    def constructor_standings(self, career_id: int) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH teams AS (
                    SELECT team FROM constructor_bases WHERE career_id = ?
                    UNION
                    SELECT team FROM career_drivers WHERE career_id = ? AND team IS NOT NULL
                )
                SELECT
                    teams.team,
                    COALESCE(base.starting_points, 0) + COALESCE(SUM(r.points), 0) AS points
                FROM teams
                LEFT JOIN constructor_bases base ON base.career_id = ? AND base.team = teams.team
                LEFT JOIN career_events e ON e.career_id = ?
                LEFT JOIN career_results r ON r.event_id = e.id AND r.team = teams.team
                GROUP BY teams.team, base.starting_points
                ORDER BY points DESC, teams.team COLLATE NOCASE
                """,
                (career_id, career_id, career_id, career_id),
            ).fetchall()
        return [{"rank": index, **dict(row)} for index, row in enumerate(rows, start=1)]

    def head_to_head(self, career_id: int) -> Dict[str, Any]:
        career = self.get_career(career_id)
        if not career:
            raise KeyError(f"Unknown career {career_id}")
        keys = (career["driver_a_key"], career["driver_b_key"])
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.event_type, e.track, r.*
                FROM career_results r
                JOIN career_events e ON e.id = r.event_id
                WHERE e.career_id = ? AND r.driver_key IN (?, ?)
                ORDER BY e.round_number, e.id
                """,
                (career_id, *keys),
            ).fetchall()
        by_event: Dict[tuple, Dict[str, sqlite3.Row]] = {}
        for row in rows:
            by_event.setdefault((row["event_id"], row["event_type"]), {})[row["driver_key"]] = row
        h2h = {"qualifying": [0, 0], "race": [0, 0], "sprint": [0, 0]}
        for (_, event_type), results in by_event.items():
            if all(key in results for key in keys):
                left, right = results[keys[0]], results[keys[1]]
                bucket = "qualifying" if "qual" in event_type else event_type if event_type in {"race", "sprint"} else None
                if bucket and left["position"] != right["position"]:
                    h2h[bucket][0 if left["position"] < right["position"] else 1] += 1
        standings = {row["driver_key"]: row for row in self.driver_standings(career_id)}
        return {
            "driver_a": standings.get(keys[0]),
            "driver_b": standings.get(keys[1]),
            "qualifying_h2h": h2h["qualifying"],
            "race_h2h": h2h["race"],
            "sprint_h2h": h2h["sprint"],
        }

    def register_session(self, session_uid: int | str, folder: Path, metadata: Mapping[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO recorded_sessions(
                    session_uid, folder, track, session_type, started_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_uid) DO UPDATE SET
                    folder=excluded.folder,
                    track=excluded.track,
                    session_type=excluded.session_type,
                    metadata_json=excluded.metadata_json
                """,
                (
                    str(session_uid),
                    str(folder.resolve(strict=False)),
                    metadata.get("track"),
                    metadata.get("session_type"),
                    metadata.get("started_at", self._now()),
                    json.dumps(dict(metadata), sort_keys=True),
                ),
            )

    def finalize_session(self, session_uid: int | str, folder: Path, metadata: Mapping[str, Any]) -> None:
        self.register_session(session_uid, folder, metadata)
        with self._connect() as connection:
            connection.execute(
                "UPDATE recorded_sessions SET ended_at=?, finalized=1 WHERE session_uid=?",
                (metadata.get("ended_at", self._now()), str(session_uid)),
            )

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM recorded_sessions ORDER BY started_at DESC"
            ).fetchall()
        output: List[Dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            value["metadata"] = json.loads(value.pop("metadata_json"))
            value["finalized"] = bool(value["finalized"])
            output.append(value)
        return output

    def set_preference(self, key: str, value: Any) -> None:
        if not key or len(key) > 128:
            raise ValueError("Invalid preference key")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO preferences(key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value), self._now()),
            )

    def get_preference(self, key: str, default: Any = None) -> Any:
        with self._connect() as connection:
            row = connection.execute("SELECT value_json FROM preferences WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else default
