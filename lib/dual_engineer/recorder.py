# MIT License
# Copyright (c) 2026 F1 Dual Engineer contributors

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, TextIO, Tuple

from lib.config.schema.engineer import EngineerSettings
from lib.packet_cap import F1PktCapFileHeader, F1PktCapMessage, ZlibCompressionHelper

from .analysis import analyze_laps
from .career import CareerDatabase
from .models import LapTrace, TelemetrySample


_INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def safe_path_component(value: Any, fallback: str = "Session") -> str:
    component = _INVALID_PATH_CHARS.sub("_", str(value or "")).strip(" ._")
    component = re.sub(r"\s+", "_", component)[:80]
    component = re.sub(r"_+", "_", component)
    if not component or component.upper() in _WINDOWS_RESERVED:
        return fallback
    return component


class StreamingPacketCaptureWriter:
    """Incremental writer for the upstream replay-compatible ``.f1pcap`` format."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("xb")
        self._compression = ZlibCompressionHelper()
        self._count = 0
        self._closed = False
        self._file.write(self._header().to_bytes())

    def _header(self) -> F1PktCapFileHeader:
        return F1PktCapFileHeader(
            major_version=1,
            minor_version=1,
            num_packets=self._count,
            is_little_endian=True,
            is_compressed=True,
        )

    @property
    def packet_count(self) -> int:
        return self._count

    def write(self, raw_packet: bytes, timestamp: Optional[float] = None) -> None:
        if self._closed:
            raise RuntimeError("Cannot write to a closed packet capture")
        message = F1PktCapMessage(raw_packet, timestamp=timestamp, is_little_endian=True)
        self._file.write(message.to_bytes(self._compression))
        self._count += 1
        if self._count % 256 == 0:
            self._file.flush()

    def close(self) -> None:
        if self._closed:
            return
        self._file.seek(0)
        self._file.write(self._header().to_bytes())
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        self._closed = True

    def __enter__(self) -> "StreamingPacketCaptureWriter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass(slots=True)
class _OpenSession:
    uid: int
    folder: Path
    started_at: str
    packet_writer: StreamingPacketCaptureWriter
    samples_file: TextIO
    samples_writer: csv.DictWriter
    metadata: Dict[str, Any]
    samples_written: int = 0


class SessionRecorder:
    """Bounded asynchronous raw and structured session recorder."""

    def __init__(
        self,
        settings: EngineerSettings,
        *,
        logger: Optional[logging.Logger] = None,
        database: Optional[CareerDatabase] = None,
    ):
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self.root = settings.export_directory_path
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = database or CareerDatabase(self.root / "f1_dual_engineer.sqlite")
        self.queue: asyncio.Queue[Tuple[Any, ...]] = asyncio.Queue(maxsize=settings.raw_packet_queue_size)
        self._worker_task: Optional[asyncio.Task] = None
        self._current: Optional[_OpenSession] = None
        self.dropped_raw_packets = 0
        self.dropped_samples = 0

    def start(self) -> asyncio.Task:
        if self._worker_task and not self._worker_task.done():
            return self._worker_task
        self._worker_task = asyncio.create_task(self._worker(), name="Dual Engineer Session Recorder")
        return self._worker_task

    def enqueue_raw(self, session_uid: int, raw_packet: bytes, timestamp: Optional[float] = None) -> bool:
        if not self.settings.enabled or not self.settings.auto_record or session_uid <= 0:
            return False
        try:
            self.queue.put_nowait(("raw", session_uid, bytes(raw_packet), timestamp or time.time()))
            return True
        except asyncio.QueueFull:
            self.dropped_raw_packets += 1
            return False

    def enqueue_sample(self, sample: TelemetrySample) -> bool:
        if not self.settings.enabled or not self.settings.auto_record:
            return False
        try:
            self.queue.put_nowait(("sample", sample))
            return True
        except asyncio.QueueFull:
            self.dropped_samples += 1
            return False

    def update_metadata(self, session_uid: int, metadata: Mapping[str, Any]) -> bool:
        if not self.settings.enabled or not self.settings.auto_record:
            return False
        try:
            self.queue.put_nowait(("metadata", session_uid, dict(metadata)))
            return True
        except asyncio.QueueFull:
            return False

    async def finalize(
        self,
        session_uid: int,
        final_json: Optional[Mapping[str, Any]],
        *,
        reason: str = "final-classification",
    ) -> Optional[Path]:
        if not self._worker_task:
            return None
        future = asyncio.get_running_loop().create_future()
        await self.queue.put(("finalize", session_uid, dict(final_json or {}), reason, future))
        return await future

    async def stop(self) -> None:
        if not self._worker_task:
            return
        future = asyncio.get_running_loop().create_future()
        await self.queue.put(("stop", future))
        await future
        await self._worker_task
        self._worker_task = None

    async def _worker(self) -> None:
        while True:
            item = await self.queue.get()
            try:
                kind = item[0]
                if kind == "raw":
                    _, uid, raw, timestamp = item
                    current = self._ensure_session(uid)
                    current.packet_writer.write(raw, timestamp)
                elif kind == "sample":
                    sample: TelemetrySample = item[1]
                    current = self._ensure_session(sample.session_uid)
                    current.samples_writer.writerow(sample.to_row())
                    current.samples_written += 1
                    if current.samples_written % 100 == 0:
                        current.samples_file.flush()
                elif kind == "metadata":
                    _, uid, metadata = item
                    current = self._ensure_session(uid)
                    current.metadata.update(metadata)
                    self.database.register_session(uid, current.folder, current.metadata)
                elif kind == "finalize":
                    _, uid, final_json, reason, future = item
                    try:
                        path = self._finalize_if_current(uid, final_json, reason)
                        future.set_result(path)
                    except Exception as error:  # pylint: disable=broad-exception-caught
                        self.logger.exception("Failed to finalize recorded session %s", uid)
                        future.set_exception(error)
                elif kind == "stop":
                    future = item[1]
                    try:
                        if self._current:
                            self._finalize_current({}, "application-shutdown")
                        future.set_result(None)
                    except Exception as error:  # pylint: disable=broad-exception-caught
                        future.set_exception(error)
                    return
            finally:
                self.queue.task_done()

    def _ensure_session(self, session_uid: int) -> _OpenSession:
        if self._current and self._current.uid == session_uid:
            return self._current
        if self._current:
            self._finalize_current({}, "session-uid-changed")
        now = datetime.now(timezone.utc)
        folder = self._unique_path(self.root / f".recording_{session_uid}_{now.strftime('%Y%m%dT%H%M%SZ')}")
        folder.mkdir(parents=True, exist_ok=False)
        packet_writer = StreamingPacketCaptureWriter(folder / "raw_telemetry.f1pcap.part")
        samples_file = (folder / "telemetry_samples.csv.part").open("x", newline="", encoding="utf-8")
        samples_writer = csv.DictWriter(samples_file, fieldnames=TelemetrySample.csv_columns(), extrasaction="raise")
        samples_writer.writeheader()
        started_at = now.isoformat()
        metadata = {"session_uid": session_uid, "started_at": started_at}
        self._current = _OpenSession(
            uid=session_uid,
            folder=folder,
            started_at=started_at,
            packet_writer=packet_writer,
            samples_file=samples_file,
            samples_writer=samples_writer,
            metadata=metadata,
        )
        self.database.register_session(session_uid, folder, metadata)
        return self._current

    def _finalize_if_current(
        self,
        session_uid: int,
        final_json: Mapping[str, Any],
        reason: str,
    ) -> Optional[Path]:
        if not self._current or self._current.uid != session_uid:
            return None
        return self._finalize_current(final_json, reason)

    def _finalize_current(self, final_json: Mapping[str, Any], reason: str) -> Path:
        current = self._current
        if not current:
            raise RuntimeError("No active session to finalize")
        current.packet_writer.close()
        current.samples_file.flush()
        os.fsync(current.samples_file.fileno())
        current.samples_file.close()
        raw_part = current.folder / "raw_telemetry.f1pcap.part"
        samples_part = current.folder / "telemetry_samples.csv.part"
        raw_part.rename(current.folder / "raw_telemetry.f1pcap")
        samples_part.rename(current.folder / "telemetry_samples.csv")

        ended_at = datetime.now(timezone.utc).isoformat()
        summary: Dict[str, Any] = {
            "schema_version": 1,
            "application": "F1 Dual Engineer",
            "recording": {
                **current.metadata,
                "ended_at": ended_at,
                "reason": reason,
                "raw_packet_count": current.packet_writer.packet_count,
                "structured_sample_count": current.samples_written,
                "dropped_raw_packets": self.dropped_raw_packets,
                "dropped_structured_samples": self.dropped_samples,
                "raw_format": "F1PktCap 1.1 zlib-per-packet",
            },
            "session": dict(final_json),
            "analysis": {"available": False, "reason": "No comparable selected-driver laps were recorded"},
        }
        self._write_classification(current.folder, final_json)
        self._write_laps(current.folder, final_json)
        self._write_analysis_exports(current.folder, current.metadata, summary)
        self._atomic_json(current.folder / "session_summary.json", summary)

        destination = self._final_folder(current)
        current.folder.rename(destination)
        metadata = {**current.metadata, "ended_at": ended_at, "reason": reason}
        self.database.finalize_session(current.uid, destination, metadata)
        self._current = None
        self._apply_retention()
        return destination

    def _final_folder(self, current: _OpenSession) -> Path:
        track = safe_path_component(current.metadata.get("track"), "Unknown_Track")
        session_type = safe_path_component(current.metadata.get("session_type"), "Session")
        date = current.started_at[:10]
        return self._unique_path(self.root / f"{track}_{date}_{session_type}", suffix=f"_{current.uid}")

    @staticmethod
    def _unique_path(path: Path, suffix: str = "_2") -> Path:
        if not path.exists():
            return path
        stem = path.name
        candidate = path.with_name(f"{stem}{suffix}")
        index = 3
        while candidate.exists():
            candidate = path.with_name(f"{stem}_{index}")
            index += 1
        return candidate

    @staticmethod
    def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
        temp = path.with_suffix(path.suffix + ".part")
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)

    @staticmethod
    def _write_classification(folder: Path, final_json: Mapping[str, Any]) -> None:
        entries = final_json.get("classification-data") or []
        columns = (
            "index", "driver-name", "team", "track-position", "grid-position",
            "points", "result-status", "result-reason", "num-laps", "best-lap-time-ms",
            "total-race-time", "penalties-time", "num-penalties", "num-pit-stops",
        )
        with (folder / "classification.csv").open("x", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for entry in entries:
                result = entry.get("final-classification") or {}
                writer.writerow({
                    "index": entry.get("index"),
                    "driver-name": entry.get("driver-name"),
                    "team": entry.get("team"),
                    "track-position": entry.get("track-position"),
                    "grid-position": result.get("grid-position"),
                    "points": result.get("points"),
                    "result-status": result.get("result-status"),
                    "result-reason": result.get("result-reason"),
                    "num-laps": result.get("num-laps"),
                    "best-lap-time-ms": result.get("best-lap-time-ms"),
                    "total-race-time": result.get("total-race-time"),
                    "penalties-time": result.get("penalties-time"),
                    "num-penalties": result.get("num-penalties"),
                    "num-pit-stops": result.get("num-pit-stops"),
                })

    @staticmethod
    def _write_laps(folder: Path, final_json: Mapping[str, Any]) -> None:
        columns = (
            "driver-index", "driver-name", "lap-number", "lap-time-ms", "sector-1-ms",
            "sector-2-ms", "sector-3-ms", "valid-flags", "tyre-compound", "tyre-age",
            "top-speed-kmph",
        )
        with (folder / "laps.csv").open("x", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for entry in final_json.get("classification-data") or []:
                history = (entry.get("lap-time-history") or {}).get("lap-history-data") or []
                for lap_number, lap in enumerate(history, start=1):
                    tyre = lap.get("tyre-set-info") or {}
                    writer.writerow({
                        "driver-index": entry.get("index"),
                        "driver-name": entry.get("driver-name"),
                        "lap-number": lap_number,
                        "lap-time-ms": lap.get("lap-time-in-ms"),
                        "sector-1-ms": lap.get("sector-1-time-in-ms"),
                        "sector-2-ms": lap.get("sector-2-time-in-ms"),
                        "sector-3-ms": lap.get("sector-3-time-in-ms"),
                        "valid-flags": lap.get("lap-valid-bit-flags"),
                        "tyre-compound": tyre.get("visual-tyre-compound"),
                        "tyre-age": tyre.get("tyre-age-laps"),
                        "top-speed-kmph": lap.get("top-speed-kmph"),
                    })

    def _write_analysis_exports(
        self,
        folder: Path,
        metadata: Mapping[str, Any],
        summary: Dict[str, Any],
    ) -> None:
        selected = [metadata.get("driver_a_index"), metadata.get("driver_b_index")]
        if any(index is None for index in selected):
            return
        best_laps = self._best_recorded_laps(
            folder / "telemetry_samples.csv",
            {int(selected[0]), int(selected[1])},
            metadata.get("track_length_m"),
        )
        if any(int(index) not in best_laps for index in selected):
            return
        target, reference = best_laps[int(selected[0])], best_laps[int(selected[1])]
        try:
            comparison = analyze_laps(target, reference)
        except ValueError as error:
            summary["analysis"] = {"available": False, "reason": str(error)}
            return
        with (folder / "driver_a_vs_driver_b.csv").open("x", newline="", encoding="utf-8") as handle:
            columns = (
                "distance_m", "driver_a_time_ms", "driver_b_time_ms", "delta_ms",
                "driver_a_speed_kph", "driver_b_speed_kph", "driver_a_brake", "driver_b_brake",
                "driver_a_throttle", "driver_b_throttle", "driver_a_steering", "driver_b_steering",
            )
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for point in comparison.synced_points:
                writer.writerow({
                    "distance_m": point.distance_m,
                    "driver_a_time_ms": point.target_time_ms,
                    "driver_b_time_ms": point.reference_time_ms,
                    "delta_ms": point.delta_ms,
                    "driver_a_speed_kph": point.target.get("speed_kph"),
                    "driver_b_speed_kph": point.reference.get("speed_kph"),
                    "driver_a_brake": point.target.get("brake"),
                    "driver_b_brake": point.reference.get("brake"),
                    "driver_a_throttle": point.target.get("throttle"),
                    "driver_b_throttle": point.reference.get("throttle"),
                    "driver_a_steering": point.target.get("steering"),
                    "driver_b_steering": point.reference.get("steering"),
                })
        with (folder / "corner_analysis.csv").open("x", newline="", encoding="utf-8") as handle:
            columns = tuple(asdict(comparison.segments[0]).keys()) if comparison.segments else (
                "label", "start_m", "end_m", "time_loss_ms", "diagnosis", "confidence"
            )
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for segment in comparison.segments:
                row = asdict(segment)
                row["evidence"] = " | ".join(row["evidence"])
                writer.writerow(row)
        comparison_dict = asdict(comparison)
        comparison_dict.pop("synced_points", None)
        summary["analysis"] = {"available": True, "comparison": comparison_dict}

    def _best_recorded_laps(
        self,
        path: Path,
        selected: set[int],
        track_length: Optional[float],
    ) -> Dict[int, LapTrace]:
        current: Dict[int, Tuple[int, list[TelemetrySample]]] = {}
        best: Dict[int, LapTrace] = {}

        def finish(index: int) -> None:
            if index not in current:
                return
            _, samples = current[index]
            if len(samples) < 10:
                return
            coverage = samples[-1].lap_distance_m - samples[0].lap_distance_m
            if track_length and coverage < float(track_length) * 0.8:
                return
            gaps = [right.lap_distance_m - left.lap_distance_m for left, right in zip(samples, samples[1:])]
            trace = LapTrace.from_samples(
                samples,
                telemetry_discontinuity=bool(gaps and max(gaps) > 300),
            )
            if not trace.comparable:
                return
            if index not in best or (trace.total_time_ms or 10**9) < (best[index].total_time_ms or 10**9):
                best[index] = trace

        with path.open("r", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                index = int(row["driver_index"])
                if index not in selected:
                    continue
                sample = self._sample_from_row(row)
                active = current.get(index)
                if active and active[0] != sample.lap_number:
                    finish(index)
                    current[index] = (sample.lap_number, [])
                elif not active:
                    current[index] = (sample.lap_number, [])
                current[index][1].append(sample)
        for index in selected:
            finish(index)
        return best

    @staticmethod
    def _sample_from_row(row: Mapping[str, str]) -> TelemetrySample:
        def optional_float(name: str) -> Optional[float]:
            return float(row[name]) if row.get(name) not in {None, "", "None"} else None

        def optional_int(name: str) -> Optional[int]:
            return int(float(row[name])) if row.get(name) not in {None, "", "None"} else None

        def boolean(name: str, default: bool = False) -> bool:
            value = row.get(name)
            return default if value in {None, ""} else value.casefold() in {"1", "true", "yes"}

        def float4(name: str) -> Optional[Tuple[float, float, float, float]]:
            value = row.get(name)
            if not value:
                return None
            parts = tuple(float(item) for item in value.split("|"))
            return parts if len(parts) == 4 else None

        return TelemetrySample(
            timestamp=float(row["timestamp"]),
            session_uid=int(row["session_uid"]),
            driver_index=int(row["driver_index"]),
            driver_name=row["driver_name"],
            lap_number=int(row["lap_number"]),
            lap_distance_m=float(row["lap_distance_m"]),
            lap_time_ms=float(row["lap_time_ms"]),
            telemetry_public=boolean("telemetry_public", True),
            lap_valid=boolean("lap_valid", True),
            pit=boolean("pit"),
            speed_kph=optional_float("speed_kph"),
            throttle=optional_float("throttle"),
            brake=optional_float("brake"),
            steering=optional_float("steering"),
            gear=optional_int("gear"),
            rpm=optional_int("rpm"),
            g_lateral=optional_float("g_lateral"),
            g_longitudinal=optional_float("g_longitudinal"),
            world_x=optional_float("world_x"),
            world_z=optional_float("world_z"),
            wheel_speeds=float4("wheel_speeds"),
            wheel_slip_ratios=float4("wheel_slip_ratios"),
            wheel_slip_angles=float4("wheel_slip_angles"),
            tyre_surface_temps=float4("tyre_surface_temps"),
            tyre_inner_temps=float4("tyre_inner_temps"),
            tyre_wear=float4("tyre_wear"),
            tyre_compound=row.get("tyre_compound") or None,
            tyre_age_laps=optional_int("tyre_age_laps"),
            fuel_kg=optional_float("fuel_kg"),
            fuel_delta_laps=optional_float("fuel_delta_laps"),
            ers_store_pct=optional_float("ers_store_pct"),
            ers_deployed_pct=optional_float("ers_deployed_pct"),
            ers_harvested_pct=optional_float("ers_harvested_pct"),
            ers_mode=row.get("ers_mode") or None,
            drs=None if row.get("drs") in {None, "", "None"} else boolean("drs"),
            damage_pct=optional_float("damage_pct"),
            traffic=boolean("traffic"),
            safety_car=boolean("safety_car"),
            weather=row.get("weather") or None,
        )

    def _apply_retention(self) -> None:
        if self.settings.retention_days <= 0:
            return
        cutoff = time.time() - (self.settings.retention_days * 86400)
        for child in self.root.iterdir():
            if child.is_dir() and not child.name.startswith(".recording_") and child.stat().st_mtime < cutoff:
                # Retention is opt-in and restricted to finalized children of the configured export root.
                for item in sorted(child.rglob("*"), reverse=True):
                    if item.is_file() or item.is_symlink():
                        item.unlink()
                    elif item.is_dir():
                        item.rmdir()
                child.rmdir()
