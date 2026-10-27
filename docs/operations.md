# Operations runbook

Commands assume the project directory as working directory, so `config/` and
`data/` resolve as in the defaults. Prefix with `uv run` when the virtual
environment is not activated.

## Health check

```bash
postparse info                 # versions, paths, database schema / item count
postparse check                # = check all: database, transcription, sessions, LLM
postparse check all --login    # also verify the Telegram/Instagram sessions online
postparse config validate      # configuration, paths, providers, taxonomies
postparse stats                # counts, queues, coverage, pending classifications
```

## Backup

The database is a single SQLite file; sessions are separate files. Stop running
`postparse` processes (CLI jobs, `serve`) before copying, or use SQLite's online
backup, which is consistent while other connections read:

```bash
uv run python -c "import sqlite3; s = sqlite3.connect('data/postparse.db'); d = sqlite3.connect('backup/postparse-2026-10-26.db'); s.backup(d); d.close(); s.close()"
# or with the sqlite3 shell:
sqlite3 data/postparse.db ".backup 'backup/postparse-2026-10-26.db'"
```

Also keep a copy of `data/sessions/` (Telegram and Instagram sessions; they are
credentials, store them privately) and of `config/config.toml` / `config/.env`.
Downloaded Telegram media live in `data/downloads/`.

## Upgrading

### From 0.1 (schema v1)

1. Back up `data/social_media.db` (and `data/downloads/`).
2. Install 0.2 (`uv sync`, plus `--extra migrate` for ftfy text repair).
3. Create `config/config.toml` from `config/config.example.toml`; remove the v1
   keys `[database] default_db_path` / `path` (they are ignored and only produce
   a warning). Move session files to `data/sessions/` if you like (the old
   locations are still found as fallbacks).
4. Migrate into a new file:

   ```bash
   postparse db migrate-v1 --source data/social_media.db --target data/postparse.db \
       --report data/migrate-v1-report.json
   postparse db check
   postparse stats
   ```

   Use `--instagram-tz` if the v1 data was collected on a machine that was not
   in `Europe/Berlin`. The v1 file is never modified.
5. Optionally verify Instagram dates: `postparse extract instagram --refresh-dates
   --refresh-limit 200` (throttled; repeat on later days).
