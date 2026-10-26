"""Local speech recognition with faster-whisper (CTranslate2), CUDA or CPU.

Requires the optional ``asr`` extra (``uv sync --extra asr``), which installs
faster-whisper plus the NVIDIA cuBLAS / cuDNN wheels. This module imports
faster-whisper lazily: importing it always works, :meth:`FasterWhisperBackend.check`
and the first transcription raise :class:`BackendUnavailable` with an install
hint when the extra is missing.

Defaults: model ``large-v3-turbo``; ``device="auto"`` uses CUDA when
CTranslate2 sees a GPU, else the CPU; ``compute_type="auto"`` is
``int8_float16`` on CUDA and ``int8`` on CPU; voice activity detection on,
``condition_on_previous_text=False`` (avoids repetition loops on music-heavy
reels), language auto-detected unless configured.

The model is loaded once per process (shared by all backend instances with the
same settings). If CUDA initialisation fails -- at load time or on the first
transcription (missing DLLs) -- the backend logs a warning and falls back to
the CPU.

On Windows the DLL directories of the ``nvidia-*-cu12`` wheels
(``site-packages/nvidia/*/bin``) are registered with ``os.add_dll_directory``
and prepended to ``PATH`` before the model is created.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from postparse.media.transcription.base import (
    BackendUnavailable,
    Segment,
    Transcript,
    TranscriptionError,
)

__all__ = ["DEFAULT_MODEL", "FasterWhisperBackend", "clear_model_cache", "register_cuda_dlls"]

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "large-v3-turbo"
_INSTALL_HINT = (
    "faster-whisper is not installed. Install the optional ASR dependencies with "
    "`uv sync --extra asr` (or `pip install postparse[asr]`), or use the API backend "
    "(`--backend api`)."
)
_CUDA_ERROR_MARKERS = ("cuda", "cublas", "cudnn", ".dll", ".so", "libcu", "gpu")

_models_lock = threading.Lock()
_models: dict[tuple[Any, ...], tuple[Any, str, str]] = {}
_dll_dirs_registered = False


def clear_model_cache() -> None:
    """Forget loaded models (frees GPU memory once no backend references them)."""
    with _models_lock:
        _models.clear()


def register_cuda_dlls() -> list[str]:
    """Make the CUDA libraries of the ``nvidia-*-cu12`` wheels loadable (Windows).

    Returns:
        Directories registered (empty on other platforms or without the wheels).
    """
    global _dll_dirs_registered
    if sys.platform != "win32" or _dll_dirs_registered:
        return []
    _dll_dirs_registered = True
    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return []
    registered: list[str] = []
    for root in spec.submodule_search_locations:
        for bin_dir in sorted(Path(root).glob("*/bin")):
            if not bin_dir.is_dir():
                continue
            try:
                os.add_dll_directory(str(bin_dir))
            except OSError:  # pragma: no cover - directory vanished
                continue
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            registered.append(str(bin_dir))
    if registered:
        logger.debug("Registered CUDA DLL directories: %s", registered)
    return registered


def _cuda_device_count() -> int:
    """Return the number of CUDA devices CTranslate2 can use (0 on any error)."""
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:  # pragma: no cover - depends on the driver
        return 0


def _load_waveform(path: Path) -> Any:
    """Decode ``path`` to a float32 numpy waveform (16 kHz mono); ``None`` without audio."""
    import numpy as np

    from postparse.media.audio import NoAudioStream, decode_pcm16k

    try:
        data = decode_pcm16k(path)
    except NoAudioStream:
        return None
    if not data:
        return None
    return np.frombuffer(data, dtype=np.float32)


def _looks_like_cuda_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _CUDA_ERROR_MARKERS)


class FasterWhisperBackend:
    """Transcribe with a local faster-whisper model.

    Args:
        model: Model size or path (``large-v3-turbo``, ``medium``, a CTranslate2 dir, ...).
        device: ``auto``, ``cuda`` or ``cpu``.
        compute_type: CTranslate2 compute type or ``auto``.
        beam_size: Beam size.
        vad_filter: Skip non-speech parts with Silero VAD.
        language: Force a language (``None``: detect).
        download_root: Model cache directory (``None``: Hugging Face cache).
        cpu_threads: CPU threads (0: CTranslate2 default).
    """

    name = "faster-whisper"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        device: str = "auto",
        compute_type: str = "auto",
        beam_size: int = 5,
        vad_filter: bool = True,
        language: str | None = None,
        download_root: str | None = None,
        cpu_threads: int = 0,
    ) -> None:
        if device not in ("auto", "cuda", "cpu"):
            raise ValueError(f"device must be 'auto', 'cuda' or 'cpu', not {device!r}")
        self.model = model
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.language = language or None
        self.download_root = download_root
        self.cpu_threads = cpu_threads
        #: Device / compute type actually used (set when the model is loaded).
        self.active_device: str | None = None
        self.active_compute_type: str | None = None
        #: Seconds spent loading the model in this process (0 when cached).
        self.load_seconds: float = 0.0
        self._whisper: Any = None

    # -- loading -----------------------------------------------------------

    def check(self) -> None:
        """Raise :class:`BackendUnavailable` if faster-whisper is not installed."""
        if importlib.util.find_spec("faster_whisper") is None:
            raise BackendUnavailable(_INSTALL_HINT)

    def _resolve(self, device: str) -> tuple[str, str]:
        """Return ``(device, compute_type)`` for a requested device."""
        if device == "auto":
            device = "cuda" if _cuda_device_count() > 0 else "cpu"
        compute = self.compute_type
        if compute == "auto":
            compute = "int8_float16" if device == "cuda" else "int8"
        return device, compute

    def _create(self, device: str, compute: str) -> Any:
        from faster_whisper import WhisperModel

        key = (self.model, device, compute, self.download_root, self.cpu_threads)
        with _models_lock:
            cached = _models.get(key)
        if cached is not None:
            return cached[0]
        started = time.perf_counter()
        whisper = WhisperModel(
            self.model,
            device=device,
            compute_type=compute,
            download_root=self.download_root,
            cpu_threads=self.cpu_threads,
        )
        self.load_seconds = time.perf_counter() - started
        logger.info(
            "Loaded faster-whisper model %s on %s (%s) in %.1fs",
            self.model,
            device,
            compute,
            self.load_seconds,
        )
        with _models_lock:
            return _models.setdefault(key, (whisper, device, compute))[0]

    def load(self) -> None:
        """Load the model now (warm-up / ``postparse check transcription --load-model``).

        Raises:
            BackendUnavailable: faster-whisper is missing or the model cannot be loaded.
        """
        self._load()

    def _load(self, force_cpu: bool = False) -> Any:
        """Load (or reuse) the model, falling back to the CPU if CUDA fails."""
        if self._whisper is not None and not force_cpu:
            return self._whisper
        self.check()
        register_cuda_dlls()
        device, compute = self._resolve("cpu" if force_cpu else self.device)
        try:
            whisper = self._create(device, compute)
        except Exception as exc:
            if device != "cuda":
                raise BackendUnavailable(f"Could not load faster-whisper model: {exc}") from exc
            logger.warning("CUDA initialisation failed (%s); falling back to the CPU", exc)
            device, compute = self._resolve("cpu")
            try:
                whisper = self._create(device, compute)
            except Exception as exc2:
                raise BackendUnavailable(f"Could not load faster-whisper model: {exc2}") from exc2
        self._whisper = whisper
        self.active_device, self.active_compute_type = device, compute
        return whisper

    # -- transcription -------------------------------------------------------

    def _run(self, whisper: Any, path: Path) -> Transcript:
        audio = _load_waveform(path)
        if audio is None:
            return Transcript(text="", language=None, backend=self.name, model=self.model)
        segments_iter, info = whisper.transcribe(
            audio,
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            condition_on_previous_text=False,
            language=self.language,
        )
        segments = [
            Segment(float(s.start), float(s.end), s.text.strip())
            for s in segments_iter
            if s.text and s.text.strip()
        ]
        return Transcript(
            text=" ".join(s.text for s in segments).strip(),
            language=getattr(info, "language", None),
            segments=segments,
            duration=getattr(info, "duration", None),
            backend=self.name,
            model=self.model,
            language_probability=getattr(info, "language_probability", None),
        )

    def transcribe(self, path: Path, *, work_dir: Path | None = None) -> Transcript:
        """Transcribe ``path`` (audio decoded in memory with PyAV; no files written).

        Raises:
            BackendUnavailable: faster-whisper missing or the model cannot be loaded.
            TranscriptionError: Decoding / inference failed.
        """
        whisper = self._load()
        try:
            return self._run(whisper, Path(path))
        except Exception as exc:
            if self.active_device == "cuda" and _looks_like_cuda_error(exc):
                logger.warning("CUDA inference failed (%s); retrying on the CPU", exc)
                whisper = self._load(force_cpu=True)
                try:
                    return self._run(whisper, Path(path))
                except Exception as exc2:
                    raise TranscriptionError(f"{type(exc2).__name__}: {exc2}") from exc2
            raise TranscriptionError(f"{type(exc).__name__}: {exc}") from exc

    def close(self) -> None:
        """Drop this instance's model reference (the process cache keeps it)."""
        self._whisper = None
