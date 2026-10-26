"""``[transcription]`` options parsing."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from postparse.media.options import TranscriptionOptions


class Cfg:
    def __init__(self, sections: dict[str, Any]) -> None:
        self.sections = sections

    def get_section(self, name: str) -> dict[str, Any]:
        return self.sections.get(name, {})


def test_defaults() -> None:
    o = TranscriptionOptions.from_config(None)
    assert o.backend == "local" and o.limit == 50 and o.max_attempts == 5
    assert o.local.model == "large-v3-turbo" and o.local.device == "auto"
    assert o.local.compute_type == "auto" and o.local.vad_filter is True
    assert o.refetch_min_delay == 20 and o.refetch_max_delay == 60
    assert o.remote_url_max_age == timedelta(hours=6)
    assert o.api.api_key_env == "OPENAI_API_KEY" and o.api.upload_format == "m4a"
    assert o.language is None


def test_config_values() -> None:
    o = TranscriptionOptions.from_config(Cfg({"transcription": {
        "backend": "API", "limit": 7, "refetch_min_delay": 1, "refetch_max_delay": 2,
        "remote_url_max_age_hours": 1.5, "max_download_mb": 1, "language": "de",
        "backoff_minutes": 5, "max_backoff_hours": 2,
        "local": {"model": "small", "device": "CPU", "download_root": ""},
        "api": {"base_url": "http://asr.test/v1", "model": "m", "api_key_env": "ASR_KEY",
                "upload_format": "wav16k"},
    }}))
    assert o.backend == "api" and o.limit == 7 and o.language == "de"
    assert o.remote_url_max_age == timedelta(minutes=90)
    assert o.max_download_bytes == 1024 * 1024
    assert o.backoff == timedelta(minutes=5) and o.max_backoff == timedelta(hours=2)
    assert o.local.model == "small" and o.local.device == "cpu" and o.local.download_root is None
    assert o.api.base_url == "http://asr.test/v1" and o.api.upload_format == "wav16k"
    assert o.api.api_key_env == "ASR_KEY"


@pytest.mark.parametrize("section", [{"backend": "cloud"}, {"api": {"upload_format": "mp3"}}])
def test_invalid_values(section: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        TranscriptionOptions.from_config(Cfg({"transcription": section}))