6. Work off the migrated backlog with the [daily backlog](#daily-backlog) and
   `postparse enrich run` (re-enriches v1 link texts).

Details of the mapping: [Database](database.md#upgrading-from-schema-v1).

### Schema updates within v2

New migrations are applied automatically by the first write command, or
explicitly:

```bash
postparse db migrate
postparse db check
```

## Refresh pipeline

Collect and process everything new, in dependency order:

```bash
postparse extract all                     # incremental; exit 2 = login needed, 3 = rate limited
postparse transcribe run --limit 50       # pending videos (throttled re-fetches)
postparse enrich run                      # new links, due retries, v1 link texts
postparse summarize run                   # items with a newer transcript than summary
postparse classify run --taxonomy topics  # default scope: new + never classified items
```

The `default` classification scope never re-classifies old posts by itself; see
[Taxonomies](taxonomies.md#scopes-default-backfill-reprocess). Each step only
works on what is pending, commits per item and can be re-run at any time.

As a script (bash) that stops after a login problem but continues after a rate
limit:

```bash
#!/usr/bin/env bash
set -u
cd /path/to/postparse
uv run postparse --quiet extract all --no-interactive; rc=$?
[ "$rc" -eq 2 ] && { echo "login required: run 'postparse extract all' interactively"; exit 2; }
uv run postparse --quiet transcribe run --limit 50
uv run postparse --quiet enrich run --limit 500
uv run postparse --quiet summarize run --limit 50
uv run postparse --quiet classify run --taxonomy topics --limit 500
```

PowerShell equivalent (Task Scheduler):

```powershell
Set-Location D:\path\to\postparse
uv run postparse --quiet extract all --no-interactive
if ($LASTEXITCODE -eq 2) { Write-Warning "Login required"; exit 2 }
uv run postparse --quiet transcribe run --limit 50
uv run postparse --quiet enrich run --limit 500
uv run postparse --quiet summarize run --limit 50
uv run postparse --quiet classify run --taxonomy topics --limit 500
```

Use `--no-interactive` in unattended runs, so a required login ends with exit
code 2 instead of waiting for input.

## Daily backlog

After a v1 migration (or when you saved many videos) the transcription queue
can hold hundreds of Instagram videos whose URLs must be re-fetched. Work them
off in small daily batches:

```bash
postparse transcribe status
postparse transcribe run --limit 50
```

* Re-fetches are 20–60 s apart; 50 media per day keeps the session inconspicuous.
* Exit code `3` means rate limited or **suspected soft block** (three re-fetch
  failures in a row): stop for the day; progress is kept.
* Exit code `2` means the Instagram session is invalid: run
  `postparse extract instagram` once interactively.
* Videos of freshly collected posts do not need re-fetches:
  `postparse extract instagram --transcribe` handles them right away.

The same applies to `extract instagram --refresh-dates --refresh-limit N` for
migrated post dates.

## Manual reprocessing

Re-classify a subset regardless of earlier results (a new run is added; old
results remain in the history):

```bash
postparse classify run --taxonomy topics --reprocess --source instagram --with-transcript
```

Other examples:

```bash
# Labels or descriptions changed: classify everything not done for the new label set
postparse classify run -t topics --backfill --limit 500

# Re-transcribe / re-summarize specific items
postparse transcribe run --item 123 --item 124
postparse summarize run --force --item 123

# Refetch links of one domain
postparse enrich run --force --domain example.com

# Rebuild the full-text index after manual SQL changes
postparse db reindex
```

## Troubleshooting

### Telegram: login code and 2FA

* The first `postparse extract telegram` (or `check telegram --login`) asks for
  the phone number (or uses `TELEGRAM_PHONE`), then for the login code Telegram
  sends to your app, and for the 2FA password if one is set. Enter them in the
  terminal; the session is saved to `data/sessions/telegram.session`.
* `--no-interactive`, the API and scheduled runs never prompt: they stop with
  exit code 2 / `error_code: auth_required`. Log in once interactively.
* `credentials missing`: set `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`
  (from my.telegram.org) in `config/.env`; `postparse config env` shows what is set.
* Exit code 3 / FloodWait: Telegram asked to wait longer than
  `telegram.flood_sleep_threshold`; retry later.

### Instagram: logging in, checkpoint, 2FA, soft block

* **Logging in (recommended): import the browser session** with
  `postparse check instagram --import-session` in a terminal. No password is
  used:
  1. Log in to Instagram in your browser (the account of
     `INSTAGRAM_USERNAME`).
  2. Open the developer tools (F12). Chrome / Edge: **Application** →
     **Cookies** → `https://www.instagram.com`; Firefox: **Storage** →
     **Cookies** → `https://www.instagram.com`.
  3. Copy the value of the `sessionid` cookie (it looks like
     `<digits>%3A...`; a copy with `:` instead of `%3A` is accepted too) and
     paste it into the hidden prompt. The `csrftoken` prompt is optional
     (Enter generates one).
  4. postparse makes exactly **one** request (the session check) and saves
     the session file (`data/sessions/instagram_<username>`, or `--session`)
     only when Instagram confirms the session of `INSTAGRAM_USERNAME`; a
     logged-out session, a session of another account or a throttled check
     saves nothing and leaves an existing session file alone.
  5. Set `[instagram] user_agent` in `config/config.toml` to the User-Agent of
     that browser (e.g. from `navigator.userAgent` in the browser console), so
     the session is used with the same browser identity.
  6. Do not log out of Instagram in that browser: logging out ends this
     session too (closing the browser is fine).

  The prompt needs an interactive terminal; the cookie is never read from
  arguments, pipes or the environment and is never shown or logged.
* **Password login (alternative)**: `postparse check instagram --login`
  verifies the saved session and, only if there is none or Instagram says it
  is logged out, logs in with `INSTAGRAM_PASSWORD`. It prints a warning before
  that password login and may ask for a 2FA code or a confirmation in the
  Instagram app. It is the **only** command that ever uses the password. The
  new session is verified (one request) before it is saved: instaloader may
  report a successful login although Instagram set no `sessionid` cookie
  (instaloader issue #2487); then `--login` stops with "Instagram accepted the
  password but returned no session cookie ...; nothing was saved" instead of
  saving an unusable session. Use `--import-session` in that case.
* **Extract never uses the password**: `extract instagram` (also with
  `--transcribe`), `transcribe run` re-fetches and all API jobs only use the
  saved session. Without a usable one (no session file, unreadable file,
  session logged out) they stop with exit code 2 / `error_code:
  auth_required` and a message like "No password login was attempted
  (session logged out: login_required); automatic password logins are
  disabled because they trigger Instagram checkpoints. Instagram login
  required: import the session of your logged-in browser with `postparse
  check instagram --import-session` in a terminal (no password), or run
  `postparse check instagram --login` ..., then retry." Repeated scripted password logins are what makes Instagram ask for
  checkpoints, so there is no switch to turn them back on.
* **Instagram's reason**: logged-out sessions, confirmations, feed refusals
  and rate limits quote Instagram's own short reason, e.g. `(Instagram:
  checkpoint_required)`, `login_required`, `challenge_required`,
  `feedback_required`, or for a login redirect the target as
  `https://host/path`. Query strings, cookies, tokens and response bodies are
  never shown (at most 200 characters).
* **2FA**: `check instagram --login` prompts for the code in the terminal.
* **Checkpoint / "confirm it was you"**: confirm the login in the Instagram app,
  then run `postparse check instagram --import-session` (or `--login`) and
  retry the extract. Do not
  delete the session file just because a run failed.
* **"Instagram did not confirm the saved session"**: exit code 3. The session
  check (one request to `api/v1/users/<id>/info/`, a single attempt; with
  `instagram.feed_api = "web"`, the default, on `www.instagram.com` with the
  same web headers as the feed, with `"iphone"` on `i.instagram.com`, so a run
  uses one client identity and a browser session is never sent with iPad
  headers to `i.instagram.com`) was throttled (401 "Please wait a few minutes", 429) or Instagram
  was unreachable. This says nothing about the session itself, so **no password
  login is attempted** and the session file is left untouched; nothing was
  collected or lost. Wait a few hours and retry. Even `check instagram
  --login` only logs in with the password when the check positively says the
  session is logged out (login redirect, `login_required`, session of another
  account, no `sessionid` cookie) or when there is no session file; a
  throttled check never leads to a password login. Do not delete a session
  file just because of this message.
* **Session outcome on the console**: every `extract instagram` run prints
  "Instagram session verified (no password login)" or stops with exit code 2
  and the reason. `check instagram --login` prints the warning "No usable
  Instagram session (<reason>); logging in with the password now ..." before
  a password login, so it is never silent.
* **"Instagram refused the saved feed ... something went wrong"**: exit code 3
  (`stopped_reason` / job `error_code` `feed_unavailable`). The session check
  passed, so the session is fine and no password login is attempted; Instagram
  answered the feed request (`api/v1/feed/saved/posts/`) with HTTP 200 and
  `"status": "fail"`. Everything committed before is kept. Feed pages get a
  single attempt (only network errors such as timeouts are retried, up to
  `instagram.max_connection_attempts`), so a refusal costs one request. The
  answer depends on how the feed is requested, so the API is configurable:
  `instagram.feed_api = "web"` (default) requests
  `https://www.instagram.com/api/v1/feed/saved/posts/` with the web app's
  headers (`X-IG-App-ID`, `X-CSRFToken` from the session cookie,
  `X-Requested-With`, `X-ASBD-ID`, `X-IG-WWW-Claim`, the saved page as
  `Referer`), which fits a session created on the website; `"iphone"` uses
  the private API on `i.instagram.com` with instaloader's iPad headers. If one
  keeps failing, switch to the other in `config/config.toml` and retry once;
  if both fail, wait a few hours.
* **Rate limit (429) / soft block**: exit code 3. Instagram sometimes answers a
  soft-blocked session with errors that look like deleted posts; the
  transcription circuit breaker stops after
  `transcription.max_consecutive_refetch_failures` such failures. Wait several
  hours (better until the next day), keep batches small, and do not run several
  Instagram jobs in parallel. Larger `instagram.default_min_delay` /
  `default_max_delay` and `transcription.refetch_*_delay` values reduce the risk.

### LLM unreachable

* `postparse check llm` lists the models of each provider and sends a chat ping
  (`--provider NAME`, `--timeout 30`).
* Check `api_base` (llama.cpp: `http://<host>:<port>/v1`), that the server is
  running and that a model is loaded; `discover_model` asks the server which
  model it serves.
* Cloud providers need `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`.
* The API answers 503 `LLM_PROVIDER_ERROR`; jobs fail with `llm_error`;
  `GET /health/ready` shows the provider status.
* Slow local models: increase the provider `timeout`; keep `max_concurrency = 1`
  for a single llama.cpp slot.

### CUDA fallback

* The warnings "CUDA initialisation failed (...); falling back to the CPU" and
  "CUDA inference failed (...); retrying on the CPU" mean faster-whisper could
  not use the GPU; transcription continues on the CPU (slower).
* `postparse check transcription --load-model` shows the CUDA device count and
  loads the model.
* Make sure the `asr` extra is installed (`uv sync --extra asr`, it brings the
  cuBLAS / cuDNN 9 wheels) and the NVIDIA driver is current. A system CUDA
  toolkit is not needed; conflicting older cuDNN DLLs on `PATH` can break loading.
* Force a device with `[transcription.local] device = "cpu"` or `"cuda"`.

### Database

* `postparse db check` reports integrity, foreign-key and index problems;
  `postparse db reindex` rebuilds the search index.
* "schema v1 setting ... ignored": remove `default_db_path` / `path` from
  `[database]` (use `db_path`).
* `database is locked`: another process is writing; connections wait 5 s.
  Avoid running two write commands at the same time.
