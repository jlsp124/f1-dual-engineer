# MIT License
# Copyright (c) 2026 F1 Dual Engineer contributors

"""Runtime coordinator for selection, recording, live traces, and career ingestion."""

from __future__ import annotations

import asyncio
import logging
import json
import os
import struct
import time
import zipfile
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

from apps.backend.state_mgmt_layer.session_state import SessionState
from lib.config.schema.engineer import EngineerSettings
from lib.f1_types import PacketHeader, PacketSessionData

from .career import CareerDatabase, CareerResult
from .championship import (
    ClassificationEntry,
    PointsRules,
    Standing,
    project_constructor_standings,
    project_standings,
)
from .models import TelemetrySample
from .recorder import SessionRecorder
from .snapshot import detailed_telemetry_available, telemetry_sample_from_state


class DualEngineerService:
    """Own the dual-driver runtime without adding I/O to ``SessionState``."""

    def __init__(
        self,
        session_state: SessionState,
        settings: EngineerSettings,
        shutdown_event: asyncio.Event,
        *,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.session_state = session_state
        self.settings = settings
        self.shutdown_event = shutdown_event
        self.logger = logger or logging.getLogger(__name__)
        self.database = CareerDatabase(settings.export_directory_path / "f1_dual_engineer.sqlite")
        self.recorder = SessionRecorder(settings, logger=self.logger, database=self.database)
        self.driver_a_index: Optional[int] = None
        self.driver_b_index: Optional[int] = None
        self.latest_export: Optional[Path] = None
        self._sampler_task: Optional[asyncio.Task] = None
        self._traces: Dict[int, Deque[TelemetrySample]] = {}
        self._trace_laps: Dict[int, int] = {}
        self._feed: Deque[Dict[str, Any]] = deque(maxlen=40)
        self._feed_last: Dict[str, float] = {}
        self._last_feed_update = 0.0

    def start(self) -> Sequence[asyncio.Task]:
        recorder_task = self.recorder.start()
        if not self._sampler_task or self._sampler_task.done():
            self._sampler_task = asyncio.create_task(
                self._sample_loop(), name="Dual Engineer Structured Sampler"
            )
        return (recorder_task, self._sampler_task)

    async def stop(self) -> None:
        if self._sampler_task and not self._sampler_task.done():
            self._sampler_task.cancel()
            await asyncio.gather(self._sampler_task, return_exceptions=True)
        await self.recorder.stop()

    def on_raw_packet(self, raw_packet: bytes) -> None:
        if len(raw_packet) < PacketHeader.PACKET_LEN:
            return
        try:
            header = PacketHeader(raw_packet[:PacketHeader.PACKET_LEN])
        except (struct.error, ValueError):
            return
        # Ignore lobby/menu traffic. The first SESSION packet establishes the
        # active UID; retaining begins with the following packet.
        if self.session_state.m_session_info.m_session_uid != header.m_sessionUID:
            return
        self.recorder.enqueue_raw(header.m_sessionUID, raw_packet)

    def on_session_update(self, packet: PacketSessionData) -> None:
        uid = packet.m_header.m_sessionUID
        self.recorder.update_metadata(uid, {
            "track": str(packet.m_trackId),
            "track_length_m": packet.m_trackLength,
            "session_type": str(packet.m_sessionType),
            "game_year": packet.m_header.m_gameYear,
            "packet_format": packet.m_header.m_packetFormat,
            "equal_performance": bool(packet.m_equalCarPerformance),
            "driver_a_index": self.driver_a_index,
            "driver_b_index": self.driver_b_index,
        })

    def on_participants_update(self) -> None:
        if not self._selection_is_valid():
            self._resolve_default_selection()
        self._update_selection_metadata()

    async def on_final_classification(
        self,
        session_uid: int,
        final_json: Mapping[str, Any],
    ) -> Optional[Path]:
        if self.session_state.m_session_info.m_session_uid != session_uid:
            self.logger.warning(
                "Ignoring final classification for non-active session %s",
                session_uid,
            )
            return None
        try:
            self.latest_export = await self.recorder.finalize(session_uid, final_json)
        except Exception:  # pylint: disable=broad-exception-caught
            self.logger.exception("Dual Engineer could not finalize session %s", session_uid)
            return None
        self._ingest_active_career(session_uid, final_json)
        return self.latest_export

    def set_selection(self, driver_a_index: int, driver_b_index: int) -> Dict[str, Any]:
        if driver_a_index == driver_b_index:
            raise ValueError("Driver A and Driver B must be different")
        for index in (driver_a_index, driver_b_index):
            if not self._valid_driver_index(index):
                raise ValueError(f"Driver index {index} is not a live participant")
        self.driver_a_index = driver_a_index
        self.driver_b_index = driver_b_index
        self._traces.clear()
        self._trace_laps.clear()
        names = [self._driver_name(index) for index in (driver_a_index, driver_b_index)]
        self.database.set_preference("driver_selection", {"names": names})
        self._update_selection_metadata()
        self._add_feed("selection", f"Pinned {names[0]} as Driver A and {names[1]} as Driver B", "info")
        return self.state_json()

    def state_json(self) -> Dict[str, Any]:
        participants: List[Dict[str, Any]] = []
        for index, driver in enumerate(self.session_state.m_driver_data):
            if not driver or not driver.is_valid:
                continue
            participants.append({
                "index": index,
                "name": driver.m_driver_info.name or f"Car {index + 1}",
                "team": driver.m_driver_info.team,
                "position": driver.m_driver_info.position,
                "telemetry_available": detailed_telemetry_available(self.session_state, index),
                "is_player": index == self.session_state.m_player_index,
                "is_secondary_player": index == self.session_state.m_secondary_player_index,
            })
        session_uid = self.session_state.m_session_info.m_session_uid
        return {
            "enabled": self.settings.enabled,
            "driver_a_index": self.driver_a_index,
            "driver_b_index": self.driver_b_index,
            "participants": participants,
            "recording": {
                "active": bool(session_uid and self.settings.auto_record),
                "session_uid": session_uid,
                "raw_queue_depth": self.recorder.queue.qsize(),
                "dropped_raw_packets": self.recorder.dropped_raw_packets,
                "dropped_structured_samples": self.recorder.dropped_samples,
                "latest_export": str(self.latest_export) if self.latest_export else None,
            },
            "comparison": self.comparison_json(),
            "feed": list(self._feed),
        }

    def comparison_json(self) -> Dict[str, Any]:
        def points(index: Optional[int]) -> List[Dict[str, Any]]:
            if index is None:
                return []
            trace = list(self._traces.get(index, ()))
            step = max(1, len(trace) // 180)
            return [
                {
                    "distance": sample.lap_distance_m,
                    "time_ms": sample.lap_time_ms,
                    "speed": sample.speed_kph,
                    "throttle": sample.throttle,
                    "brake": sample.brake,
                    "steering": sample.steering,
                    "gear": sample.gear,
                    "rpm": sample.rpm,
                    "g_lat": sample.g_lateral,
                    "g_long": sample.g_longitudinal,
                    "x": sample.world_x,
                    "z": sample.world_z,
                }
                for sample in trace[::step]
            ]

        a_points = points(self.driver_a_index)
        b_points = points(self.driver_b_index)
        return {
            "driver_a": {"index": self.driver_a_index, "name": self._driver_name(self.driver_a_index), "points": a_points},
            "driver_b": {"index": self.driver_b_index, "name": self._driver_name(self.driver_b_index), "points": b_points},
            "live_delta_ms": self._live_delta(a_points, b_points),
            "normalization": "lap-distance",
        }

    @staticmethod
    def _live_delta(a_points: List[Dict[str, Any]], b_points: List[Dict[str, Any]]) -> Optional[float]:
        if not a_points or not b_points:
            return None
        target_distance = min(a_points[-1]["distance"], b_points[-1]["distance"])

        def nearest(points: List[Dict[str, Any]]) -> Dict[str, Any]:
            return min(points, key=lambda point: abs(point["distance"] - target_distance))

        return round(nearest(a_points)["time_ms"] - nearest(b_points)["time_ms"], 1)

    def sessions_json(self) -> List[Dict[str, Any]]:
        return self.database.list_sessions()

    def careers_json(self) -> List[Dict[str, Any]]:
        return self.database.list_careers()

    def career_detail_json(self, career_id: int) -> Dict[str, Any]:
        career = self.database.get_career(career_id)
        if not career:
            raise KeyError(f"Unknown career {career_id}")
        driver_standings = self.database.driver_standings(career_id)
        constructor_standings = self.database.constructor_standings(career_id)
        projected_drivers, projected_constructors, projection_active = self._career_projection(
            career, driver_standings, constructor_standings
        )
        return {
            "career": career,
            "driver_standings": driver_standings,
            "constructor_standings": constructor_standings,
            "projected_driver_standings": projected_drivers,
            "projected_constructor_standings": projected_constructors,
            "projection_active": projection_active,
            "head_to_head": self.database.head_to_head(career_id),
            "active": self.database.get_preference("active_career_id") == career_id,
        }

    def _career_projection(
        self,
        career: Mapping[str, Any],
        driver_standings: Sequence[Mapping[str, Any]],
        constructor_standings: Sequence[Mapping[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
        """Project an active race without inventing drivers absent from the career."""
        session_uid = self.session_state.m_session_info.m_session_uid
        session_label = str(self.session_state.m_session_info.m_session_type or "").casefold()
        session_type = "sprint" if "sprint" in session_label else "race"
        if not session_uid or not any(label in session_label for label in ("race", "sprint")):
            return [dict(row, projected_delta=0) for row in driver_standings], [
                dict(row, projected_delta=0) for row in constructor_standings
            ], False

        existing = tuple(
            Standing(
                driver_id=str(row["driver_key"]),
                driver_name=str(row["driver_name"]),
                points=int(row["points"]),
                rank=int(row["rank"]),
                team=row.get("team"),
            )
            for row in driver_standings
        )
        existing_keys = {item.driver_id for item in existing}
        keys_by_name = {
            str(row["driver_name"]).strip().casefold(): str(row["driver_key"])
            for row in driver_standings
        }
        classification: List[ClassificationEntry] = []
        for index, driver in enumerate(self.session_state.m_driver_data):
            if not driver or not driver.is_valid or not driver.m_driver_info.position:
                continue
            if index == self.driver_a_index:
                driver_key = str(career["driver_a_key"])
            elif index == self.driver_b_index:
                driver_key = str(career["driver_b_key"])
            else:
                driver_key = keys_by_name.get(
                    str(driver.m_driver_info.name or "").strip().casefold(), ""
                )
            if not driver_key or driver_key not in existing_keys:
                continue
            classification.append(
                ClassificationEntry(
                    driver_id=driver_key,
                    driver_name=str(driver.m_driver_info.name or driver_key),
                    position=int(driver.m_driver_info.position),
                    team=driver.m_driver_info.team,
                )
            )
        if not classification:
            return [dict(row, projected_delta=0) for row in driver_standings], [
                dict(row, projected_delta=0) for row in constructor_standings
            ], False

        rules = PointsRules(**career["scoring"])
        projected = project_standings(existing, classification, rules=rules, session_type=session_type)
        base_constructor_points = {
            str(row["team"]): int(row["points"]) for row in constructor_standings
        }
        projected_constructors = project_constructor_standings(
            base_constructor_points, classification, rules=rules, session_type=session_type
        )
        driver_output = [
            {
                "rank": row.rank,
                "driver_key": row.driver_id,
                "driver_name": row.driver_name,
                "team": row.team,
                "points": row.points,
                "projected_delta": row.projected_delta,
            }
            for row in projected
        ]
        constructor_output = [
            {
                "rank": rank,
                "team": team,
                "points": points,
                "projected_delta": points - base_constructor_points.get(team, 0),
            }
            for rank, (team, points) in enumerate(projected_constructors, start=1)
        ]
        return driver_output, constructor_output, True

    def create_career(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        season_name = self._bounded_text(payload.get("season_name") or "New season", "season_name", 80)
        game_version = self._bounded_text(payload.get("game_version") or "F1 25", "game_version", 40)
        driver_a_key = self._bounded_text(payload.get("driver_a_key") or "driver-a", "driver_a_key", 80)
        driver_b_key = self._bounded_text(payload.get("driver_b_key") or "driver-b", "driver_b_key", 80)
        calendar = tuple(payload.get("calendar") or ())
        if len(calendar) > 40:
            raise ValueError("calendar cannot contain more than 40 events")
        calendar = tuple(self._bounded_text(value, "calendar event", 80) for value in calendar)
        career_id = self.database.create_career(
            season_name,
            game_version,
            driver_a_key,
            driver_b_key,
            calendar=calendar,
            rules=PointsRules(**(payload.get("scoring") or {})),
        )
        self.database.set_preference("active_career_id", career_id)
        return self.career_detail_json(career_id)

    def import_career_standings(self, career_id: int, payload: Mapping[str, Any]) -> Dict[str, Any]:
        drivers = payload.get("drivers") or ()
        constructors = payload.get("constructors") or {}
        if not isinstance(drivers, (list, tuple)) or len(drivers) > 40:
            raise ValueError("drivers must be a list with at most 40 entries")
        if not isinstance(constructors, dict) or len(constructors) > 20:
            raise ValueError("constructors must be an object with at most 20 entries")
        current_round = int(payload.get("current_round") or 0)
        if not 0 <= current_round <= 100:
            raise ValueError("current_round must be between 0 and 100")
        bounded_drivers = []
        for driver in drivers:
            if not isinstance(driver, Mapping):
                raise ValueError("each driver must be an object")
            points = int(driver.get("points", 0))
            if not 0 <= points <= 100000:
                raise ValueError("driver points must be between 0 and 100000")
            bounded_drivers.append({
                "driver_key": self._bounded_text(driver.get("driver_key"), "driver_key", 80),
                "driver_name": self._bounded_text(driver.get("driver_name"), "driver_name", 80),
                "team": self._bounded_text(driver.get("team"), "team", 80, allow_empty=True) or None,
                "points": points,
            })
        bounded_constructors = {}
        for team, points_value in constructors.items():
            points = int(points_value)
            if not 0 <= points <= 100000:
                raise ValueError("constructor points must be between 0 and 100000")
            bounded_constructors[self._bounded_text(team, "constructor team", 80)] = points
        self.database.import_standings(
            career_id,
            bounded_drivers,
            bounded_constructors,
            current_round=current_round,
        )
        return self.career_detail_json(career_id)

    @staticmethod
    def _bounded_text(value: Any, field: str, limit: int, *, allow_empty: bool = False) -> str:
        text = str(value or "").strip()
        if not text and not allow_empty:
            raise ValueError(f"{field} must not be empty")
        if len(text) > limit or "\x00" in text:
            raise ValueError(f"{field} must be at most {limit} characters")
        return text

    def activate_career(self, career_id: int) -> Dict[str, Any]:
        if not self.database.get_career(career_id):
            raise KeyError(f"Unknown career {career_id}")
        self.database.set_preference("active_career_id", career_id)
        return self.career_detail_json(career_id)

    def session_detail_json(self, session_uid: str) -> Dict[str, Any]:
        path = self._session_path(session_uid)
        summary = path / "session_summary.json"
        if not summary.is_file() or summary.stat().st_size > 25 * 1024 * 1024:
            raise FileNotFoundError("Session summary is unavailable")
        with summary.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def export_session_zip(self, session_uid: str) -> Path:
        folder = self._session_path(session_uid)
        candidate = self.settings.export_directory_path / f"{folder.name}.zip"
        if candidate.is_symlink():
            raise ValueError("Session archive path must not be a symlink")
        if candidate.is_file():
            return candidate
        with zipfile.ZipFile(candidate, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for item in sorted(folder.rglob("*")):
                if item.is_file() and not item.is_symlink():
                    archive.write(item, arcname=f"{folder.name}/{item.relative_to(folder)}")
        return candidate

    def open_session_folder(self, session_uid: str) -> Path:
        folder = self._session_path(session_uid)
        if os.name != "nt":
            raise OSError("Open Session Folder is currently supported on Windows")
        os.startfile(str(folder))  # type: ignore[attr-defined]  # trusted catalog path, no shell
        return folder

    def _session_path(self, session_uid: str) -> Path:
        record = next(
            (item for item in self.database.list_sessions() if str(item["session_uid"]) == str(session_uid)),
            None,
        )
        if not record or not record["finalized"]:
            raise FileNotFoundError("Finalized session was not found")
        root = self.settings.export_directory_path.resolve(strict=True)
        path = Path(record["folder"]).resolve(strict=True)
        if not path.is_dir() or not path.is_relative_to(root):
            raise ValueError("Recorded session path is outside the configured export directory")
        return path

    async def _sample_loop(self) -> None:
        while not self.shutdown_event.is_set():
            await asyncio.sleep(self.settings.sample_interval_seconds)
            uid = self.session_state.m_session_info.m_session_uid
            if not uid:
                continue
            for index in (self.driver_a_index, self.driver_b_index):
                if index is None:
                    continue
                sample = telemetry_sample_from_state(self.session_state, uid, index)
                if not sample:
                    continue
                self.recorder.enqueue_sample(sample)
                self._append_trace(sample)
            now = time.monotonic()
            if now - self._last_feed_update >= 1.0:
                self._update_engineer_feed()
                self._last_feed_update = now

    def _append_trace(self, sample: TelemetrySample) -> None:
        previous_lap = self._trace_laps.get(sample.driver_index)
        if previous_lap != sample.lap_number:
            self._traces[sample.driver_index] = deque(maxlen=self.settings.sample_rate_hz * 180)
            self._trace_laps[sample.driver_index] = sample.lap_number
        self._traces[sample.driver_index].append(sample)

    def _update_engineer_feed(self) -> None:
        for index in (self.driver_a_index, self.driver_b_index):
            if index is None or not self._valid_driver_index(index):
                continue
            driver = self.session_state.m_driver_data[index]
            name = self._driver_name(index)
            if not detailed_telemetry_available(self.session_state, index):
                self._add_feed(
                    f"privacy-{index}",
                    f"{name} detailed telemetry unavailable — set Your Telemetry to Public",
                    "warning",
                    cooldown=120,
                )
                continue
            ers = driver.m_car_info.m_ers_perc
            if self.settings.energy_alerts and ers is not None and ers < 15:
                self._add_feed(f"ers-{index}", f"{name} ERS low · {ers:.0f}% stored", "warning", cooldown=30)
            if self.settings.pit_alerts and driver.m_lap_info.m_is_pitting:
                self._add_feed(f"pit-{index}", f"{name} is in the pit sequence", "critical", cooldown=20)

        if self.settings.pace_alerts and self.driver_a_index is not None and self.driver_b_index is not None:
            left = self.session_state.m_driver_data[self.driver_a_index]
            right = self.session_state.m_driver_data[self.driver_b_index]
            if left and right and left.m_lap_info.m_last_lap_ms and right.m_lap_info.m_last_lap_ms:
                delta = left.m_lap_info.m_last_lap_ms - right.m_lap_info.m_last_lap_ms
                if abs(delta) >= 100:
                    faster = self._driver_name(self.driver_a_index if delta < 0 else self.driver_b_index)
                    slower = self._driver_name(self.driver_b_index if delta < 0 else self.driver_a_index)
                    self._add_feed(
                        "last-lap-pace",
                        f"{faster} was {abs(delta) / 1000:.2f}s faster than {slower} last lap",
                        "pace",
                        cooldown=15,
                    )

    def _add_feed(self, key: str, message: str, level: str, cooldown: float = 5.0) -> None:
        now = time.monotonic()
        if now - self._feed_last.get(key, -cooldown) < cooldown:
            return
        self._feed_last[key] = now
        self._feed.appendleft({"time": time.strftime("%H:%M:%S"), "level": level, "message": message})

    def _resolve_default_selection(self) -> None:
        available = [
            index for index, driver in enumerate(self.session_state.m_driver_data)
            if driver and driver.is_valid
        ]
        if len(available) < 2:
            return
        stored = self.database.get_preference("driver_selection", {}) or {}
        preferred_names = [
            self.settings.driver_a_preference,
            self.settings.driver_b_preference,
            *(stored.get("names") or []),
        ]
        candidates: List[int] = []
        for name in preferred_names:
            match = self._find_name(name, available)
            if match is not None and match not in candidates:
                candidates.append(match)
        for index in (self.session_state.m_player_index, self.session_state.m_secondary_player_index):
            if index in available and index not in candidates:
                candidates.append(index)
        for index in available:
            if index not in candidates:
                candidates.append(index)
        self.driver_a_index = candidates[0]
        self.driver_b_index = candidates[1]
        self.database.set_preference("driver_selection", {
            "names": [self._driver_name(self.driver_a_index), self._driver_name(self.driver_b_index)]
        })

    def _find_name(self, name: str, indices: Sequence[int]) -> Optional[int]:
        key = str(name or "").strip().casefold()
        if not key:
            return None
        for index in indices:
            candidate = self._driver_name(index).casefold()
            if candidate == key or candidate.startswith(key) or key.startswith(candidate):
                return index
        return None

    def _selection_is_valid(self) -> bool:
        return bool(
            self.driver_a_index is not None
            and self.driver_b_index is not None
            and self.driver_a_index != self.driver_b_index
            and self._valid_driver_index(self.driver_a_index)
            and self._valid_driver_index(self.driver_b_index)
        )

    def _valid_driver_index(self, index: int) -> bool:
        return bool(
            0 <= index < len(self.session_state.m_driver_data)
            and self.session_state.m_driver_data[index]
            and self.session_state.m_driver_data[index].is_valid
        )

    def _driver_name(self, index: Optional[int]) -> Optional[str]:
        if index is None or not 0 <= index < len(self.session_state.m_driver_data):
            return None
        driver = self.session_state.m_driver_data[index]
        return (driver.m_driver_info.name or f"Car {index + 1}") if driver else None

    def _update_selection_metadata(self) -> None:
        uid = self.session_state.m_session_info.m_session_uid
        if uid:
            self.recorder.update_metadata(uid, {
                "driver_a_index": self.driver_a_index,
                "driver_b_index": self.driver_b_index,
                "driver_a_name": self._driver_name(self.driver_a_index),
                "driver_b_name": self._driver_name(self.driver_b_index),
            })

    def _ingest_active_career(self, session_uid: int, final_json: Mapping[str, Any]) -> None:
        career_id = self.database.get_preference("active_career_id")
        if not career_id:
            return
        career = self.database.get_career(int(career_id))
        if not career:
            return
        session_type = str(self.session_state.m_session_info.m_session_type or "race").casefold()
        event_type = "sprint" if "sprint" in session_type else "qualifying" if "qual" in session_type else "race"
        results: List[CareerResult] = []
        for entry in final_json.get("classification-data") or []:
            result = entry.get("final-classification") or {}
            name = str(entry.get("driver-name") or f"Car {entry.get('index', 0) + 1}")
            result_status = str(result.get("result-status") or result.get("result-reason") or "")
            results.append(CareerResult(
                driver_key=name.casefold(),
                driver_name=name,
                position=int(entry.get("track-position") or result.get("position") or 99),
                team=entry.get("team"),
                grid_position=result.get("grid-position"),
                classified="disqualified" not in result_status.casefold(),
                fastest_lap=bool(entry.get("is-fastest")),
                dnf=any(token in result_status.casefold() for token in ("dnf", "retired", "not classified")),
            ))
        if not results:
            return
        try:
            self.database.ingest_event(
                int(career_id), session_uid, int(career["current_round"]) + 1,
                str(self.session_state.m_session_info.m_track or "Unknown"), event_type, results,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            self.logger.exception("Could not ingest session %s into career %s", session_uid, career_id)
