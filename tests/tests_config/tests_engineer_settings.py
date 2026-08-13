import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from lib.config.schema.engineer import EngineerSettings
from lib.config.schema.png import PngSettings


def test_engineer_defaults_are_release_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    local_app_data = tmp_path / "local-app-data"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.chdir(tmp_path)
    settings = EngineerSettings()

    assert settings.enabled is True
    assert settings.auto_record is True
    assert settings.sample_rate_hz == 20
    assert settings.retention_days == 0
    assert settings.max_session_size_mb == 2048
    assert settings.max_export_storage_gb == 20
    assert settings.minimum_free_space_mb == 2048
    expected_root = local_app_data / "f1_dual_engineer" if sys.platform == "win32" else tmp_path
    assert settings.export_directory_path == expected_root / "exports"


def test_engineer_preserves_user_selected_absolute_export_directory(tmp_path: Path):
    selected_directory = tmp_path / "selected-exports"

    assert EngineerSettings(export_directory=str(selected_directory)).export_directory_path == selected_directory


@pytest.mark.parametrize("sample_rate", [0, 31])
def test_engineer_rejects_unsafe_sample_rates(sample_rate: int):
    with pytest.raises(ValidationError):
        EngineerSettings(sample_rate_hz=sample_rate)


def test_engineer_rejects_duplicate_driver_preferences():
    with pytest.raises(ValidationError, match="must be different"):
        EngineerSettings(driver_a_preference="JOV", driver_b_preference=" jov ")


def test_engineer_normalizes_driver_preferences():
    settings = EngineerSettings(
        driver_a_preference="  Driver   A ",
        driver_b_preference="Driver B",
    )
    assert settings.driver_a_preference == "Driver A"
    assert settings.driver_b_preference == "Driver B"


def test_png_settings_includes_engineer_section():
    assert PngSettings().Engineer == EngineerSettings()
