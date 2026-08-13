# MIT License
# Copyright (c) 2026 F1 Dual Engineer contributors

"""Privacy-aware snapshots from the upstream single-writer session state."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from apps.backend.state_mgmt_layer.data_per_driver import DataPerDriver
from apps.backend.state_mgmt_layer.session_state import SessionState
from lib.f1_types import CarStatusData, SafetyCarType

from .models import TelemetrySample


def detailed_telemetry_available(session_state: SessionState, driver_index: int) -> bool:
    """Return whether private car telemetry may be represented for a driver.

    The game always exposes the local primary/secondary cars to their own UDP
    stream. Other human participants are only detailed when their Your
    Telemetry preference is Public. Unknown is treated as restricted.
    """

    if driver_index in {
        session_state.m_player_index,
        session_state.m_secondary_player_index,
    }:
        return True
    if not 0 <= driver_index < len(session_state.m_driver_data):
        return False
    driver = session_state.m_driver_data[driver_index]
    setting = driver.m_driver_info.telemetry_setting if driver else None
    return bool(setting) if setting is not None else False


def _four(values: Any) -> Optional[Tuple[float, float, float, float]]:
    if values is None or len(values) != 4:
        return None
    return tuple(float(value) for value in values)


def _damage_max(driver: DataPerDriver) -> Optional[float]:
    damage = driver.m_packet_copies.m_packet_car_damage
    if not damage:
        return None
    values = (
        damage.m_frontLeftWingDamage,
        damage.m_frontRightWingDamage,
        damage.m_rearWingDamage,
        damage.m_floorDamage,
        damage.m_diffuserDamage,
        damage.m_sidepodDamage,
    )
    return float(max(values))


def live_telemetry_json(
    session_state: SessionState,
    driver_index: int,
    driver: DataPerDriver,
) -> Dict[str, Any]:
    """Return dashboard-ready telemetry without inventing restricted values."""

    available = detailed_telemetry_available(session_state, driver_index)
    telemetry = driver.m_packet_copies.m_packet_car_telemetry if available else None
    motion = driver.m_packet_copies.m_packet_motion
    status = driver.m_packet_copies.m_packet_car_status if available else None
    damage = driver.m_packet_copies.m_packet_car_damage if available else None
    lap = driver.m_packet_copies.m_packet_lap_data
    return {
        "available": available,
        "status": "Available" if available else "Unavailable",
        "speed-kph": telemetry.m_speed if telemetry else None,
        "throttle": telemetry.m_throttle if telemetry else None,
        "brake": telemetry.m_brake if telemetry else None,
        "steering": telemetry.m_steer if telemetry else None,
        "gear": telemetry.m_gear if telemetry else None,
        "rpm": telemetry.m_engineRPM if telemetry else None,
        "g-lateral": motion.m_gForceLateral if motion and available else None,
        "g-longitudinal": motion.m_gForceLongitudinal if motion and available else None,
        "tyre-surface-temps": list(telemetry.m_tyresSurfaceTemperature) if telemetry else None,
        "tyre-inner-temps": list(telemetry.m_tyresInnerTemperature) if telemetry else None,
        "tyre-wear": list(damage.m_tyresWear) if damage else None,
        "fuel-kg": status.m_fuelInTank if status else None,
        "fuel-delta-laps": status.m_fuelRemainingLaps if status else None,
        "ers-store-percent": (
            (status.m_ersStoreEnergy / CarStatusData.MAX_ERS_STORE_ENERGY) * 100.0
            if status else None
        ),
        "ers-deployed-percent": (
            (status.m_ersDeployedThisLap / CarStatusData.MAX_ERS_STORE_ENERGY) * 100.0
            if status else None
        ),
        "ers-harvested-percent": (
            (
                status.m_ersHarvestedThisLapMGUK
                + status.m_ersHarvestedThisLapMGUH
            ) / CarStatusData.MAX_ERS_STORE_ENERGY * 100.0
            if status else None
        ),
        "ers-mode": str(status.m_ersDeployMode) if status else None,
        "drs": telemetry.m_drs if telemetry else None,
        "damage-percent": _damage_max(driver) if available else None,
        "pit": bool(lap and lap.m_pitStatus.value != 0),
        # Motion position is part of the public race context used by the map.
        "world-x": motion.m_worldPositionX if motion else None,
        "world-z": motion.m_worldPositionZ if motion else None,
        # F1 25 Motion Ex arrays only describe the local player car. They are
        # intentionally unavailable for arbitrary remote-driver comparisons.
        "wheel-speeds": None,
        "wheel-slip-ratios": None,
        "wheel-slip-angles": None,
    }


def telemetry_sample_from_state(
    session_state: SessionState,
    session_uid: int,
    driver_index: int,
    *,
    timestamp: Optional[float] = None,
) -> Optional[TelemetrySample]:
    """Build one structured sample, or ``None`` until core timing exists."""

    if not 0 <= driver_index < len(session_state.m_driver_data):
        return None
    driver = session_state.m_driver_data[driver_index]
    if not driver:
        return None
    lap = driver.m_packet_copies.m_packet_lap_data
    if not lap or lap.m_currentLapNum <= 0:
        return None
    details = live_telemetry_json(session_state, driver_index, driver)
    status = driver.m_packet_copies.m_packet_car_status if details["available"] else None
    tyre_compound = str(status.m_visualTyreCompound) if status else None
    weather = session_state.m_session_info.curr_weather
    safety_car = session_state.m_session_info.m_safety_car_status
    return TelemetrySample(
        timestamp=timestamp or time.time(),
        session_uid=session_uid,
        driver_index=driver_index,
        driver_name=driver.m_driver_info.name or f"Car {driver_index + 1}",
        lap_number=lap.m_currentLapNum,
        lap_distance_m=max(0.0, float(lap.m_lapDistance)),
        lap_time_ms=float(lap.m_currentLapTimeInMS),
        telemetry_public=bool(details["available"]),
        lap_valid=not lap.m_currentLapInvalid,
        pit=bool(details["pit"]),
        speed_kph=details["speed-kph"],
        throttle=details["throttle"],
        brake=details["brake"],
        steering=details["steering"],
        gear=details["gear"],
        rpm=details["rpm"],
        g_lateral=details["g-lateral"],
        g_longitudinal=details["g-longitudinal"],
        world_x=details["world-x"],
        world_z=details["world-z"],
        tyre_surface_temps=_four(details["tyre-surface-temps"]),
        tyre_inner_temps=_four(details["tyre-inner-temps"]),
        tyre_wear=_four(details["tyre-wear"]),
        tyre_compound=tyre_compound,
        tyre_age_laps=status.m_tyresAgeLaps if status else None,
        fuel_kg=details["fuel-kg"],
        fuel_delta_laps=details["fuel-delta-laps"],
        ers_store_pct=details["ers-store-percent"],
        ers_deployed_pct=details["ers-deployed-percent"],
        ers_harvested_pct=details["ers-harvested-percent"],
        ers_mode=details["ers-mode"],
        drs=details["drs"],
        damage_pct=details["damage-percent"],
        traffic=0 < lap.m_deltaToCarInFrontInMS < 1000,
        safety_car=bool(
            safety_car is not None and safety_car != SafetyCarType.NO_SAFETY_CAR
        ),
        weather=str(weather) if weather is not None else None,
    )
