# MIT License
# Copyright (c) 2026 F1 Dual Engineer contributors

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from statistics import fmean, pstdev
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .models import LapSummary, LapTrace, TelemetrySample


@dataclass(frozen=True, slots=True)
class SyncedPoint:
    distance_m: float
    target_time_ms: float
    reference_time_ms: float
    delta_ms: float
    target: Dict[str, Optional[float]]
    reference: Dict[str, Optional[float]]


@dataclass(frozen=True, slots=True)
class ReferenceQuality:
    label: str
    score: int
    reasons: Tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SegmentAnalysis:
    label: str
    start_m: float
    end_m: float
    time_loss_ms: float
    entry_loss_ms: float
    mid_loss_ms: float
    exit_loss_ms: float
    brake_point_difference_m: Optional[float]
    brake_duration_difference_m: Optional[float]
    peak_brake_difference: Optional[float]
    minimum_speed_difference_kph: Optional[float]
    throttle_pickup_difference_m: Optional[float]
    full_throttle_difference_m: Optional[float]
    exit_speed_difference_kph: Optional[float]
    steering_correction_difference: Optional[int]
    path_difference_m: Optional[float]
    diagnosis: str
    confidence: str
    evidence: Tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LapComparison:
    target_driver: str
    reference_driver: str
    target_lap: int
    reference_lap: int
    representative_gap_ms: float
    entry_loss_ms: float
    mid_loss_ms: float
    exit_loss_ms: float
    reference_quality: ReferenceQuality
    segments: Tuple[SegmentAnalysis, ...]
    synced_points: Tuple[SyncedPoint, ...]


@dataclass(frozen=True, slots=True)
class TheoreticalLapResult:
    personal_best_ms: Optional[int]
    best_clean_sectors_ms: Optional[Tuple[int, int, int]]
    best_clean_mini_sectors_ms: Tuple[int, ...]
    theoretical_sector_lap_ms: Optional[int]
    theoretical_mini_sector_lap_ms: Optional[int]
    theoretical_lap_ms: Optional[int]
    untapped_ms: Optional[int]
    best_three_average_ms: Optional[float]
    consistency_stddev_ms: Optional[float]
    eligible_laps: int


_INTERPOLATED_FIELDS = (
    "speed_kph",
    "throttle",
    "brake",
    "steering",
    "gear",
    "rpm",
    "g_lateral",
    "g_longitudinal",
    "world_x",
    "world_z",
    "ers_store_pct",
    "ers_deployed_pct",
    "ers_harvested_pct",
)


def _deduplicate_samples(samples: Sequence[TelemetrySample]) -> Tuple[TelemetrySample, ...]:
    by_distance: Dict[float, TelemetrySample] = {}
    for sample in sorted(samples, key=lambda item: (item.lap_distance_m, item.lap_time_ms)):
        if sample.lap_distance_m < 0 or sample.lap_time_ms < 0:
            continue
        by_distance[round(sample.lap_distance_m, 3)] = sample
    return tuple(by_distance[key] for key in sorted(by_distance))


def _interpolate(a: TelemetrySample, b: TelemetrySample, distance_m: float) -> Tuple[float, Dict[str, Optional[float]]]:
    span = b.lap_distance_m - a.lap_distance_m
    ratio = 0.0 if span <= 0 else (distance_m - a.lap_distance_m) / span
    lap_time = a.lap_time_ms + ((b.lap_time_ms - a.lap_time_ms) * ratio)
    values: Dict[str, Optional[float]] = {}
    for name in _INTERPOLATED_FIELDS:
        left = getattr(a, name)
        right = getattr(b, name)
        if left is None or right is None:
            values[name] = None
        else:
            values[name] = float(left) + ((float(right) - float(left)) * ratio)
    rear_slip_a = a.wheel_slip_ratios[:2] if a.wheel_slip_ratios else None
    rear_slip_b = b.wheel_slip_ratios[:2] if b.wheel_slip_ratios else None
    if rear_slip_a and rear_slip_b:
        left = fmean(abs(value) for value in rear_slip_a)
        right = fmean(abs(value) for value in rear_slip_b)
        values["rear_slip"] = left + ((right - left) * ratio)
    else:
        values["rear_slip"] = None
    return lap_time, values


def _resample(samples: Sequence[TelemetrySample], distances: Sequence[float]) -> List[Tuple[float, Dict[str, Optional[float]]]]:
    clean = _deduplicate_samples(samples)
    if len(clean) < 2:
        raise ValueError("At least two monotonic telemetry samples are required")
    output: List[Tuple[float, Dict[str, Optional[float]]]] = []
    cursor = 0
    for distance in distances:
        while cursor + 1 < len(clean) - 1 and clean[cursor + 1].lap_distance_m < distance:
            cursor += 1
        output.append(_interpolate(clean[cursor], clean[cursor + 1], distance))
    return output


