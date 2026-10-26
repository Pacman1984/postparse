"""Speech recognition through an OpenAI-compatible ``/v1/audio/transcriptions`` API.

Works with OpenAI (``whisper-1``), Groq (``whisper-large-v3-turbo``), and
self-hosted servers such as speaches (``Systran/faster-whisper-large-v3``).
The audio track is extracted with PyAV into the caller's scratch directory
(``m4a`` by default, ~0.4 MB per minute) and uploaded with
``response_format="verbose_json"`` and segment timestamps.

The API key is read from the environment variable named by ``api_key_env``
(never from the config file). Servers that do not check keys work without one
when ``base_url`` is set.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from postparse.media.audio import NoAudioStream, extract_audio
from postparse.media.transcription.base import (
    BackendUnavailable,
    Segment,
    Transcript,
    TranscriptionError,
)

__all__ = ["OpenAICompatibleBackend"]

logger = logging.getLogger(__name__)

_NO_KEY = "not-needed"
#: verbose_json reports full language names; map the common ones to ISO codes.
_LANGUAGE_CODES = {
    "german": "de", "english": "en", "french": "fr", "spanish": "es", "italian": "it",
    "portuguese": "pt", "dutch": "nl", "polish": "pl", "turkish": "tr", "russian": "ru",
    "ukrainian": "uk", "arabic": "ar", "japanese": "ja", "korean": "ko", "chinese": "zh",
    "hindi": "hi", "swedish": "sv", "danish": "da", "norwegian": "no", "finnish": "fi",
    "czech": "cs", "greek": "el", "hungarian": "hu", "romanian": "ro", "croatian": "hr",
}


def _field(obj: Any, name: str) -> Any:
    """Read ``name`` from an SDK object or a dict."""
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _language_code(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    return _LANGUAGE_CODES.get(text, text)


class OpenAICompatibleBackend:
    """Transcribe by uploading the audio track to an OpenAI-compatible endpoint.

    Args:
        base_url: API base (``.../v1``); ``None`` uses api.openai.com.
        api_key_env: Name of the environment variable with the API key.
        model: Model name sent to the endpoint.
        timeout: Request timeout in seconds.
        upload_format: ``m4a`` or ``wav16k``.
        language: Force a language (``None``: detect).
        env: Environment for the key lookup (default ``os.environ``).
        client: Prebuilt ``openai.OpenAI`` client (tests).
    """

    name = "openai-compatible"

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key_env: str = "OPENAI_API_KEY",
        model: str = "whisper-1",
        timeout: float = 300.0,
        upload_format: Literal["m4a", "wav16k"] = "m4a",
        language: str | None = None,
        env: Mapping[str, str] | None = None,
        client: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.api_key_env = api_key_env
        self.model = model
        self.timeout = timeout
        self.upload_format = upload_format
        self.language = language or None
        self._env = env
        self._client = client
        host = urlparse(self.base_url).hostname if self.base_url else "api.openai.com"
        #: Endpoint host (informational, never contains credentials).
        self.host = host or "?"

    def _api_key(self) -> str | None:
        env = self._env if self._env is not None else os.environ
        key = env.get(self.api_key_env) if self.api_key_env else None
        if key:
            return key
        return _NO_KEY if self.base_url else None

    def check(self) -> None:
        """Raise :class:`BackendUnavailable` if no API key is available for api.openai.com."""
        if self._client is None and self._api_key() is None:
            raise BackendUnavailable(
                f"No API key for the transcription API: set {self.api_key_env} "
                "or configure transcription.api.base_url for a self-hosted server."
            )

    def _get_client(self) -> Any:
        if self._client is None:
            self.check()
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self._api_key(), base_url=self.base_url, timeout=self.timeout,
                max_retries=1,
            )
        return self._client

    def transcribe(self, path: Path, *, work_dir: Path | None = None) -> Transcript:
        """Extract the audio, upload it and parse the verbose JSON response.

        Raises:
            BackendUnavailable: No API key.
            TranscriptionError: Extraction or the request failed.
        """
        client = self._get_client()
        suffix = ".m4a" if self.upload_format == "m4a" else ".wav"
        own_dir = None
        if work_dir is None:
            own_dir = tempfile.TemporaryDirectory(prefix="postparse-asr-")
            work_dir = Path(own_dir.name)
        audio_path = Path(work_dir) / f"{Path(path).stem}.upload{suffix}"
        try:
            try:
                extract_audio(path, audio_path, self.upload_format)
            except NoAudioStream:
                return Transcript(text="", language=None, backend=self.name, model=self.model)
            except Exception as exc:
                raise TranscriptionError(f"Audio extraction failed: {exc}") from exc
            kwargs: dict[str, Any] = {
                "model": self.model,
                "response_format": "verbose_json",
                "timestamp_granularities": ["segment"],
            }
            if self.language:
                kwargs["language"] = self.language
            try:
                with audio_path.open("rb") as handle:
                    response = client.audio.transcriptions.create(
                        file=(audio_path.name, handle), **kwargs
                    )
            except Exception as exc:
                name = type(exc).__name__
                if name in ("AuthenticationError", "PermissionDeniedError"):
                    raise BackendUnavailable(
                        f"Transcription API rejected the credentials ({self.host}): {name}"
                    ) from exc
                raise TranscriptionError(f"Transcription request failed: {name}: {exc}") from exc
            return self._parse(response)
        finally:
            audio_path.unlink(missing_ok=True)
            if own_dir is not None:
                own_dir.cleanup()

    def _parse(self, response: Any) -> Transcript:
        segments: list[Segment] = []
        for raw in _field(response, "segments") or []:
            text = str(_field(raw, "text") or "").strip()
            if not text:
                continue
            segments.append(
                Segment(float(_field(raw, "start") or 0.0), float(_field(raw, "end") or 0.0), text)
            )
        text = str(_field(response, "text") or "").strip()
        if not text and segments:
            text = " ".join(s.text for s in segments)
        duration = _field(response, "duration")
        return Transcript(
            text=text,
            language=_language_code(_field(response, "language")) or self.language,
            segments=segments,
            duration=float(duration) if duration is not None else None,
            backend=self.name,
            model=self.model,
        )

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and hasattr(self._client, "close"):
            try:
                self._client.close()
            except Exception:  # pragma: no cover - best effort
                logger.debug("Could not close the transcription client", exc_info=True)
        self._client = None
