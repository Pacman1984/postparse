"""Transcription settings (``[transcription]`` config section).

All keys are optional; the defaults below apply when a key (or the whole
section) is missing::

    [transcription]
    backend = "local"                 # "local" (faster-whisper) or "api" (OpenAI-compatible)
    limit = 50                        # media per `postparse transcribe run`
    max_attempts = 5                  # failed media are retried this many times in total
    backoff_minutes = 10              # first retry delay; doubles per failure ...
    max_backoff_hours = 24            # ... up to this cap
    remote_url_max_age_hours = 6      # stored video URLs older than this are re-fetched
    refetch_min_delay = 20            # pause between Instagram post re-fetches (seconds) ...
    refetch_max_delay = 60            # ... uniformly jittered between min and max
    download_timeout = 60             # HTTP timeout per video download (seconds)
    max_download_mb = 200             # abort downloads larger than this
    max_duration_minutes = 30         # longer media are marked 'skipped'
    language = ""                     # force a language ("de", "en"); empty = auto-detect

    [transcription.local]             # faster-whisper (install the `asr` extra)
    model = "large-v3-turbo"
    device = "auto"                   # "auto" (CUDA if available), "cuda" or "cpu"
    compute_type = "auto"             # auto: int8_float16 on CUDA, int8 on CPU
    beam_size = 5
    vad_filter = true
    download_root = ""                # model cache dir (empty: Hugging Face cache)
    cpu_threads = 0                   # 0 = CTranslate2 default

    [transcription.api]               # any OpenAI-compatible /v1/audio/transcriptions
    base_url = ""                     # e.g. "http://speaches.lan:8000/v1"; empty = api.openai.com
    api_key_env = "OPENAI_API_KEY"    # name of the env var holding the key
    model = "whisper-1"               # e.g. "Systran/faster-whisper-large-v3" (speaches)
    timeout = 300
    upload_format = "m4a"             # "m4a" (small AAC) or "wav16k"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal

__all__ = ["ApiAsrOptions", "BackendKind", "LocalAsrOptions", "TranscriptionOptions"]

BackendKind = Literal["local", "api"]


def _get(section: Any, key: str, default: Any) -> Any:
    """Read ``key`` from a mapping (``None`` / empty string -> default)."""
    if not isinstance(section, dict):
        return default
    value = section.get(key)
    return default if value is None or value == "" else value


@dataclass(frozen=True, slots=True)
class LocalAsrOptions:
    """faster-whisper settings (``[transcription.local]``)."""

    model: str = "large-v3-turbo"
    device: str = "auto"
    compute_type: str = "auto"
    beam_size: int = 5
    vad_filter: bool = True
    download_root: str | None = None
    cpu_threads: int = 0


@dataclass(frozen=True, slots=True)
class ApiAsrOptions:
    """OpenAI-compatible transcription endpoint (``[transcription.api]``)."""

    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "whisper-1"
    timeout: float = 300.0
    upload_format: Literal["m4a", "wav16k"] = "m4a"


@dataclass(frozen=True, slots=True)
class TranscriptionOptions:
    """Tunables of the transcription pipeline (see the module docstring for keys)."""

    backend: BackendKind = "local"
    limit: int = 50
    max_attempts: int = 5
    backoff_minutes: float = 10.0
    max_backoff_hours: float = 24.0
    remote_url_max_age_hours: float = 6.0
    refetch_min_delay: float = 20.0
    refetch_max_delay: float = 60.0
    download_timeout: float = 60.0
    max_download_mb: float = 200.0
    max_duration_minutes: float = 30.0
    language: str | None = None
    local: LocalAsrOptions = field(default_factory=LocalAsrOptions)
    api: ApiAsrOptions = field(default_factory=ApiAsrOptions)

    @property
    def backoff(self) -> timedelta:
        """Delay after the first failure."""
        return timedelta(minutes=self.backoff_minutes)

    @property
    def max_backoff(self) -> timedelta:
        """Upper bound of the retry delay."""
        return timedelta(hours=self.max_backoff_hours)

    @property
    def remote_url_max_age(self) -> timedelta:
        """Maximum age of a stored video URL that is downloaded without re-fetch."""
        return timedelta(hours=self.remote_url_max_age_hours)

    @property
    def max_download_bytes(self) -> int:
        """Download size cap in bytes."""
        return int(self.max_download_mb * 1024 * 1024)

    @classmethod
    def from_config(cls, config: Any) -> TranscriptionOptions:
        """Build options from a ``ConfigManager`` (``None``: defaults).

        Raises:
            ValueError: For an unknown backend or upload format.
        """
        section: Any = config.get_section("transcription") if config is not None else {}
        section = section if isinstance(section, dict) else {}
        d = cls()
        local_raw = section.get("local") or {}
        api_raw = section.get("api") or {}
        dl, da = LocalAsrOptions(), ApiAsrOptions()
        backend = str(_get(section, "backend", d.backend)).lower()
        if backend not in ("local", "api"):
            raise ValueError(f"transcription.backend must be 'local' or 'api', not {backend!r}")
        upload_format = str(_get(api_raw, "upload_format", da.upload_format))
        if upload_format not in ("m4a", "wav16k"):
            raise ValueError(
                f"transcription.api.upload_format must be 'm4a' or 'wav16k', not {upload_format!r}"
            )
        return cls(
            backend=backend,  # type: ignore[arg-type]
            limit=int(_get(section, "limit", d.limit)),
            max_attempts=int(_get(section, "max_attempts", d.max_attempts)),
            backoff_minutes=float(_get(section, "backoff_minutes", d.backoff_minutes)),
            max_backoff_hours=float(_get(section, "max_backoff_hours", d.max_backoff_hours)),
            remote_url_max_age_hours=float(
                _get(section, "remote_url_max_age_hours", d.remote_url_max_age_hours)
            ),
            refetch_min_delay=float(_get(section, "refetch_min_delay", d.refetch_min_delay)),
            refetch_max_delay=float(_get(section, "refetch_max_delay", d.refetch_max_delay)),
            download_timeout=float(_get(section, "download_timeout", d.download_timeout)),
            max_download_mb=float(_get(section, "max_download_mb", d.max_download_mb)),
            max_duration_minutes=float(
                _get(section, "max_duration_minutes", d.max_duration_minutes)
            ),
            language=_get(section, "language", None),
            local=LocalAsrOptions(
                model=str(_get(local_raw, "model", dl.model)),
                device=str(_get(local_raw, "device", dl.device)).lower(),
                compute_type=str(_get(local_raw, "compute_type", dl.compute_type)),
                beam_size=int(_get(local_raw, "beam_size", dl.beam_size)),
                vad_filter=bool(_get(local_raw, "vad_filter", dl.vad_filter)),
                download_root=_get(local_raw, "download_root", None),
                cpu_threads=int(_get(local_raw, "cpu_threads", dl.cpu_threads)),
            ),
            api=ApiAsrOptions(
                base_url=_get(api_raw, "base_url", None),
                api_key_env=str(_get(api_raw, "api_key_env", da.api_key_env)),
                model=str(_get(api_raw, "model", da.model)),
                timeout=float(_get(api_raw, "timeout", da.timeout)),
                upload_format=upload_format,  # type: ignore[arg-type]
            ),
        )
