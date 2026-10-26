"""PyAV probe / audio extraction on tiny generated files (no network, no ffmpeg)."""

from __future__ import annotations

from pathlib import Path

import av
import pytest

from postparse.media.audio import NoAudioStream, decode_pcm16k, extract_audio, probe
from tests.unit.media.helpers import make_media_file


def test_probe_video_with_audio(tmp_path: Path) -> None:
    info = probe(make_media_file(tmp_path / "av.mp4", seconds=1.0))
    assert info.has_audio is True
    assert info.duration == pytest.approx(1.0, abs=0.1)
    has_audio, duration = info  # tuple-unpackable
    assert has_audio and duration


def test_probe_video_without_audio(tmp_path: Path) -> None:
    info = probe(make_media_file(tmp_path / "v.mp4", audio=False))
    assert info.has_audio is False
    assert info.duration == pytest.approx(1.0, abs=0.2)


def test_probe_rejects_non_media(tmp_path: Path) -> None:
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video at all")
    with pytest.raises(av.error.FFmpegError):
        probe(junk)


@pytest.mark.parametrize(
    ("fmt", "codec", "suffix"), [("m4a", "aac", ".m4a"), ("wav16k", "pcm_s16le", ".wav")]
)
def test_extract_audio(tmp_path: Path, fmt: str, codec: str, suffix: str) -> None:
    src = make_media_file(tmp_path / "av.mp4", seconds=1.0)
    out = extract_audio(src, tmp_path / f"out{suffix}", fmt)  # type: ignore[arg-type]
    assert out.exists() and out.stat().st_size > 0
    with av.open(str(out)) as container:
        streams = [s for s in container.streams if s.type == "audio"]
        assert len(streams) == 1 and not any(s.type == "video" for s in container.streams)
        stream = streams[0]
        assert stream.codec_context.name == codec
        assert stream.codec_context.sample_rate == 16000
        assert stream.codec_context.channels == 1
    assert probe(out).duration == pytest.approx(1.0, abs=0.15)


def test_extract_audio_without_audio_stream(tmp_path: Path) -> None:
    src = make_media_file(tmp_path / "v.mp4", audio=False)
    with pytest.raises(NoAudioStream):
        extract_audio(src, tmp_path / "out.m4a")


def test_extract_audio_unknown_format(tmp_path: Path) -> None:
    src = make_media_file(tmp_path / "av.mp4")
    with pytest.raises(ValueError, match="Unknown audio format"):
        extract_audio(src, tmp_path / "out.ogg", "ogg")  # type: ignore[arg-type]


def test_decode_pcm16k(tmp_path: Path) -> None:
    import struct

    data = decode_pcm16k(make_media_file(tmp_path / "av.mp4", seconds=1.0))
    samples = len(data) // 4
    assert len(data) % 4 == 0
    assert 15000 <= samples <= 17500  # ~1 s at 16 kHz (AAC priming may add a little)
    values = struct.unpack(f"<{samples}f", data)
    peak = max(abs(v) for v in values)
    assert 0.2 < peak < 0.4  # the 0.3 amplitude tone survives the round trip
    with pytest.raises(NoAudioStream):
        decode_pcm16k(make_media_file(tmp_path / "v.mp4", audio=False))
