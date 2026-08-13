# MIT License
# Copyright (c) 2026 F1 Dual Engineer contributors

import logging
import sys
from pathlib import Path

import pytest

from apps.launcher.logger import get_rotating_logger
from apps.launcher.perf_db import save_session_stats
from lib.config import load_config_from_json
from lib.config.schema.engineer import EngineerSettings
from lib.dual_engineer.recorder import SessionRecorder
from lib.file_path import get_app_base_dir, resolve_fixed_file, resolve_user_file
from lib.save_to_disk import save_json_to_file
from lib.telemetry_manager.manager import AsyncF1TelemetryManager


class _PacketProbe:
    @staticmethod
    def toJSON() -> dict:
        return {"ok": True}


@pytest.mark.parametrize("cwd_parts", [("arbitrary", "launch-dir"), ("Windows", "System32")])
@pytest.mark.asyncio
async def test_windows_runtime_writes_ignore_current_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cwd_parts: tuple[str, ...],
):
    launch_directory = tmp_path.joinpath(*cwd_parts)
    launch_directory.mkdir(parents=True)
    local_app_data = tmp_path / "local-app-data"
    expected_root = local_app_data / "f1_dual_engineer"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.chdir(launch_directory)

    assert get_app_base_dir() == expected_root
    assert Path(resolve_user_file("png_config.json")) == expected_root / "png_config.json"
    assert Path(resolve_fixed_file(".f1_dual_engineer.lock")) == expected_root / ".f1_dual_engineer.lock"

    logger, log_path = get_rotating_logger(name=f"runtime-path-{launch_directory.name}")
    try:
        logger.info("runtime path regression probe")
        for handler in logger.handlers:
            handler.flush()
        assert Path(log_path) == expected_root / "png.log"
        assert Path(log_path).is_file()
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)

    config_path = Path(resolve_user_file("png_config.json"))
    load_config_from_json(str(config_path))
    saved_json = await save_json_to_file({"ok": True}, "runtime-probe.json")
    save_session_stats(get_app_base_dir(), {"ok": True})
    recorder = SessionRecorder(EngineerSettings())
    crash_dump = AsyncF1TelemetryManager._dumpPacketToFile(object(), _PacketProbe())

    assert saved_json.is_relative_to(expected_root / "data")
    assert (expected_root / "png_perf.db").is_file()
    assert recorder.root == expected_root / "exports"
    assert (recorder.root / "f1_dual_engineer.sqlite").is_file()
    assert Path(crash_dump).parent == expected_root / "crash_packet_dumps"
    assert list(launch_directory.iterdir()) == []


def test_linux_runtime_base_directory_behavior_is_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.chdir(tmp_path)

    assert get_app_base_dir() == Path(".")
    assert resolve_user_file("png.log") == "png.log"
