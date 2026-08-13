# MIT License
#
# Copyright (c) 2026 F1 Dual Engineer contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import sys
from pathlib import Path
from typing import Any, ClassVar, Dict

from pydantic import BaseModel, Field, field_validator, model_validator

from lib.file_path import get_app_base_dir

from .diff import ConfigDiffMixin


class EngineerSettings(ConfigDiffMixin, BaseModel):
    """Dual-driver pit wall, recording and alert settings."""

    ui_meta: ClassVar[Dict[str, Any]] = {"visible": True}

    enabled: bool = Field(
        default=True,
        description="Enable Dual Driver Engineer mode",
        json_schema_extra={"ui": {"type": "check_box", "visible": True}},
    )
    auto_record: bool = Field(
        default=True,
        description="Automatically record supported F1 sessions",
        json_schema_extra={"ui": {"type": "check_box", "visible": True}},
    )
    export_directory: str = Field(
        default="exports",
        description="Dual Driver session export directory",
        json_schema_extra={"ui": {"type": "text_box", "visible": True}},
    )
    sample_rate_hz: int = Field(
        default=20,
        ge=1,
        le=30,
        description="Structured telemetry recording rate (Hz)",
        json_schema_extra={
            "ui": {
                "type": "text_box",
                "visible": True,
                "ext_info": [
                    "Raw UDP packets are always retained when automatic recording is enabled.",
                    "This controls the analysis-friendly structured sample rate.",
                ],
            }
        },
    )
    retention_days: int = Field(
        default=0,
        ge=0,
        le=3650,
        description="Delete generated session exports after this many days (0 keeps them)",
        json_schema_extra={"ui": {"type": "text_box", "visible": True}},
    )
    driver_a_preference: str = Field(
        default="",
        max_length=64,
        description="Preferred Driver A name or abbreviation",
        json_schema_extra={"ui": {"type": "text_box", "visible": True}},
    )
    driver_b_preference: str = Field(
        default="",
        max_length=64,
        description="Preferred Driver B name or abbreviation",
        json_schema_extra={"ui": {"type": "text_box", "visible": True}},
    )
    pace_alerts: bool = Field(
        default=True,
        description="Engineer feed: pace and time-loss alerts",
        json_schema_extra={"ui": {"type": "check_box", "visible": True}},
    )
    tyre_alerts: bool = Field(
        default=True,
        description="Engineer feed: tyre and degradation alerts",
        json_schema_extra={"ui": {"type": "check_box", "visible": True}},
    )
    energy_alerts: bool = Field(
        default=True,
        description="Engineer feed: ERS and fuel alerts",
        json_schema_extra={"ui": {"type": "check_box", "visible": True}},
    )
    championship_alerts: bool = Field(
        default=True,
        description="Engineer feed: championship projection alerts",
        json_schema_extra={"ui": {"type": "check_box", "visible": True}},
    )
    pit_alerts: bool = Field(
        default=True,
        description="Engineer feed: pit window and stop alerts",
        json_schema_extra={"ui": {"type": "check_box", "visible": True}},
    )
    raw_packet_queue_size: int = Field(
        default=8192,
        ge=1024,
        le=65536,
        description="Maximum queued raw telemetry packets",
        json_schema_extra={"ui": {"type": "text_box", "visible": False}},
    )
    max_session_size_mb: int = Field(
        default=2048,
        ge=128,
        le=8192,
        description="Maximum raw packet capture size per session in MiB",
        json_schema_extra={"ui": {"type": "text_box", "visible": False}},
    )
    max_export_storage_gb: int = Field(
        default=20,
        ge=1,
        le=1024,
        description="Maximum application-owned session storage before new recordings are refused",
        json_schema_extra={"ui": {"type": "text_box", "visible": True}},
    )
    minimum_free_space_mb: int = Field(
        default=2048,
        ge=256,
        le=1024 * 1024,
        description="Minimum free disk space required to start or extend a recording",
        json_schema_extra={"ui": {"type": "text_box", "visible": True}},
    )

    @field_validator("export_directory")
    @classmethod
    def export_directory_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("export_directory must not be empty")
        if "\x00" in value:
            raise ValueError("export_directory cannot contain a null byte")
        return value

    @field_validator("driver_a_preference", "driver_b_preference")
    @classmethod
    def normalize_driver_preference(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def drivers_must_be_distinct(self) -> "EngineerSettings":
        if (
            self.driver_a_preference
            and self.driver_b_preference
            and self.driver_a_preference.casefold() == self.driver_b_preference.casefold()
        ):
            raise ValueError("Driver A and Driver B preferences must be different")
        return self

    @property
    def export_directory_path(self) -> Path:
        path = Path(self.export_directory).expanduser()
        if sys.platform == "win32" and not path.is_absolute():
            path = get_app_base_dir() / path
        return path.resolve(strict=False)

    @property
    def sample_interval_seconds(self) -> float:
        return 1.0 / self.sample_rate_hz
