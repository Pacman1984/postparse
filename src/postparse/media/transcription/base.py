"""Backend protocol and result types of speech recognition.

A backend turns a local media file into a :class:`Transcript` with segment
timestamps. Backends must not keep files: anything they create goes into the
``work_dir`` handed to :meth:`TranscriptionBackend.transcribe`, which the caller
deletes afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple, Protocol, runtime_checkable

__all__ = [
    "BackendUnavailable",
    "Segment",
    "Transcript",
    "TranscriptionBackend",
    "TranscriptionError",
]


class TranscriptionError(RuntimeError):
    """Transcribing one file failed (the media is retried later)."""


class BackendUnavailable(TranscriptionError):
    """The backend cannot run at all (missing extra, API key, ...); stops the run."""


class Segment(NamedTuple):
    """A timed piece of the transcript (seconds from the start)."""

    start: float
    end: float
    text: str


@dataclass(frozen=True, slots=True)
class Transcript:
    """Speech recognition result of one media file.

    Attributes:
        text: Full transcript (segments joined by spaces).
        language: Detected (or forced) ISO language code, if known.
        segments: Timed segments in order.
        duration: Audio duration in seconds, if known.
        backend: Backend identifier stored with the transcript.
        model: Model identifier stored with the transcript.
        language_probability: Confidence of the language detection, if known.
    """

    text: str
    language: str | None
    segments: list[Segment] = field(default_factory=list)
    duration: float | None = None
    backend: str = ""
    model: str = ""
    language_probability: float | None = None

    @property
    def is_empty(self) -> bool:
        """True when no speech was recognized."""
        return not self.text.strip()

    def segments_json(self) -> list[dict[str, Any]]:
        """Segments as JSON-friendly dicts (``start``/``end`` rounded to ms)."""
        return [
            {"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text}
            for s in self.segments
        ]


@runtime_checkable
class TranscriptionBackend(Protocol):
    """Speech recognition backend.

    Attributes:
        name: Backend identifier (stored as ``transcripts.backend``).
        model: Model identifier (stored as ``transcripts.model``).
    """

    name: str
    model: str

    def check(self) -> None:
        """Verify the backend can run (cheap; no model load / request).

        Raises:
            BackendUnavailable: If it cannot.
        """
        ...

    def transcribe(self, path: Path, *, work_dir: Path | None = None) -> Transcript:
        """Transcribe one media file.

        Args:
            path: Local video or audio file.
            work_dir: Scratch directory for intermediate files (deleted by the caller).

        Returns:
            Transcript (``is_empty`` when there is no speech).

        Raises:
            TranscriptionError: If transcription fails.
            BackendUnavailable: If the backend cannot run at all.
        """
        ...

    def close(self) -> None:
        """Release resources (connections; local models stay cached per process)."""
        ...
