"""ASR backends: OpenAI-compatible (mocked HTTP transport) and faster-whisper (fake module)."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any, ClassVar

import httpx
import openai
import pytest

from postparse.media.options import TranscriptionOptions
from postparse.media.transcription import (
    BackendUnavailable,
    TranscriptionError,
    build_backend,
)
from postparse.media.transcription import local_faster_whisper as lfw
from postparse.media.transcription.local_faster_whisper import FasterWhisperBackend
from postparse.media.transcription.openai_compatible import OpenAICompatibleBackend
from tests.unit.media.helpers import make_media_file

# ---------------------------------------------------------------------------
# OpenAI-compatible
# ---------------------------------------------------------------------------

VERBOSE = {
    "task": "transcribe",
    "language": "german",
    "duration": 9.5,
    "text": " Heute machen wir Pasta. ",
    "segments": [
        {
            "id": 0,
            "seek": 0,
            "start": 0.0,
            "end": 2.5,
            "text": " Heute machen wir",
            "tokens": [],
            "temperature": 0.0,
            "avg_logprob": -0.1,
            "compression_ratio": 1.0,
            "no_speech_prob": 0.01,
        },
        {
            "id": 1,
            "seek": 0,
            "start": 2.5,
            "end": 4.0,
            "text": " Pasta.",
            "tokens": [],
            "temperature": 0.0,
            "avg_logprob": -0.1,
            "compression_ratio": 1.0,
            "no_speech_prob": 0.01,
        },
    ],
}


class AsrServer:
    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status = status
        self.body = VERBOSE if body is None else body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body)


def api_backend(server: AsrServer, **kwargs: Any) -> OpenAICompatibleBackend:
    client = openai.OpenAI(
        api_key="test-key",
        base_url="http://asr.test/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(server)),
    )
    return OpenAICompatibleBackend("http://asr.test/v1", model="whisper-x", client=client, **kwargs)


def test_api_backend_uploads_audio_and_parses_segments(tmp_path: Path) -> None:
    server = AsrServer()
    src = make_media_file(tmp_path / "clip.mp4")
    work = tmp_path / "work"
    work.mkdir()
    result = api_backend(server, language="de").transcribe(src, work_dir=work)
    assert result.text == "Heute machen wir Pasta."
    assert result.language == "de" and result.duration == 9.5
    assert result.segments[0] == (0.0, 2.5, "Heute machen wir")
    assert result.backend == "openai-compatible" and result.model == "whisper-x"
    (request,) = server.requests
    assert request.url.path == "/v1/audio/transcriptions"
    body = request.content
    assert b'name="model"' in body and b"whisper-x" in body
    assert b"verbose_json" in body and b"segment" in body
    assert b'name="language"' in body
    assert b'filename="clip.upload.m4a"' in body
    assert list(work.iterdir()) == []  # uploaded audio removed


def test_api_backend_without_audio_returns_empty(tmp_path: Path) -> None:
    server = AsrServer()
    src = make_media_file(tmp_path / "silent.mp4", audio=False)
    result = api_backend(server).transcribe(src)
    assert result.is_empty and server.requests == []


def test_api_backend_http_error(tmp_path: Path) -> None:
    src = make_media_file(tmp_path / "clip.mp4")
    with pytest.raises(TranscriptionError, match="request failed"):
        api_backend(AsrServer(status=500, body={"error": {"message": "boom"}})).transcribe(src)


def test_api_backend_auth_error_is_unavailable(tmp_path: Path) -> None:
    src = make_media_file(tmp_path / "clip.mp4")
    with pytest.raises(BackendUnavailable, match="credentials"):
        api_backend(AsrServer(status=401, body={"error": {"message": "bad key"}})).transcribe(src)


def test_api_backend_key_lookup() -> None:
    cloud = OpenAICompatibleBackend(None, api_key_env="MY_KEY", env={})
    with pytest.raises(BackendUnavailable, match="MY_KEY"):
        cloud.check()
    OpenAICompatibleBackend(None, api_key_env="MY_KEY", env={"MY_KEY": "k"}).check()
    # Self-hosted servers do not need a key.
    OpenAICompatibleBackend("http://speaches.lan:8000/v1", env={}).check()


def test_build_backend_api_from_options() -> None:
    options = TranscriptionOptions.from_config(None)
    backend = build_backend(options, "api", env={"OPENAI_API_KEY": "k"})
    assert isinstance(backend, OpenAICompatibleBackend)
    assert backend.model == "whisper-1" and backend.host == "api.openai.com"
    with pytest.raises(ValueError):
        build_backend(options, "cloud")  # type: ignore[arg-type]


def test_segments_json_is_serializable(tmp_path: Path) -> None:
    result = api_backend(AsrServer()).transcribe(make_media_file(tmp_path / "c.mp4"))
    data = json.loads(json.dumps(result.segments_json()))
    assert data[1] == {"start": 2.5, "end": 4.0, "text": "Pasta."}


# ---------------------------------------------------------------------------
# faster-whisper (fake module; the real extra is not needed)
# ---------------------------------------------------------------------------


class FakeWhisperModel:
    instances: ClassVar[list[FakeWhisperModel]] = []
    fail_devices: ClassVar[set[str]] = set()
    fail_transcribe_on: ClassVar[set[str]] = set()

    def __init__(
        self,
        model: str,
        device: str,
        compute_type: str,
        download_root: Any = None,
        cpu_threads: int = 0,
    ) -> None:
        if device in self.fail_devices:
            raise RuntimeError("CUDA failed with error no CUDA-capable device is detected")
        self.model, self.device, self.compute_type = model, device, compute_type
        self.calls: list[dict[str, Any]] = []
        FakeWhisperModel.instances.append(self)

    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[Any, Any]:
        self.calls.append({"audio": audio, **kwargs})
        if self.device in self.fail_transcribe_on:
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
        segments = iter(
            [
                types.SimpleNamespace(start=0.0, end=1.2, text=" Hallo"),
                types.SimpleNamespace(start=1.2, end=2.0, text="  "),
                types.SimpleNamespace(start=2.0, end=3.0, text=" Welt."),
            ]
        )
        info = types.SimpleNamespace(language="de", language_probability=0.98, duration=3.0)
        return segments, info


@pytest.fixture
def fake_whisper(monkeypatch: pytest.MonkeyPatch):
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: object() if name == "faster_whisper" else real_find_spec(name, *a),
    )
    # The real decoder needs numpy (an `asr` dependency); feed a dummy waveform instead.
    monkeypatch.setattr(lfw, "_load_waveform", lambda path: [0.0] * 16000)
    FakeWhisperModel.instances = []
    FakeWhisperModel.fail_devices = set()
    FakeWhisperModel.fail_transcribe_on = set()
    lfw.clear_model_cache()
    yield FakeWhisperModel
    lfw.clear_model_cache()


def test_local_backend_without_extra(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "faster_whisper" else real_find_spec(name, *a),
    )
    backend = FasterWhisperBackend()
    with pytest.raises(BackendUnavailable, match="--extra asr"):
        backend.check()
    with pytest.raises(BackendUnavailable):
        backend.transcribe(tmp_path / "x.mp4")


def test_local_backend_cuda_defaults(
    fake_whisper, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(lfw, "_cuda_device_count", lambda: 1)
    backend = FasterWhisperBackend()
    result = backend.transcribe(tmp_path / "clip.mp4")
    (model,) = fake_whisper.instances
    assert (model.model, model.device, model.compute_type) == (
        "large-v3-turbo",
        "cuda",
        "int8_float16",
    )
    call = model.calls[0]
    assert call["vad_filter"] is True and call["condition_on_previous_text"] is False
    assert call["language"] is None and call["beam_size"] == 5
    assert len(call["audio"]) == 16000  # decoded waveform, not a path
    assert result.text == "Hallo Welt." and len(result.segments) == 2
    assert result.language == "de" and result.duration == 3.0
    assert backend.active_device == "cuda"


def test_local_backend_cpu_and_model_cache(
    fake_whisper, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(lfw, "_cuda_device_count", lambda: 0)
    first = FasterWhisperBackend(model="small", language="de")
    first.transcribe(tmp_path / "a.mp4")
    second = FasterWhisperBackend(model="small")
    second.transcribe(tmp_path / "b.mp4")
    assert len(fake_whisper.instances) == 1  # loaded once per process
    model = fake_whisper.instances[0]
    assert (model.device, model.compute_type) == ("cpu", "int8")
    assert model.calls[0]["language"] == "de" and model.calls[1]["language"] is None


def test_local_backend_falls_back_to_cpu_on_load_error(
    fake_whisper, monkeypatch, tmp_path: Path, caplog
) -> None:
    monkeypatch.setattr(lfw, "_cuda_device_count", lambda: 1)
    fake_whisper.fail_devices = {"cuda"}
    backend = FasterWhisperBackend()
    with caplog.at_level("WARNING"):
        backend.transcribe(tmp_path / "clip.mp4")
    assert backend.active_device == "cpu" and backend.active_compute_type == "int8"
    assert "falling back to the CPU" in caplog.text


def test_local_backend_falls_back_to_cpu_on_inference_dll_error(
    fake_whisper, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(lfw, "_cuda_device_count", lambda: 1)
    fake_whisper.fail_transcribe_on = {"cuda"}
    backend = FasterWhisperBackend()
    result = backend.transcribe(tmp_path / "clip.mp4")
    assert result.text == "Hallo Welt." and backend.active_device == "cpu"


def test_local_backend_errors_are_transcription_errors(
    fake_whisper, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(lfw, "_cuda_device_count", lambda: 0)
    fake_whisper.fail_transcribe_on = {"cpu"}
    with pytest.raises(TranscriptionError):
        FasterWhisperBackend().transcribe(tmp_path / "clip.mp4")


def test_build_backend_local_from_options() -> None:
    backend = build_backend(TranscriptionOptions.from_config(None), "local")
    assert isinstance(backend, FasterWhisperBackend)
    assert backend.model == "large-v3-turbo" and backend.device == "auto"
    with pytest.raises(ValueError):
        FasterWhisperBackend(device="tpu")


def test_local_backend_without_audio_returns_empty(
    fake_whisper, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(lfw, "_cuda_device_count", lambda: 0)
    monkeypatch.setattr(lfw, "_load_waveform", lambda path: None)
    result = FasterWhisperBackend().transcribe(tmp_path / "silent.mp4")
    assert result.is_empty
    assert fake_whisper.instances[0].calls == []
