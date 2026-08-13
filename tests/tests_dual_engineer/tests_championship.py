from lib.dual_engineer.championship import (
    ClassificationEntry,
    PointsRules,
    Standing,
    project_constructor_standings,
    project_standings,
)


def test_default_f1_25_points_do_not_award_fastest_lap_bonus():
    rules = PointsRules()
    assert rules.points_for(1, fastest_lap=True) == 25
    assert rules.points_for(10) == 1
    assert rules.points_for(11) == 0
    assert rules.points_for(1, session_type="sprint") == 8


def test_projected_driver_standings_rank_and_delta():
    existing = [Standing("jov", "JOV", 117), Standing("jax", "JAX", 121)]
    classification = [
        ClassificationEntry("jov", "JOV", 1, "Apex"),
        ClassificationEntry("jax", "JAX", 3, "Apex"),
    ]
    projected = project_standings(existing, classification)

    assert [(item.driver_name, item.points, item.rank) for item in projected] == [
        ("JOV", 142, 1),
        ("JAX", 136, 2),
    ]
    assert projected[0].projected_delta == 25


def test_projected_constructor_standings_support_custom_rules():
    rules = PointsRules(race_points=(10, 6, 4), sprint_points=(3, 2, 1))
    result = project_constructor_standings(
        {"Apex": 20, "Vector": 22},
        [
            ClassificationEntry("a", "A", 1, "Apex"),
            ClassificationEntry("b", "B", 2, "Vector"),
        ],
        rules=rules,
    )
    assert result == (("Apex", 30), ("Vector", 28))
