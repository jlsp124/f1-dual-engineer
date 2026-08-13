from __future__ import annotations

import pytest

from lib.dual_engineer.analysis import (
    analyze_laps,
    calculate_theoretical_lap,
    evaluate_reference_quality,
    synchronize_laps,
)
from lib.dual_engineer.models import LapSummary, LapTrace, TelemetrySample


def _sample(
    driver: str,
    index: int,
    distance: float,
    time_ms: float,
    speed: float,
    brake: float,
    throttle: float,
    *,
    steering: float = 0.0,
    lap: int = 3,
    valid: bool = True,
    pit: bool = False,
) -> TelemetrySample:
    return TelemetrySample(
        timestamp=time_ms / 1000,
        session_uid=7,
        driver_index=index,
        driver_name=driver,
        lap_number=lap,
        lap_distance_m=distance,
        lap_time_ms=time_ms,
        speed_kph=speed,
        brake=brake,
        throttle=throttle,
        steering=steering,
        lap_valid=valid,
        pit=pit,
        tyre_compound="Medium",
        tyre_age_laps=2,
        fuel_kg=50.0,
        weather="Dry",
    )


def _trace(driver: str, index: int, points, **kwargs) -> LapTrace:
    return LapTrace.from_samples(
        [_sample(driver, index, *point) for point in points],
        compound="Medium",
        tyre_age_laps=2,
        fuel_start_kg=50.0,
        weather="Dry",
        **kwargs,
    )


def test_synchronize_laps_uses_distance_not_packet_timestamps():
    reference = _trace("JAX", 1, [
        (0, 0, 300, 0, 1),
        (100, 1000, 250, 0.4, 0),
        (200, 2500, 180, 0, 0.3),
        (300, 4000, 260, 0, 1),
    ])
    target = _trace("JOV", 0, [
        (0, 100, 300, 0, 1),
        (75, 1050, 240, 0.5, 0),
        (225, 3100, 170, 0, 0.4),
        (300, 4300, 250, 0, 1),
    ])
    points = synchronize_laps(target, reference, step_m=50)

    assert points[0].delta_ms == pytest.approx(0)
    assert points[-1].distance_m == pytest.approx(300)
    assert points[-1].delta_ms == pytest.approx(200)


@pytest.mark.parametrize("override", [{"valid": False}, {"pit_lap": True}, {"flashback": True}])
def test_synchronize_rejects_contaminated_laps(override):
    trace = _trace("JOV", 0, [
        (0, 0, 200, 0, 1),
        (50, 1000, 150, 0.5, 0),
        (100, 2000, 220, 0, 1),
    ], **override)
    clean = _trace("JAX", 1, [
        (0, 0, 200, 0, 1),
        (50, 900, 160, 0.5, 0),
        (100, 1800, 230, 0, 1),
    ])
    with pytest.raises(ValueError, match="clean, representative"):
        synchronize_laps(trace, clean)


def test_analysis_identifies_explainable_over_slowing_and_phase_split():
    reference = _trace("JAX", 1, [
        (0, 0, 300, 0, 1),
        (80, 700, 290, 0, 1),
        (120, 1200, 250, 0.7, 0),
        (180, 2200, 170, 0.3, 0.1),
        (220, 2900, 180, 0, 0.5),
        (280, 3700, 250, 0, 1),
        (340, 4300, 290, 0, 1),
    ])
    target = _trace("JOV", 0, [
        (0, 0, 300, 0, 1),
        (60, 600, 285, 0.3, 0),
        (100, 1250, 235, 0.8, 0),
        (180, 2500, 155, 0.4, 0.1),
        (230, 3300, 170, 0, 0.4),
        (300, 4300, 235, 0, 1),
        (340, 4800, 275, 0, 1),
    ])
    result = analyze_laps(target, reference, step_m=10, segment_labels={(0, 340): "T5"})
    largest = result.segments[0]

    assert result.representative_gap_ms == pytest.approx(500)
    assert largest.label == "T5"
    assert largest.diagnosis == "Over-slowing"
    assert largest.brake_point_difference_m is not None and largest.brake_point_difference_m < 0
    assert largest.minimum_speed_difference_kph is not None and largest.minimum_speed_difference_kph < -5
    assert largest.entry_loss_ms + largest.mid_loss_ms + largest.exit_loss_ms == pytest.approx(largest.time_loss_ms)
    assert largest.confidence in {"Medium", "High"}


def test_reference_quality_reports_context():
    left = _trace("A", 0, [
        (0, 0, 200, 0, 1), (50, 1000, 150, 0.3, 0), (100, 2000, 220, 0, 1)
    ])
    right = _trace("B", 1, [
        (0, 0, 200, 0, 1), (50, 1000, 150, 0.3, 0), (100, 2000, 220, 0, 1)
    ])
    quality = evaluate_reference_quality(left, right)
    assert quality.label == "HIGH"
    assert "Same compound" in quality.reasons
    assert "Clean air" in quality.reasons


def test_theoretical_lap_filters_garbage_and_uses_best_clean_minisectors():
    laps = [
        LapSummary("JOV", 1, 90000, (30000, 31000, 29000), (15000, 15000, 15500, 15500, 14500, 14500)),
        LapSummary("JOV", 2, 89500, (29800, 30900, 28800), (14900, 14900, 15400, 15400, 14450, 14450)),
        LapSummary("JOV", 3, 87000, (29000, 29000, 29000), (14000,) * 6, valid=False),
        LapSummary("JOV", 4, 91000, (30100, 31500, 29400), (15100, 15000, 15600, 15700, 14600, 14500)),
        LapSummary("JOV", 5, 88000, (29500, 30000, 28500), (14500,) * 6, pit_lap=True),
    ]
    result = calculate_theoretical_lap(laps)

    assert result.eligible_laps == 3
    assert result.personal_best_ms == 89500
    assert result.best_clean_sectors_ms == (29800, 30900, 28800)
    assert result.theoretical_mini_sector_lap_ms == sum((14900, 14900, 15400, 15400, 14450, 14450))
    assert result.untapped_ms == result.personal_best_ms - result.theoretical_lap_ms
    assert result.best_three_average_ms == pytest.approx((90000 + 89500 + 91000) / 3)
