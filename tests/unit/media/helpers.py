"""Shared helpers for the media / transcription tests: tiny media files, DB rows, fakes."""

from __future__ import annotations

import math
import struct
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import av

from postparse.core.db import Database
from postparse.core.db.models import ItemUpsert, Media, MediaInput
from postparse.core.db.repos import ItemsRepo, MediaRepo
from postparse.media.fetch import FetchedMedia
from postparse.media.transcription import Segment, Transcript

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def make_media_file(
    path: Path, *, audio: bool = True, video: bool = True, seconds: float = 1.0
) -> Path:
    """Write a tiny MP4 (32x32 black video and/or a 440 Hz tone) with PyAV."""
    with av.open(str(path), "w", format="mp4") as container:
        vstream = container.add_stream("mpeg4", rate=10) if video else None
        if vstream is not None:
            vstream.width = 32
            vstream.height = 32
            vstream.pix_fmt = "yuv420p"
        astream = container.add_stream("aac", rate=16000, layout="mono") if audio else None
        if vstream is not None:
            for index in range(max(1, int(10 * seconds))):
                frame = av.VideoFrame(32, 32, "yuv420p")
                for plane in frame.planes:
                    plane.update(bytes(plane.buffer_size))
                frame.pts = index
                for packet in vstream.encode(frame):
                    container.mux(packet)
            for packet in vstream.encode(None):
                container.mux(packet)
        if astream is not None:
            samples = int(16000 * seconds)
            frame = av.AudioFrame(format="flt", layout="mono", samples=samples)
            frame.sample_rate = 16000
            frame.pts = 0
            frame.planes[0].update(
                struct.pack(
                    f"<{samples}f",
                    *(0.3 * math.sin(2 * math.pi * 440 * i / 16000) for i in range(samples)),
                )
            )
            for packet in astream.encode(frame):
                container.mux(packet)
            for packet in astream.encode(None):
                container.mux(packet)
    return path


def add_video_item(
    db: Database,
    shortcode: str,
    *,
    remote_url: str | None = None,
    seen_at: datetime | None = None,
    caption: str | None = "Pasta mit Tomaten #rezept",
    kind: str = "video",
    positions: tuple[int, ...] = (0,),
    local_path: str | None = None,
    source: str = "instagram",
) -> tuple[int, list[int]]:
    """Insert an item with pending video media; return ``(item_id, media_ids)``."""
    with db.transaction() as conn:
        item_id, _ = ItemsRepo(conn).upsert(
            ItemUpsert(
                source=source,  # type: ignore[arg-type]
                external_id=shortcode,
                kind=kind,  # type: ignore[arg-type]
                text=caption,
                media=tuple(
                    MediaInput(
                        position=p, media_type="video", remote_url=remote_url,
                        local_path=local_path, transcript_status="pending",
                    )
                    for p in positions
                ),
            )
        )
        media = MediaRepo(conn).for_item(item_id)
        if seen_at is not None:
            for m in media:
                if m.remote_url:
                    MediaRepo(conn).set_remote_url(m.id, m.remote_url, seen_at)
    return item_id, [m.id for m in media]


def get_media(db: Database, media_id: int) -> Media:
    with db.read() as conn:
        media = MediaRepo(conn).get(media_id)
    assert media is not None
    return media


class FakeBackend:
    """Transcription backend returning canned transcripts (or raising)."""

    name = "fake-asr"
    model = "fake-model"

    def __init__(
        self,
        text: str = "Hallo und willkommen zu meinem Rezept",
        *,
        error: BaseException | None = None,
        unavailable: BaseException | None = None,
        on_transcribe: Callable[[Path, Path | None], Any] | None = None,
    ) -> None:
        self.text = text
        self.error = error
        self.unavailable = unavailable
        self.on_transcribe = on_transcribe
        self.calls: list[Path] = []
        self.work_dirs: list[Path | None] = []
        self.closed = False

    def check(self) -> None:
        if self.unavailable is not None:
            raise self.unavailable

    def transcribe(self, path: Path, *, work_dir: Path | None = None) -> Transcript:
        self.calls.append(Path(path))
        self.work_dirs.append(work_dir)
        assert Path(path).exists()
        if work_dir is not None:  # backends may leave intermediate files in work_dir
            (work_dir / "intermediate.m4a").write_bytes(b"x")
        if self.on_transcribe is not None:
            self.on_transcribe(Path(path), work_dir)
        if self.error is not None:
            raise self.error
        words = self.text.split()
        segments = [Segment(float(i), float(i) + 1.0, w) for i, w in enumerate(words)]
        return Transcript(
            text=self.text, language="de", segments=segments, duration=float(len(words)),
            backend=self.name, model=self.model,
        )

    def close(self) -> None:
        self.closed = True


class FakeFetcher:
    """Fetcher writing a generated MP4 (or raising per shortcode)."""

    def __init__(
        self,
        *,
        audio: bool = True,
        errors: dict[str, BaseException] | None = None,
        refetch: bool = True,
    ) -> None:
        self.audio = audio
        self.errors = dict(errors or {})
        self.refetch = refetch
        self.fetched: list[tuple[int, str, Path]] = []
        self.refetches = 0
        self.closed = False

    def fetch(self, media: Media, shortcode: str, dest_dir: Path) -> FetchedMedia:
        assert dest_dir.is_dir()
        target = dest_dir / f"{shortcode}_{media.position}.mp4"
        make_media_file(target, audio=self.audio)
        self.fetched.append((media.id, shortcode, target))
        if shortcode in self.errors:
            raise self.errors[shortcode]
        return FetchedMedia(target, size_bytes=target.stat().st_size)

    def close(self) -> None:
        self.closed = True


def fresh(minutes: int = 5) -> datetime:
    return NOW - timedelta(minutes=minutes)
