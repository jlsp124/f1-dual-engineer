from pathlib import Path
from types import SimpleNamespace

from lib.config.schema.engineer import EngineerSettings
from lib.dual_engineer.service import DualEngineerService
from lib.dual_engineer.snapshot import (
    detailed_telemetry_available,
    live_telemetry_json,
    telemetry_sample_from_state,
)
from lib.f1_types import F1PacketType, PacketHeader, SafetyCarType, TelemetrySetting


def _driver(name: str, setting=TelemetrySetting.PUBLIC):
    telemetry = SimpleNamespace(
        m_speed=281, m_throttle=0.82, m_steer=-0.12, m_brake=0.0,
        m_gear=7, m_engineRPM=11320, m_drs=True,
        m_tyresSurfaceTemperature=[91, 92, 88, 89],
        m_tyresInnerTemperature=[99, 100, 96, 97],
    )
    motion = SimpleNamespace(
        m_gForceLateral=2.3, m_gForceLongitudinal=0.8,
        m_worldPositionX=12.5, m_worldPositionZ=-31.0,
    )
    status = SimpleNamespace(
        m_fuelInTank=35.4, m_fuelRemainingLaps=0.62,
        m_ersStoreEnergy=2_000_000, m_ersDeployedThisLap=600_000,
        m_ersHarvestedThisLapMGUK=200_000, m_ersHarvestedThisLapMGUH=100_000,
        m_ersDeployMode="Medium", m_visualTyreCompound="Medium", m_tyresAgeLaps=4,
    )
    damage = SimpleNamespace(
        m_tyresWear=[20.0, 21.0, 18.0, 19.0],
        m_frontLeftWingDamage=0, m_frontRightWingDamage=0, m_rearWingDamage=0,
        m_floorDamage=0, m_diffuserDamage=0, m_sidepodDamage=0,
    )
    lap = SimpleNamespace(
        m_currentLapNum=3, m_lapDistance=1420.0, m_currentLapTimeInMS=28650,
        m_currentLapInvalid=False, m_pitStatus=SimpleNamespace(value=0),
        m_deltaToCarInFrontInMS=850,
    )
    return SimpleNamespace(
        is_valid=True,
        m_driver_info=SimpleNamespace(name=name, team="Apex", position=1, telemetry_setting=setting),
        m_packet_copies=SimpleNamespace(
            m_packet_car_telemetry=telemetry,
            m_packet_motion=motion,
            m_packet_car_status=status,
            m_packet_car_damage=damage,
            m_packet_lap_data=lap,
        ),
    )


def _state(drivers, primary=0, secondary=1, uid=123):
    return SimpleNamespace(
        m_driver_data=list(drivers),
        m_player_index=primary,
        m_secondary_player_index=secondary,
        m_session_info=SimpleNamespace(
            m_session_uid=uid,
            curr_weather="Dry",
            m_safety_car_status=SafetyCarType.NO_SAFETY_CAR,
            m_session_type="Race",
            m_track="Hungaroring",
        ),
    )


def test_secondary_local_car_remains_available_when_telemetry_setting_is_restricted():
    state = _state([_driver("A"), _driver("B", TelemetrySetting.RESTRICTED)])
    assert detailed_telemetry_available(state, 1)
    assert live_telemetry_json(state, 1, state.m_driver_data[1])["speed-kph"] == 281


def test_remote_restricted_telemetry_is_null_not_zero():
    state = _state([_driver("A"), _driver("B"), _driver("REMOTE", TelemetrySetting.RESTRICTED)])
    snapshot = live_telemetry_json(state, 2, state.m_driver_data[2])
    assert snapshot["available"] is False
    assert snapshot["speed-kph"] is None
    assert snapshot["fuel-kg"] is None
    assert snapshot["tyre-wear"] is None
    assert snapshot["damage-percent"] is None
    assert snapshot["world-x"] == 12.5  # public race-context position remains usable by the map


def test_structured_sample_preserves_privacy_and_timing_context():
    state = _state([_driver("A"), _driver("B"), _driver("REMOTE", TelemetrySetting.RESTRICTED)])
    sample = telemetry_sample_from_state(state, 123, 2, timestamp=100.0)
    assert sample is not None
    assert sample.telemetry_public is False
    assert sample.speed_kph is None
    assert sample.lap_distance_m == 1420.0
    assert sample.world_x == 12.5


def test_selection_persists_by_name_across_participant_reordering(tmp_path: Path):
    settings = EngineerSettings(export_directory=str(tmp_path))
    first = DualEngineerService(_state([_driver("ONE"), _driver("TWO"), _driver("THREE")]), settings, SimpleNamespace(is_set=lambda: False))
    first.set_selection(1, 2)

    reordered = DualEngineerService(
        _state([_driver("THREE"), _driver("ONE"), _driver("TWO")], primary=1, secondary=None),
        settings,
        SimpleNamespace(is_set=lambda: False),
    )
    reordered.on_participants_update()
    assert reordered.driver_a_index == 2
    assert reordered.driver_b_index == 0


def test_raw_capture_ignores_wrong_or_inactive_session_uid(tmp_path: Path):
    settings = EngineerSettings(export_directory=str(tmp_path))
    state = _state([_driver("ONE"), _driver("TWO")], uid=123)
    service = DualEngineerService(state, settings, SimpleNamespace(is_set=lambda: False))
    inactive = PacketHeader.from_values(2025, 25, 1, 0, 1, F1PacketType.MOTION, 999, 0.1, 1, 1, 0, 1).to_bytes()
    active = PacketHeader.from_values(2025, 25, 1, 0, 1, F1PacketType.MOTION, 123, 0.2, 2, 2, 0, 1).to_bytes()
    service.on_raw_packet(inactive)
    assert service.recorder.queue.qsize() == 0
    service.on_raw_packet(active)
    assert service.recorder.queue.qsize() == 1


def test_active_race_projects_imported_career_standings(tmp_path: Path):
    settings = EngineerSettings(export_directory=str(tmp_path))
    state = _state([_driver("JOV"), _driver("JAX")], uid=321)
    state.m_driver_data[0].m_driver_info.position = 1
    state.m_driver_data[1].m_driver_info.position = 2
    service = DualEngineerService(state, settings, SimpleNamespace(is_set=lambda: False))
    service.driver_a_index = 0
    service.driver_b_index = 1
    detail = service.create_career({
        "season_name": "Test season",
        "driver_a_key": "jov",
        "driver_b_key": "jax",
    })
    detail = service.import_career_standings(detail["career"]["id"], {
        "current_round": 7,
        "drivers": [
            {"driver_key": "jov", "driver_name": "JOV", "team": "Apex", "points": 100},
            {"driver_key": "jax", "driver_name": "JAX", "team": "Apex", "points": 110},
        ],
        "constructors": {"Apex": 210},
    })

    assert detail["projection_active"] is True
    projected = {row["driver_key"]: row for row in detail["projected_driver_standings"]}
    assert projected["jov"]["points"] == 125
    assert projected["jov"]["projected_delta"] == 25
    assert projected["jax"]["points"] == 128
    assert projected["jax"]["projected_delta"] == 18
    assert detail["projected_constructor_standings"][0]["points"] == 253
