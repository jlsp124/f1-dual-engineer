# MIT License
# Copyright (c) 2026 F1 Dual Engineer contributors

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True, slots=True)
class PointsRules:
    race_points: Tuple[int, ...] = (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)
    sprint_points: Tuple[int, ...] = (8, 7, 6, 5, 4, 3, 2, 1)
    fastest_lap_bonus: int = 0
    fastest_lap_top_n: int = 10

    def points_for(self, position: int, session_type: str = "race", fastest_lap: bool = False) -> int:
        table = self.sprint_points if session_type.casefold() == "sprint" else self.race_points
        base = table[position - 1] if 1 <= position <= len(table) else 0
        bonus = self.fastest_lap_bonus if fastest_lap and position <= self.fastest_lap_top_n else 0
        return base + bonus


@dataclass(frozen=True, slots=True)
class ClassificationEntry:
    driver_id: str
    driver_name: str
    position: int
    team: Optional[str] = None
    classified: bool = True
    fastest_lap: bool = False


@dataclass(frozen=True, slots=True)
class Standing:
    driver_id: str
    driver_name: str
    points: int
    projected_delta: int = 0
    rank: int = 0
    team: Optional[str] = None


def project_standings(
    existing: Sequence[Standing],
    classification: Sequence[ClassificationEntry],
    *,
    rules: PointsRules = PointsRules(),
    session_type: str = "race",
) -> Tuple[Standing, ...]:
    """Project driver standings if the observed classification ended now."""
    table: Dict[str, Standing] = {item.driver_id: item for item in existing}
    earned: Dict[str, int] = {}
    for entry in classification:
        if not entry.classified:
            earned[entry.driver_id] = 0
            continue
        earned[entry.driver_id] = rules.points_for(entry.position, session_type, entry.fastest_lap)
        if entry.driver_id not in table:
            table[entry.driver_id] = Standing(entry.driver_id, entry.driver_name, 0, team=entry.team)

    projected = [
        Standing(
            driver_id=item.driver_id,
            driver_name=item.driver_name,
            points=item.points + earned.get(item.driver_id, 0),
            projected_delta=earned.get(item.driver_id, 0),
            team=item.team,
        )
        for item in table.values()
    ]
    projected.sort(key=lambda item: (-item.points, item.driver_name.casefold(), item.driver_id))
    return tuple(
        Standing(
            driver_id=item.driver_id,
            driver_name=item.driver_name,
            points=item.points,
            projected_delta=item.projected_delta,
            rank=index,
            team=item.team,
        )
        for index, item in enumerate(projected, start=1)
    )


def project_constructor_standings(
    existing_points: Mapping[str, int],
    classification: Iterable[ClassificationEntry],
    *,
    rules: PointsRules = PointsRules(),
    session_type: str = "race",
) -> Tuple[Tuple[str, int], ...]:
    points = dict(existing_points)
    for entry in classification:
        if entry.team and entry.classified:
            points[entry.team] = points.get(entry.team, 0) + rules.points_for(
                entry.position, session_type, entry.fastest_lap
            )
    return tuple(sorted(points.items(), key=lambda item: (-item[1], item[0].casefold())))