def synchronize_laps(target: LapTrace, reference: LapTrace, step_m: float = 5.0) -> Tuple[SyncedPoint, ...]:
    """Synchronize two clean laps by distance instead of packet time."""
    if not target.comparable or not reference.comparable:
        raise ValueError("Only clean, representative laps can be synchronized")
    if step_m <= 0:
        raise ValueError("step_m must be positive")
    target_samples = _deduplicate_samples(target.samples)
    reference_samples = _deduplicate_samples(reference.samples)
    start = max(target_samples[0].lap_distance_m, reference_samples[0].lap_distance_m)
    end = min(target_samples[-1].lap_distance_m, reference_samples[-1].lap_distance_m)
    if end - start < step_m * 2:
        raise ValueError("Laps do not have enough overlapping track distance")
    count = int((end - start) // step_m)
    distances = [start + index * step_m for index in range(count + 1)]
    if distances[-1] < end:
        distances.append(end)
    target_values = _resample(target_samples, distances)
    reference_values = _resample(reference_samples, distances)
    initial_delta = target_values[0][0] - reference_values[0][0]
    return tuple(
        SyncedPoint(
            distance_m=distance,
            target_time_ms=target_item[0],
            reference_time_ms=reference_item[0],
            delta_ms=(target_item[0] - reference_item[0]) - initial_delta,
            target=target_item[1],
            reference=reference_item[1],
        )
        for distance, target_item, reference_item in zip(distances, target_values, reference_values)
    )


def evaluate_reference_quality(target: LapTrace, reference: LapTrace) -> ReferenceQuality:
    score = 50
    reasons: List[str] = []
    if not target.comparable or not reference.comparable:
        return ReferenceQuality("LOW", 0, ("Invalid, pit, interrupted or contaminated lap",))

    if target.compound and reference.compound:
        if target.compound == reference.compound:
            score += 15
            reasons.append("Same compound")
        else:
            score -= 20
            reasons.append("Different compounds")
    else:
        reasons.append("Compound unavailable")

    if target.tyre_age_laps is not None and reference.tyre_age_laps is not None:
        age_diff = abs(target.tyre_age_laps - reference.tyre_age_laps)
        if age_diff <= 2:
            score += 10
        elif age_diff >= 5:
            score -= 10
        reasons.append(f"Tyre-age difference: {age_diff} lap{'s' if age_diff != 1 else ''}")

    if target.weather and reference.weather:
        if target.weather == reference.weather:
            score += 10
            reasons.append("Weather: same")
        else:
            score -= 25
            reasons.append("Weather mismatch")

    target_traffic = sum(sample.traffic for sample in target.samples) / len(target.samples)
    reference_traffic = sum(sample.traffic for sample in reference.samples) / len(reference.samples)
    if max(target_traffic, reference_traffic) <= 0.1:
        score += 10
        reasons.append("Clean air")
    elif max(target_traffic, reference_traffic) >= 0.3:
        score -= 20
        reasons.append("Traffic detected")

    if target.fuel_start_kg is not None and reference.fuel_start_kg is not None:
        fuel_diff = abs(target.fuel_start_kg - reference.fuel_start_kg)
        if fuel_diff <= 3:
            score += 5
        elif fuel_diff >= 10:
            score -= 10
        reasons.append(f"Fuel difference: {fuel_diff:.1f} kg")

    if target.damage_pct is not None and reference.damage_pct is not None:
        damage_diff = abs(target.damage_pct - reference.damage_pct)
        if damage_diff <= 2:
            score += 5
        elif damage_diff >= 10:
            score -= 15
            reasons.append("Damage mismatch")

    score = max(0, min(100, score))
    label = "HIGH" if score >= 80 else "MEDIUM" if score >= 55 else "LOW"
    return ReferenceQuality(label, score, tuple(reasons or ["Limited context data"]))


def _value(point: SyncedPoint, side: str, field: str) -> Optional[float]:
    return (point.target if side == "target" else point.reference).get(field)


def _delta_at(points: Sequence[SyncedPoint], distance_m: float) -> float:
    nearest = min(points, key=lambda item: abs(item.distance_m - distance_m))
    return nearest.delta_ms


def _detect_braking_segments(points: Sequence[SyncedPoint]) -> List[Tuple[int, int]]:
    segments: List[Tuple[int, int]] = []
    active_start: Optional[int] = None
    minimum_index: Optional[int] = None
    for index, point in enumerate(points):
        brake = _value(point, "reference", "brake") or 0.0
        throttle = _value(point, "reference", "throttle") or 0.0
        speed = _value(point, "reference", "speed_kph")
        if active_start is None and brake >= 0.12:
            active_start = max(0, index - 1)
            minimum_index = index
        if active_start is not None:
            current_min_speed = _value(points[minimum_index], "reference", "speed_kph") if minimum_index is not None else None
            if speed is not None and (current_min_speed is None or speed < current_min_speed):
                minimum_index = index
            if minimum_index is not None and index > minimum_index and brake <= 0.03 and throttle >= 0.9:
                segments.append((active_start, min(len(points) - 1, index + 2)))
                active_start = None
                minimum_index = None
    if active_start is not None:
        segments.append((active_start, len(points) - 1))
    if segments:
        return segments

    # Honest fallback when no braking signal is exposed: stable distance mini-sectors.
    chunk = max(2, len(points) // 10)
    return [(start, min(len(points) - 1, start + chunk)) for start in range(0, len(points) - 1, chunk)]


def _threshold_distance(
    points: Sequence[SyncedPoint],
    side: str,
    field: str,
    threshold: float,
    start_index: int,
    end_index: int,
    greater: bool = True,
) -> Optional[float]:
    for point in points[start_index : end_index + 1]:
        value = _value(point, side, field)
        if value is not None and ((value >= threshold) if greater else (value <= threshold)):
            return point.distance_m
    return None


def _phase_loss(points: Sequence[SyncedPoint], start_m: float, end_m: float) -> float:
    return _delta_at(points, end_m) - _delta_at(points, start_m)


def _steering_corrections(points: Sequence[SyncedPoint], side: str, start: int, end: int) -> Optional[int]:
    values = [_value(point, side, "steering") for point in points[start : end + 1]]
    clean = [value for value in values if value is not None and abs(value) >= 0.08]
    if len(clean) < 3:
        return None
    directions: List[int] = []
    for left, right in zip(clean, clean[1:]):
        delta = right - left
        if abs(delta) >= 0.04:
            directions.append(1 if delta > 0 else -1)
    return sum(left != right for left, right in zip(directions, directions[1:]))


def _mean_path_difference(points: Sequence[SyncedPoint], start: int, end: int) -> Optional[float]:
    diffs: List[float] = []
    for point in points[start : end + 1]:
        tx, tz = _value(point, "target", "world_x"), _value(point, "target", "world_z")
        rx, rz = _value(point, "reference", "world_x"), _value(point, "reference", "world_z")
        if None not in (tx, tz, rx, rz):
            diffs.append(hypot(tx - rx, tz - rz))
    return fmean(diffs) if diffs else None


def _mean(points: Iterable[Optional[float]]) -> Optional[float]:
    clean = [value for value in points if value is not None]
    return fmean(clean) if clean else None


def _segment_label(start_m: float, end_m: float, labels: Optional[Mapping[Tuple[int, int], str]]) -> str:
    if labels:
        midpoint = (start_m + end_m) / 2
        for (label_start, label_end), label in labels.items():
            if label_start <= midpoint <= label_end:
                return label
    return f"{round(start_m):d}-{round(end_m):d}m"


def _analyse_segment(
    points: Sequence[SyncedPoint],
    start: int,
    end: int,
    quality: ReferenceQuality,
    labels: Optional[Mapping[Tuple[int, int], str]],
) -> SegmentAnalysis:
    segment = points[start : end + 1]
    start_m, end_m = segment[0].distance_m, segment[-1].distance_m
    ref_speeds = [(_value(point, "reference", "speed_kph"), index) for index, point in enumerate(segment)]
    ref_speeds = [(speed, index) for speed, index in ref_speeds if speed is not None]
    apex_rel = min(ref_speeds)[1] if ref_speeds else len(segment) // 2
    apex = start + apex_rel
    apex_m = points[apex].distance_m
    entry_end_m = max(start_m, apex_m - 20.0)
    mid_end_m = min(end_m, apex_m + 20.0)
    entry_loss = _phase_loss(points, start_m, entry_end_m)
    mid_loss = _phase_loss(points, entry_end_m, mid_end_m)
    exit_loss = _phase_loss(points, mid_end_m, end_m)
    time_loss = entry_loss + mid_loss + exit_loss

    target_brake = _threshold_distance(points, "target", "brake", 0.12, start, end)
    ref_brake = _threshold_distance(points, "reference", "brake", 0.12, start, end)
    target_release = _threshold_distance(points, "target", "brake", 0.05, apex, end, greater=False)
    ref_release = _threshold_distance(points, "reference", "brake", 0.05, apex, end, greater=False)
    brake_point_diff = target_brake - ref_brake if target_brake is not None and ref_brake is not None else None
    target_duration = target_release - target_brake if target_release is not None and target_brake is not None else None
    ref_duration = ref_release - ref_brake if ref_release is not None and ref_brake is not None else None
    duration_diff = target_duration - ref_duration if target_duration is not None and ref_duration is not None else None

    target_peak = max((_value(point, "target", "brake") for point in segment if _value(point, "target", "brake") is not None), default=None)
    ref_peak = max((_value(point, "reference", "brake") for point in segment if _value(point, "reference", "brake") is not None), default=None)
    peak_diff = target_peak - ref_peak if target_peak is not None and ref_peak is not None else None
    target_min = min((_value(point, "target", "speed_kph") for point in segment if _value(point, "target", "speed_kph") is not None), default=None)
    ref_min = min((_value(point, "reference", "speed_kph") for point in segment if _value(point, "reference", "speed_kph") is not None), default=None)
    min_speed_diff = target_min - ref_min if target_min is not None and ref_min is not None else None

    target_pickup = _threshold_distance(points, "target", "throttle", 0.2, apex, end)
    ref_pickup = _threshold_distance(points, "reference", "throttle", 0.2, apex, end)
    pickup_diff = target_pickup - ref_pickup if target_pickup is not None and ref_pickup is not None else None
    target_full = _threshold_distance(points, "target", "throttle", 0.95, apex, end)
    ref_full = _threshold_distance(points, "reference", "throttle", 0.95, apex, end)
    full_diff = target_full - ref_full if target_full is not None and ref_full is not None else None
    target_exit = _value(points[end], "target", "speed_kph")
    ref_exit = _value(points[end], "reference", "speed_kph")
    exit_speed_diff = target_exit - ref_exit if target_exit is not None and ref_exit is not None else None
    target_corrections = _steering_corrections(points, "target", start, end)
    ref_corrections = _steering_corrections(points, "reference", start, end)
    correction_diff = target_corrections - ref_corrections if target_corrections is not None and ref_corrections is not None else None
    path_diff = _mean_path_difference(points, start, end)
    target_slip = _mean(_value(point, "target", "rear_slip") for point in segment[apex_rel:])
    ref_slip = _mean(_value(point, "reference", "rear_slip") for point in segment[apex_rel:])

    diagnosis = "Uncertain / insufficient data"
    if time_loss <= 20:
        diagnosis = "Gain / neutral"
    elif target_slip is not None and ref_slip is not None and target_slip >= max(0.08, ref_slip * 1.25) and exit_loss >= 35:
        diagnosis = "Traction / exit"
    elif brake_point_diff is not None and brake_point_diff <= -10 and min_speed_diff is not None and min_speed_diff <= -5:
        diagnosis = "Over-slowing"
    elif brake_point_diff is not None and brake_point_diff >= 10 and entry_loss >= 35:
        diagnosis = "Braking too late"
    elif duration_diff is not None and duration_diff >= 15 and min_speed_diff is not None and min_speed_diff <= -4:
        diagnosis = "Braking too long"
    elif full_diff is not None and full_diff >= 10 and exit_loss >= 35:
        diagnosis = "Throttle too late"
    elif path_diff is not None and path_diff >= 2.5 and mid_loss >= 30:
        diagnosis = "Racing-line difference"
    elif correction_diff is not None and correction_diff >= 2 and mid_loss >= 25:
        diagnosis = "Excessive steering corrections"
    elif min_speed_diff is not None and min_speed_diff <= -5 and mid_loss >= 25:
        diagnosis = "Low minimum speed"
    elif exit_speed_diff is not None and exit_speed_diff <= -5 and exit_loss >= 30:
        diagnosis = "Poor corner exit"

    available = sum(
        value is not None
        for value in (brake_point_diff, duration_diff, min_speed_diff, full_diff, exit_speed_diff)
    )
    if diagnosis == "Uncertain / insufficient data" or quality.label == "LOW" or available <= 1:
        confidence = "Low"
    elif quality.label == "HIGH" and available >= 4 and abs(time_loss) >= 80:
        confidence = "High"
    else:
        confidence = "Medium"

    evidence: List[str] = [
        f"Entry {entry_loss / 1000:+.3f}s",
        f"Mid {mid_loss / 1000:+.3f}s",
        f"Exit {exit_loss / 1000:+.3f}s",
    ]
    if brake_point_diff is not None:
        evidence.append(f"Brake point {brake_point_diff:+.0f}m")
    if duration_diff is not None:
        evidence.append(f"Brake duration {duration_diff:+.0f}m")
    if min_speed_diff is not None:
        evidence.append(f"Minimum speed {min_speed_diff:+.0f} km/h")
    if full_diff is not None:
        evidence.append(f"Full throttle {full_diff:+.0f}m")
    if target_slip is not None and ref_slip is not None:
        evidence.append(f"Rear slip {target_slip - ref_slip:+.3f}")

    return SegmentAnalysis(
        label=_segment_label(start_m, end_m, labels),
        start_m=start_m,
        end_m=end_m,
        time_loss_ms=time_loss,
        entry_loss_ms=entry_loss,
        mid_loss_ms=mid_loss,
        exit_loss_ms=exit_loss,
        brake_point_difference_m=brake_point_diff,
        brake_duration_difference_m=duration_diff,
        peak_brake_difference=peak_diff,
        minimum_speed_difference_kph=min_speed_diff,
        throttle_pickup_difference_m=pickup_diff,
        full_throttle_difference_m=full_diff,
        exit_speed_difference_kph=exit_speed_diff,
        steering_correction_difference=correction_diff,
        path_difference_m=path_diff,
        diagnosis=diagnosis,
        confidence=confidence,
        evidence=tuple(evidence),
    )


def analyze_laps(
    target: LapTrace,
    reference: LapTrace,
    *,
    step_m: float = 5.0,
    segment_labels: Optional[Mapping[Tuple[int, int], str]] = None,
) -> LapComparison:
    quality = evaluate_reference_quality(target, reference)
    points = synchronize_laps(target, reference, step_m=step_m)
    segments = tuple(
        _analyse_segment(points, start, end, quality, segment_labels)
        for start, end in _detect_braking_segments(points)
        if end > start
    )
    representative_gap = points[-1].delta_ms
    return LapComparison(
        target_driver=target.driver_name,
        reference_driver=reference.driver_name,
        target_lap=target.lap_number,
        reference_lap=reference.lap_number,
        representative_gap_ms=representative_gap,
        entry_loss_ms=sum(segment.entry_loss_ms for segment in segments),
        mid_loss_ms=sum(segment.mid_loss_ms for segment in segments),
        exit_loss_ms=sum(segment.exit_loss_ms for segment in segments),
        reference_quality=quality,
        segments=tuple(sorted(segments, key=lambda item: item.time_loss_ms, reverse=True)),
        synced_points=points,
    )


def calculate_theoretical_lap(laps: Sequence[LapSummary]) -> TheoreticalLapResult:
    eligible = [lap for lap in laps if lap.representative]
    if not eligible:
        return TheoreticalLapResult(None, None, (), None, None, None, None, None, None, 0)
    personal_best = min(lap.lap_time_ms for lap in eligible)
    best_sectors = tuple(min(lap.sectors_ms[index] for lap in eligible) for index in range(3))
    theoretical_sector = sum(best_sectors)
    mini_lengths = {len(lap.mini_sectors_ms) for lap in eligible if lap.mini_sectors_ms}
    best_mini: Tuple[int, ...] = ()
    theoretical_mini: Optional[int] = None
    if len(mini_lengths) == 1:
        mini_count = next(iter(mini_lengths))
        mini_laps = [lap for lap in eligible if len(lap.mini_sectors_ms) == mini_count and all(value > 0 for value in lap.mini_sectors_ms)]
        if mini_laps:
            best_mini = tuple(min(lap.mini_sectors_ms[index] for lap in mini_laps) for index in range(mini_count))
            theoretical_mini = sum(best_mini)
    theoretical = theoretical_mini if theoretical_mini is not None else theoretical_sector
    best_three = sorted(lap.lap_time_ms for lap in eligible)[:3]
    return TheoreticalLapResult(
        personal_best_ms=personal_best,
        best_clean_sectors_ms=best_sectors,
        best_clean_mini_sectors_ms=best_mini,
        theoretical_sector_lap_ms=theoretical_sector,
        theoretical_mini_sector_lap_ms=theoretical_mini,
        theoretical_lap_ms=theoretical,
        untapped_ms=max(0, personal_best - theoretical),
        best_three_average_ms=fmean(best_three),
        consistency_stddev_ms=pstdev(best_three) if len(best_three) >= 2 else 0.0,
        eligible_laps=len(eligible),
    )
