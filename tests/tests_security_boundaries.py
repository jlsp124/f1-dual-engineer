import struct
import zlib
from pathlib import Path

import pytest

from lib.dual_engineer.models import TelemetrySample, csv_safe_value
from lib.dual_engineer.recorder import StreamingPacketCaptureWriter
from lib.packet_cap import F1PktCapFileHeader, F1PktCapMessage, ZlibCompressionHelper


def test_capture_header_rejects_wrong_magic_and_truncation():
    valid = F1PktCapFileHeader().to_bytes()
    with pytest.raises(ValueError, match="exactly"):
        F1PktCapFileHeader.from_bytes(valid[:-1])
    with pytest.raises(ValueError, match="Not an F1"):
        F1PktCapFileHeader.from_bytes(b"NOPE!!" + valid[6:])


def test_capture_entry_rejects_decompression_bomb():
    compressed = zlib.compress(b"A" * (ZlibCompressionHelper.MAX_DECOMPRESSED_PACKET_BYTES + 1))
    serialized = struct.pack("<fI", 1.0, len(compressed)) + compressed
    with pytest.raises(ValueError, match="output limit"):
        F1PktCapMessage.from_bytes(serialized, True, ZlibCompressionHelper())


def test_streaming_writer_enforces_byte_quota(tmp_path: Path):
    path = tmp_path / "bounded.f1pcap"
    with StreamingPacketCaptureWriter(path) as writer:
        initial = writer.bytes_written
        assert writer.write(b"first", max_bytes=initial + 64)
        assert not writer.write(b"second", max_bytes=writer.bytes_written)
        assert writer.packet_count == 1


@pytest.mark.parametrize("value", ["=1+1", " +SUM(A1:A2)", "\t@cmd", "-2+3"])
def test_csv_safe_value_neutralizes_formula_prefixes(value: str):
    assert csv_safe_value(value).startswith("'")


def test_telemetry_sample_csv_row_neutralizes_driver_name():
    sample = TelemetrySample(
        timestamp=1.0,
        session_uid=1,
        driver_index=0,
        driver_name="=WEBSERVICE(\"https://example.invalid\")",
        lap_number=1,
        lap_distance_m=1.0,
        lap_time_ms=1.0,
    )
    assert sample.to_row()["driver_name"].startswith("'")
