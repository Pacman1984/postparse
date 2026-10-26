# Video transcription

PostParse transcribes the audio of saved videos (Instagram reels and video
posts, carousel video children, Telegram videos and audio) and stores the
transcripts in the database. They become part of the search index, the summary
input and the classification input.

**Nothing is stored except the text.** Each media is downloaded into a scratch
directory below `<tmp_dir>/transcribe/`, transcribed, and the directory is
deleted afterwards, also after errors and Ctrl-C.

## Backends

| Backend | `transcription.backend` | Requirements |
|---|---|---|
| Local faster-whisper (CTranslate2), CUDA or CPU | `local` (default) | `uv sync --extra asr` |
| Any OpenAI-compatible `/v1/audio/transcriptions` endpoint (OpenAI, speaches, ...) | `api` | network access; key in the env variable named by `transcription.api.api_key_env` |

Switch per run with `postparse transcribe run --backend api`.

### Local (faster-whisper)

Defaults: model `large-v3-turbo`, `device = "auto"` (CUDA when CTranslate2 sees a
GPU, otherwise CPU), `compute_type = "auto"` (`int8_float16` on CUDA, `int8` on
CPU), beam size 5, voice activity detection on, language auto-detected unless
`transcription.language` is set. The model is downloaded on first use into the
Hugging Face cache (or `transcription.local.download_root`) and loaded once per
process.

```bash
uv sync --extra asr
postparse check transcription              # faster-whisper installed? CUDA devices?
postparse check transcription --load-model # also load (and download) the model
```

**CUDA on Windows (and Linux).** The `asr` extra installs the NVIDIA wheels
`nvidia-cublas-cu12` and `nvidia-cudnn-cu12` (cuDNN 9), so no system CUDA
toolkit is needed; only a current NVIDIA driver. On Windows PostParse registers
the DLL directories of these wheels (`site-packages/nvidia/*/bin`) with
`os.add_dll_directory` and prepends them to `PATH` before the model is created.
If CUDA initialisation fails — at load time or on the first transcription
(for example missing DLLs) — the backend logs a warning and **falls back to the
CPU**. Force a device with `transcription.local.device = "cuda"` or `"cpu"`.
The NVIDIA wheels are not installed on macOS or Linux aarch64.

### OpenAI-compatible API

```toml
[transcription]
backend = "api"

[transcription.api]
base_url = "http://speaches.lan:8000/v1"   # empty: api.openai.com
api_key_env = "OPENAI_API_KEY"             # NAME of the env variable with the key
model = "Systran/faster-whisper-large-v3"  # default "whisper-1"
upload_format = "m4a"                      # or "wav16k"
timeout = 300
```

The audio is extracted with PyAV (bundled FFmpeg, no system `ffmpeg` needed) and
uploaded as small AAC (`m4a`) or 16 kHz WAV.
`postparse check transcription --backend api` checks that the endpoint is
reachable.

## The transcription queue

Every video/audio media row starts with `transcript_status = pending`.
`postparse transcribe run` works through the due rows one media at a time:

1. fetch the video: the stored Instagram URL if it was seen less than
   `remote_url_max_age_hours` (6 h) ago, otherwise **re-fetch the post** from
   Instagram (one request, throttled 20–60 s apart, one login per run); Telegram
   media use the downloaded file below `downloads_dir`;
2. probe it (no audio stream → `no_audio`);
3. transcribe it (empty result → `no_audio`);
4. store the transcript, refresh the search document and mark the media
   `transcribed` in one transaction;
5. delete the scratch directory.

| Status | Meaning |
|---|---|
| `pending` | waiting for its first attempt |
| `transcribed` | transcript stored |
| `no_audio` | no audio stream or no speech |
| `failed` | last attempt failed; retried after a backoff (10 min, doubling, max 24 h) until `max_attempts` (5) |
| `skipped` | deleted/private post, no video at that position, or longer than `max_duration_minutes` (30); reason in `last_error` |

`--item ID` (repeatable) transcribes specific items and ignores the retry
backoff. `--no-refetch` never contacts Instagram (media without a fresh URL
stay pending). `--source` defaults to `instagram` (`telegram`, `all`).

```bash
postparse transcribe status        # queue per source and status, next retries, totals
```

## Throttled backlog

A large archive (for example after `db migrate-v1`, where every Instagram video
needs a re-fetch because the CDN URLs expired) must be worked off slowly to
avoid Instagram blocks. Run a bounded batch once a day:

```bash
postparse transcribe run --limit 50      # transcription.limit is 50 by default
```

With 20–60 s between re-fetches, 50 media take roughly half an hour plus
transcription time. Schedule it (Task Scheduler / cron) after `extract`; see the
[runbook](operations.md#daily-backlog).

Newly collected posts have fresh URLs: `postparse extract instagram --transcribe`
transcribes (and summarizes) the videos of the posts collected in that run
without any re-fetch.

## Circuit breaker for soft blocks

Instagram answers a soft-blocked session with errors that look like missing
posts. To avoid burning retries, the run stops after
`max_consecutive_refetch_failures` (default 3) re-fetch failures **in a row**
with `stopped_reason = suspected_block` and **exit code 3**. A rate limit stops
the run with exit code 3 as well, a missing/invalid Instagram login with exit
code 2. Everything committed before the stop is kept; wait a few hours before
the next run. Set the threshold to `0` to disable the breaker.

Exit codes of `transcribe run`: `0` success, `1` error / ASR backend
unavailable, `2` Instagram login required, `3` rate limited or suspected block,
`130` interrupted.

## Summaries

`postparse summarize run` summarizes items that have a transcript and no
summary newer than it, using the LLM provider from `summarization.provider` (or
`llm.default_provider`). The input is the caption, the transcripts and fetched
link texts, cut to `summarization.max_input_chars` (12000). `--force`
re-summarizes, `--item ID` limits the run to specific items.

## Configuration

All keys of `[transcription]`, `[transcription.local]` and `[transcription.api]`
are documented in [`config/config.example.toml`](https://github.com/Pacman1984/postparse/blob/master/config/config.example.toml);
`postparse config show --section transcription` prints the effective values.
