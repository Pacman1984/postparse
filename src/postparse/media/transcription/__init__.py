"""Speech recognition backends.

* ``local`` -- :class:`~.local_faster_whisper.FasterWhisperBackend` (needs the
  ``asr`` extra: ``uv sync --extra asr``).
* ``api`` -- :class:`~.openai_compatible.OpenAICompatibleBackend` for any
  OpenAI-compatible ``/v1/audio/transcriptions`` endpoint (OpenAI, Groq,
  speaches, ...).

:func:`build_backend` creates one from :class:`~postparse.media.options.TranscriptionOptions`.
Importing this package never imports faster-whisper.
"""

from __future__ import annotations

from collections.abc import Mapping

from postparse.media.options import BackendKind, TranscriptionOptions
from postparse.media.transcription.base import (
    BackendUnavailable,
    Segment,
    Transcript,
    TranscriptionBackend,
    TranscriptionError,
)

__all__ = [
    "BackendUnavailable",
    "Segment",
    "Transcript",
    "TranscriptionBackend",
    "TranscriptionError",
    "build_backend",
]


def build_backend(
    options: TranscriptionOptions,
    kind: BackendKind | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> TranscriptionBackend:
    """Create the configured (or requested) backend.

    Args:
        options: Transcription options.
        kind: ``local`` or ``api``; ``None`` uses ``options.backend``.
        env: Environment for the API key lookup (default ``os.environ``).

    Returns:
        Backend instance (models / clients are created lazily).

    Raises:
        ValueError: For an unknown backend kind.
    """
    kind = kind or options.backend
    if kind == "local":
        from postparse.media.transcription.local_faster_whisper import FasterWhisperBackend

        o = options.local
        return FasterWhisperBackend(
            model=o.model,
            device=o.device,
            compute_type=o.compute_type,
            beam_size=o.beam_size,
            vad_filter=o.vad_filter,
            language=options.language,
            download_root=o.download_root,
            cpu_threads=o.cpu_threads,
        )
    if kind == "api":
        from postparse.media.transcription.openai_compatible import OpenAICompatibleBackend

        a = options.api
        return OpenAICompatibleBackend(
            base_url=a.base_url,
            api_key_env=a.api_key_env,
            model=a.model,
            timeout=a.timeout,
            upload_format=a.upload_format,
            language=options.language,
            env=env,
        )
    raise ValueError(f"Unknown transcription backend: {kind!r} (use 'local' or 'api')")
