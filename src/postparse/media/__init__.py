"""Media handling for transcription: fetching videos, audio helpers and ASR backends.

Nothing in this package keeps media files: videos are downloaded into a
per-media scratch directory below ``Settings.tmp_dir/transcribe/`` and deleted
as soon as the transcript is stored (see
:mod:`postparse.services.transcription`).

Modules:

* :mod:`postparse.media.options` -- ``[transcription]`` configuration.
* :mod:`postparse.media.fetch` -- download Instagram videos (re-fetching expired URLs).
* :mod:`postparse.media.audio` -- PyAV probe / audio extraction (no system ffmpeg).
* :mod:`postparse.media.transcription` -- ASR backends (local faster-whisper,
  OpenAI-compatible API).
"""
