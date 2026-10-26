"""Audio helpers on top of PyAV (``av``), which bundles its own FFmpeg libraries.

* :func:`probe` tells whether a media file has an audio stream and how long it is.
* :func:`extract_audio` writes the audio track as a small mono file for upload
  backends: ``m4a`` (AAC, 16 kHz, ~48 kbit/s) or ``wav16k`` (16 kHz PCM).
* :func:`decode_pcm16k` decodes the audio track to the 16 kHz mono float32
  waveform the local Whisper backend consumes (faster-whisper's own decoder
  is not used because it relies on PyAV options removed in PyAV 16).

Example:
    >>> info = probe("clip.mp4")
    >>> info.has_audio, round(info.duration or 0)
    (True, 31)
    >>> extract_audio("clip.mp4", "clip.m4a", fmt="m4a")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NamedTuple, cast

import av

if TYPE_CHECKING:
    from av.audio.stream import AudioStream

__all__ = [
    "AudioFormat",
    "AudioProbe",
    "NoAudioStream",
    "decode_pcm16k",
    "extract_audio",
    "probe",
]

logger = logging.getLogger(__name__)

AudioFormat = Literal["m4a", "wav16k"]

_SAMPLE_RATE = 16_000
_AAC_BITRATE = 48_000


class NoAudioStream(ValueError):
    """The media file has no audio stream."""


class AudioProbe(NamedTuple):
    """Result of :func:`probe`.

    Attributes:
        has_audio: The container has at least one audio stream.
        duration: Duration in seconds (audio stream, else container), if known.
    """

    has_audio: bool
    duration: float | None


def probe(path: str | Path) -> AudioProbe:
    """Inspect a media file.

    Args:
        path: Video or audio file.

    Returns:
        ``(has_audio, duration)``.

    Raises:
        av.error.FFmpegError: If the file cannot be opened (corrupt / not media).
    """
    with av.open(str(path)) as container:
        audio = next((s for s in container.streams if s.type == "audio"), None)
        duration: float | None = None
        if audio is not None and audio.duration is not None and audio.time_base is not None:
            duration = float(audio.duration * audio.time_base)
        if duration is None and container.duration is not None:
            duration = container.duration / av.time_base
        return AudioProbe(audio is not None, duration)


def decode_pcm16k(path: str | Path) -> bytes:
    """Decode the first audio stream to mono 16 kHz float32 PCM (little endian).

    This is the waveform format Whisper models expect; ``numpy.frombuffer(data,
    numpy.float32)`` turns it into an array. Undecodable packets are skipped.

    Args:
        path: Media file.

    Returns:
        Raw samples (empty when the stream contains no decodable audio).

    Raises:
        NoAudioStream: If the file has no audio stream.
    """
    chunks: list[bytes] = []
    with av.open(str(path)) as container:
        stream = next(iter(container.streams.audio), None)
        if stream is None:
            raise NoAudioStream(f"No audio stream in {Path(path).name}")
        resampler = av.AudioResampler(format="flt", layout="mono", rate=_SAMPLE_RATE)
        frames = container.decode(stream)
        while True:
            try:
                frame = next(frames)
            except StopIteration:
                break
            except av.error.InvalidDataError:
                logger.debug("Skipping an invalid audio packet in %s", Path(path).name)
                continue
            frame.pts = None
            for resampled in resampler.resample(frame):
                chunks.append(_plane_bytes(resampled))
        for resampled in resampler.resample(None):
            chunks.append(_plane_bytes(resampled))
    return b"".join(chunks)


def _plane_bytes(frame: av.AudioFrame) -> bytes:
    """Return the packed samples of a mono float32 frame (without plane padding)."""
    return bytes(frame.planes[0])[: frame.samples * 4]


def extract_audio(src: str | Path, out: str | Path, fmt: AudioFormat = "m4a") -> Path:
    """Write the first audio stream of ``src`` as a mono 16 kHz file.

    Args:
        src: Input media file.
        out: Output file (its extension does not matter; the format is ``fmt``).
        fmt: ``m4a`` (AAC in an MP4 container) or ``wav16k`` (16-bit PCM WAV).

    Returns:
        ``out`` as a path.

    Raises:
        NoAudioStream: If ``src`` has no audio stream.
        ValueError: For an unknown ``fmt``.
    """
    if fmt == "m4a":
        codec, container_format, sample_format = "aac", "mp4", "fltp"
    elif fmt == "wav16k":
        codec, container_format, sample_format = "pcm_s16le", "wav", "s16"
    else:
        raise ValueError(f"Unknown audio format: {fmt!r}")
    out_path = Path(out)
    with av.open(str(src)) as inp:
        stream = next(iter(inp.streams.audio), None)
        if stream is None:
            raise NoAudioStream(f"No audio stream in {Path(src).name}")
        resampler = av.AudioResampler(format=sample_format, layout="mono", rate=_SAMPLE_RATE)
        with av.open(str(out_path), "w", format=container_format) as output:
            # codec is one of two audio codecs, so the stream is an AudioStream.
            out_stream = cast(
                "AudioStream", output.add_stream(codec, rate=_SAMPLE_RATE, layout="mono")
            )
            if codec == "aac":
                out_stream.bit_rate = _AAC_BITRATE
            for frame in inp.decode(stream):
                frame.pts = None
                for resampled in resampler.resample(frame):
                    for packet in out_stream.encode(resampled):
                        output.mux(packet)
            for resampled in resampler.resample(None):
                for packet in out_stream.encode(resampled):
                    output.mux(packet)
            for packet in out_stream.encode(None):
                output.mux(packet)
    logger.debug("Extracted audio of %s to %s (%s)", Path(src).name, out_path.name, fmt)
    return out_path
