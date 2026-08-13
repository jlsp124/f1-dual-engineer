from pathlib import Path

from lib.dual_engineer.career import CareerDatabase, CareerResult


def _results(a_position=1, b_position=3):
    return [
        CareerResult("jov", "JOV", a_position, "Apex", grid_position=2, fastest_lap=True),
        CareerResult("jax", "JAX", b_position, "Apex", grid_position=1),
    ]


def test_career_import_ingestion_and_idempotent_final_classification(tmp_path: Path):
    database = CareerDatabase(tmp_path / "career.sqlite")
    career_id = database.create_career("Co-op 2026", "F1 25", "jov", "jax", calendar=["Hungary"])
    database.import_standings(
        career_id,
        [
            {"driver_key": "jov", "driver_name": "JOV", "team": "Apex", "points": 117},
            {"driver_key": "jax", "driver_name": "JAX", "team": "Apex", "points": 121},
        ],
        {"Apex": 238},
        current_round=5,
    )

    event_id = database.ingest_event(career_id, 99, 6, "Hungary", "race", _results())
    same_event_id = database.ingest_event(career_id, 99, 6, "Hungary", "race", _results())

    assert same_event_id == event_id
    standings = database.driver_standings(career_id)
    assert [(row["driver_name"], row["points"]) for row in standings] == [("JOV", 142), ("JAX", 136)]
    assert database.constructor_standings(career_id)[0]["points"] == 278


def test_manual_result_correction_recomputes_local_standings(tmp_path: Path):
    database = CareerDatabase(tmp_path / "career.sqlite")
    career_id = database.create_career("Season", "F1 25", "jov", "jax")
    event_id = database.ingest_event(career_id, "abc", 1, "Bahrain", "race", _results())

    database.correct_result(event_id, "jax", position=1, points=25)
    standings = database.driver_standings(career_id)

    assert standings[0]["driver_name"] == "JAX"
    assert standings[0]["points"] == 25


def test_head_to_head_tracks_qualifying_race_and_sprint(tmp_path: Path):
    database = CareerDatabase(tmp_path / "career.sqlite")
    career_id = database.create_career("Season", "F1 25", "jov", "jax")
    database.ingest_event(career_id, "q1", 1, "Bahrain", "qualifying", _results(2, 1))
    database.ingest_event(career_id, "r1", 1, "Bahrain", "race", _results(1, 3))
    database.ingest_event(career_id, "s2", 2, "China", "sprint", _results(4, 2))

    head_to_head = database.head_to_head(career_id)
    assert head_to_head["qualifying_h2h"] == [0, 1]
    assert head_to_head["race_h2h"] == [1, 0]
    assert head_to_head["sprint_h2h"] == [0, 1]


def test_session_catalog_and_preferences_persist(tmp_path: Path):
    database = CareerDatabase(tmp_path / "career.sqlite")
    folder = tmp_path / "exports" / "Hungary"
    metadata = {"track": "Hungary", "session_type": "Race", "started_at": "2026-08-12T10:00:00Z"}
    database.register_session(42, folder, metadata)
    database.finalize_session(42, folder, {**metadata, "ended_at": "2026-08-12T12:00:00Z"})
    database.set_preference("driver_selection", {"a": "jov", "b": "jax"})

    assert database.list_sessions()[0]["finalized"] is True
    assert database.get_preference("driver_selection") == {"a": "jov", "b": "jax"}
