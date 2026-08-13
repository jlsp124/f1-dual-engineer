import os
import time
from pathlib import Path

import pytest

from lib.config.schema.engineer import EngineerSettings
from lib.dual_engineer.models import TelemetrySample
from lib.dual_engineer.recorder import (
    SessionRecorder,
    StreamingPacketCaptureWriter,
    safe_path_component,
)
from lib.packet_cap import F1PacketCapture


def test_streaming_packet_writer_is_replay_compatible(tmp_path: Path):
    path = tmp_path / "raw.f1pcap"
    packets = [b"first packet", bytes(range(64)), b"last"]
    with StreamingPacketCaptureWriter(path) as writer:
        for index, packet in enumerate(packets):
            writer.write(packet, timestamp=100.0 + index)

    capture = F1PacketCapture(file_name=str(path))
    assert capture.getNumPackets() == len(packets)
    assert [data for _, data in capture.getPackets()] == packets


def _sample(index: int, name: str, distance: float, lap_time_ms: float) -> TelemetrySample:
    return TelemetrySample(
        timestamp=lap_time_ms / 1000,
        session_uid=123,
        driver_index=index,
        driver_name=name,
        lap_number=2,
        lap_distance_m=distance,
        lap_time_ms=lap_time_ms,
        speed_kph=280 - abs(150 - distance) / 2,
        throttle=1.0 if distance < 90 or distance > 220 else 0.1,
        brake=0.7 if 90 <= distance <= 170 else 0.0,
        steering=0.2 if 130 <= distance <= 210 else 0.0,
        tyre_compound="Medium",
        tyre_age_laps=2,
        fuel_kg=45,
        weather="Dry",
    )


@pytest.mark.asyncio
async def test_session_recorder_exports_raw_structured_classification_and_analysis(tmp_path: Path):
    settings = EngineerSettings(export_directory=str(tmp_path), raw_packet_queue_size=1024)
    recorder = SessionRecorder(settings)
    recorder.start()
    recorder.update_metadata(123, {
        "track": "Hungary",
        "session_type": "Race",
        "track_length_m": 300,
        "driver_a_index": 0,
        "driver_b_index": 1,
    })
    for raw in (b"one", b"two", b"three"):
        assert recorder.enqueue_raw(123, raw)
    for index, name, extra in ((0, "JOV", 0), (1, "JAX", -20)):
        for distance in range(0, 301, 10):
            recorder.enqueue_sample(_sample(index, name, distance, distance * 12 + extra))

    final_json = {
        "classification-data": [
            {
                "index": 0,
                "driver-name": "JOV",
                "team": "Apex",
                "track-position": 1,
                "final-classification": {"position": 1, "grid-position": 2, "points": 25, "result-status": "Finished"},
                "lap-time-history": {"lap-history-data": [{
                    "lap-time-in-ms": 90000,
                    "sector-1-time-in-ms": 30000,
                    "sector-2-time-in-ms": 31000,
                    "sector-3-time-in-ms": 29000,
                    "lap-valid-bit-flags": 15,
                    "top-speed-kmph": 320,
                }]},
            },
            {
                "index": 1,
                "driver-name": "JAX",
                "team": "Apex",
                "track-position": 2,
                "final-classification": {"position": 2, "grid-position": 1, "points": 18, "result-status": "Finished"},
                "lap-time-history": {"lap-history-data": []},
            },
        ]
    }
    folder = await recorder.finalize(123, final_json)
    await recorder.stop()

    assert folder is not None and folder.name.startswith("Hungary_")
    assert (folder / "raw_telemetry.f1pcap").is_file()
    assert (folder / "telemetry_samples.csv").is_file()
    assert (folder / "classification.csv").is_file()
    assert (folder / "laps.csv").is_file()
    assert (folder / "session_summary.json").is_file()
    assert (folder / "driver_a_vs_driver_b.csv").is_file()
    assert (folder / "corner_analysis.csv").is_file()
    assert F1PacketCapture(file_name=str(folder / "raw_telemetry.f1pcap")).getNumPackets() == 3


def test_safe_path_component_blocks_traversal_and_windows_names():
    assert safe_path_component("../Hungary: Race") == "Hungary_Race"
    assert safe_path_component("CON") == "Session"


@pytest.mark.asyncio
async def test_metadata_alone_does_not_create_persistent_session(tmp_path: Path):
    recorder = SessionRecorder(EngineerSettings(export_directory=str(tmp_path)))
    recorder.start()
    assert recorder.update_metadata(999, {"track": "Candidate"})
    await recorder.queue.join()
    assert recorder.database.list_sessions() == []
    assert not tuple(tmp_path.glob(".recording_*"))
    await recorder.stop()


def test_retention_deletes_only_cataloged_finalized_session(tmp_path: Path):
    settings = EngineerSettings(export_directory=str(tmp_path), retention_days=1)
    recorder = SessionRecorder(settings)
    cataloged = tmp_path / "Cataloged_Race"
    uncataloged = tmp_path / "Personal_Data"
    for folder in (cataloged, uncataloged):
        folder.mkdir()
        (folder / "data.txt").write_text("keep boundaries explicit", encoding="utf-8")
        old = time.time() - (3 * 86400)
        os.utime(folder, (old, old))
    recorder.database.finalize_session(123, cataloged, {"track": "Cataloged"})

    recorder._apply_retention()  # pylint: disable=protected-access

    assert not cataloged.exists()
    assert uncataloged.is_dir()


def test_global_storage_quota_refuses_additional_writes(tmp_path: Path):
    settings = EngineerSettings(export_directory=str(tmp_path), max_export_storage_gb=1)
    recorder = SessionRecorder(settings)
    recorder._owned_storage_bytes = 1024**3  # pylint: disable=protected-access
    assert not recorder._storage_budget_available(1)  # pylint: disable=protected-access
    assert recorder.storage_quota_rejections == 1
