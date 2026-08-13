# MIT License
# Copyright (c) 2026 F1 Dual Engineer contributors

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Dict, Optional, Sequence, Tuple


Float4 = Tuple[float, float, float, float]


def csv_safe_value(value: Any) -> Any:
    """Keep untrusted text inert when a CSV is opened in a spreadsheet."""
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    """One analysis-friendly observation for one participant.

    Every field that the game can hide is optional. A missing value remains
    ``None`` all the way through analysis and presentation.
    """

    timestamp: float
    session_uid: int
    driver_index: int
    driver_name: str
    lap_number: int
    lap_distance_m: float
    lap_time_ms: float
    telemetry_public: bool = True
    lap_valid: bool = True
    pit: bool = False
    speed_kph: Optional[float] = None
    throttle: Optional[float] = None
    brake: Optional[float] = None
    steering: Optional[float] = None
    gear: Optional[int] = None
    rpm: Optional[int] = None
    g_lateral: Optional[float] = None
    g_longitudinal: Optional[float] = None
    world_x: Optional[float] = None
    world_z: Optional[float] = None
    wheel_speeds: Optional[Float4] = None
    wheel_slip_ratios: Optional[Float4] = None
    wheel_slip_angles: Optional[Float4] = None
    tyre_surface_temps: Optional[Float4] = None
    tyre_inner_temps: Optional[Float4] = None
    tyre_wear: Optional[Float4] = None
    tyre_compound: Optional[str] = None
    tyre_age_laps: Optional[int] = None
    fuel_kg: Optional[float] = None
    fuel_delta_laps: Optional[float] = None
    ers_store_pct: Optional[float] = None
    ers_deployed_pct: Optional[float] = None
    ers_harvested_pct: Optional[float] = None
    ers_mode: Optional[str] = None
    drs: Optional[bool] = None
    damage_pct: Optional[float] = None
    traffic: bool = False
    safety_car: bool = False
    weather: Optional[str] = None

    @classmethod
    def csv_columns(cls) -> Tuple[str, ...]:
        return tuple(item.name for item in fields(cls))

    def to_row(self) -> Dict[str, Any]:
        row: Dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            serialized = "|".join(str(v) for v in value) if isinstance(value, tuple) else value
            row[item.name] = csv_safe_value(serialized)
        return row


@dataclass(frozen=True, slots=True)
class LapTrace:
    driver_index: int
    driver_name: str
    lap_number: int
    samples: Tuple[TelemetrySample, ...]
    total_time_ms: Optional[int] = None
    valid: bool = True
    pit_lap: bool = False
    formation_lap: bool = False
    safety_car: bool = False
    incident: bool = False
    flashback: bool = False
    telemetry_discontinuity: bool = False
    compound: Optional[str] = None
    tyre_age_laps: Optional[int] = None
    fuel_start_kg: Optional[float] = None
    weather: Optional[str] = None
    damage_pct: Optional[float] = None
    session_type: Optional[str] = None
    equal_performance: Optional[bool] = None

    @classmethod
    def from_samples(
        cls,
        samples: Sequence[TelemetrySample],
        **overrides: Any,
    ) -> "LapTrace":
        if not samples:
            raise ValueError("LapTrace requires at least one sample")
        ordered = tuple(sorted(samples, key=lambda sample: (sample.lap_distance_m, sample.lap_time_ms)))
        first = ordered[0]
        defaults: Dict[str, Any] = {
            "driver_index": first.driver_index,
            "driver_name": first.driver_name,
            "lap_number": first.lap_number,
            "samples": ordered,
            "total_time_ms": round(ordered[-1].lap_time_ms),
            "valid": all(sample.lap_valid for sample in ordered),
            "pit_lap": any(sample.pit for sample in ordered),
            "safety_car": any(sample.safety_car for sample in ordered),
            "compound": next((sample.tyre_compound for sample in ordered if sample.tyre_compound), None),
            "tyre_age_laps": next((sample.tyre_age_laps for sample in ordered if sample.tyre_age_laps is not None), None),
            "fuel_start_kg": next((sample.fuel_kg for sample in ordered if sample.fuel_kg is not None), None),
            "weather": next((sample.weather for sample in ordered if sample.weather), None),
            "damage_pct": max((sample.damage_pct for sample in ordered if sample.damage_pct is not None), default=None),
        }
        defaults.update(overrides)
        return cls(**defaults)

    @property
    def comparable(self) -> bool:
        return bool(
            self.valid
            and not self.pit_lap
            and not self.formation_lap
            and not self.safety_car
            and not self.incident
            and not self.flashback
            and not self.telemetry_discontinuity
            and len(self.samples) >= 3
        )


@dataclass(frozen=True, slots=True)
class LapSummary:
    driver_name: str
    lap_number: int
    lap_time_ms: int
    sectors_ms: Tuple[int, int, int]
    mini_sectors_ms: Tuple[int, ...] = field(default_factory=tuple)
    valid: bool = True
    pit_lap: bool = False
    formation_lap: bool = False
    safety_car: bool = False
    incident: bool = False
    flashback: bool = False
    telemetry_discontinuity: bool = False

    @property
    def representative(self) -> bool:
        return bool(
            self.valid
            and not self.pit_lap
            and not self.formation_lap
            and not self.safety_car
            and not self.incident
            and not self.flashback
            and not self.telemetry_discontinuity
            and self.lap_time_ms > 0
            and all(value > 0 for value in self.sectors_ms)
        )
