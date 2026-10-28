# CLI reference

This page is generated from the `--help` output of PostParse 0.2.0 (the click
command definitions); `postparse COMMAND --help` always shows the authoritative
text for your installed version.

## Global options

```text
Usage: postparse [OPTIONS] [COMMAND] [ARGS]...
```

| Option | Description |
|---|---|
| `--config PATH` | Config file (must exist); default: `./config/config.toml`, `./config.toml`, `<project root>/config/config.toml` |
| `--verbose` | Verbose output (tracebacks on errors) |
| `--quiet` | Suppress non-essential output (no welcome banner) |
| `--version` | Show the version and exit |
| `--help` | Show help and exit |

Global options go **before** the command: `postparse --config my.toml stats`.
Running `postparse` without a command shows a welcome banner.

| Group | Commands |
|---|---|
| Core | [`stats`](#postparse-stats), [`info`](#postparse-info), [`check`](#postparse-check), [`search`](#postparse-search) |
| Data operations | [`extract`](#postparse-extract), [`classify`](#postparse-classify), [`transcribe`](#postparse-transcribe), [`summarize`](#postparse-summarize), [`enrich`](#postparse-enrich) |
| System | [`serve`](#postparse-serve), [`db`](#postparse-db), [`config`](#postparse-config) |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | error (also: a failed check in `config validate` / `check` / `db check`, ASR backend unavailable) |
| `2` | login required (`extract`, `transcribe run`: Telegram/Instagram session invalid or 2FA needed in non-interactive mode); also click usage errors |
| `3` | rate limited (Telegram FloodWait above the threshold, Instagram 429), Instagram refused the saved feed (`"fail"` status; see `instagram.feed_api`) or suspected Instagram soft block (`transcribe run`) |
| `130` | interrupted (Ctrl-C) |

`extract all` returns the most severe code of the platforms (3 > 2 > 1).

## `postparse check`

```text
Usage: postparse check [OPTIONS] [COMMAND] [ARGS]...
```

Health checks (database, transcription, sessions, LLM providers).

Without a subcommand this runs `check all`. Only `--login`,
`check instagram --import-session` and `check llm` talk to external services.

| Subcommand | Description |
|---|---|
| [`all`](#postparse-check-all) | Run all checks (no Telegram/Instagram network calls without --login). |
| [`db`](#postparse-check-db) | Database integrity, schema version and search index (= `db check`). |
| [`instagram`](#postparse-check-instagram) | Instagram session file and credentials (`--login` / `--import-session` go online). |
| [`llm`](#postparse-check-llm) | LLM providers: model list, discovered model, chat ping and latency. |
| [`telegram`](#postparse-check-telegram) | Telegram session file and credentials (`--login` verifies online). |
| [`transcription`](#postparse-check-transcription) | Transcription backend: faster-whisper / CUDA, or API endpoint reachability. |

### `postparse check all`

```text
Usage: postparse check all [OPTIONS]
```

Run all checks (no Telegram/Instagram network calls without --login).

Telegram / Instagram are reported as skipped when neither credentials nor
a session file exist.

**Examples:**

```bash
postparse check
postparse check all --login
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--login` | flag |  | Also verify Telegram/Instagram sessions online |
| `--skip-llm` | flag |  | Skip the LLM provider check |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

### `postparse check db`

```text
Usage: postparse check db [OPTIONS]
```

Database integrity, schema version and search index (= `db check`).

| Option | Type | Default | Description |
|---|---|---|---|
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

### `postparse check instagram`

```text
Usage: postparse check instagram [OPTIONS]
```

Instagram session file and credentials (`--login` / `--import-session` go online).

`--import-session` is the recommended way to log in: it takes the session
of your logged-in browser (no password login).

**Examples:**

```bash
postparse check instagram
postparse check instagram --import-session
postparse check instagram --login
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--username` | TEXT |  | Instagram username (default: INSTAGRAM_USERNAME) |
| `--session` | TEXT |  | Session file (default: &lt;sessions_dir&gt;/instagram_&lt;username&gt;) |
| `--login` | flag |  | Verify the saved session; without a usable one log in with INSTAGRAM_PASSWORD (may prompt for a 2FA code). The only command that uses the password. |
| `--import-session` | flag |  | Import the sessionid cookie of your logged-in browser (hidden prompt, no password), verify it with one request and save it. Needs a terminal. |

`--import-session` and `--login` cannot be combined (usage error, exit code
2). The import asks for the `sessionid` cookie (hidden input) and optionally
the `csrftoken` cookie (Enter generates one), makes exactly one request (the
session check: with `instagram.feed_api = "web"`, the default, the first page
of the saved feed, as the web app requests it when the saved page is opened;
with `"iphone"` the user info on `i.instagram.com`) and saves the session file
only when Instagram confirms the session; otherwise nothing is saved (exit
code 1).
See [Operations](operations.md#instagram-logging-in-checkpoint-2fa-soft-block).

### `postparse check llm`

```text
Usage: postparse check llm [OPTIONS]
```

LLM providers: model list, discovered model, chat ping and latency.

**Examples:**

```bash
postparse check llm
postparse check llm --provider llama_cpp --timeout 30
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--provider` | TEXT |  | Check only this provider (default: all configured) |
| `--no-chat` | flag |  | Only list models, skip the chat ping |
| `--timeout` | FLOAT | `10.0` | Request timeout in seconds |

### `postparse check telegram`

```text
Usage: postparse check telegram [OPTIONS]
```

Telegram session file and credentials (`--login` verifies online).

**Examples:**

```bash
postparse check telegram
postparse check telegram --login
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--session` | TEXT |  | Session name or file (default: Settings.sessions_dir) |
| `--login` | flag |  | Connect to Telegram and verify the session (may prompt for a code) |

### `postparse check transcription`

```text
Usage: postparse check transcription [OPTIONS]
```

Transcription backend: faster-whisper / CUDA, or API endpoint reachability.

**Examples:**

```bash
postparse check transcription
postparse check transcription --load-model
postparse check transcription --backend api
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--backend` | `local` \| `api` |  | Backend to check (default: transcription.backend) |
| `--load-model` | flag |  | Load the faster-whisper model (downloads it on first use) |

## `postparse classify`

```text
Usage: postparse classify [OPTIONS] COMMAND [ARGS]...
```

Classify content into taxonomies with an LLM.

Commands:

- run: classify pending database items of a taxonomy and store results
- text: classify free-form text (ad hoc, nothing is stored)
- taxonomies: list configured and stored taxonomies
- db: deprecated alias for `classify run --taxonomy topics`

| Subcommand | Description |
|---|---|
| [`db`](#postparse-classify-db) | Deprecated: use `postparse classify run --taxonomy topics`. (DEPRECATED) |
| [`run`](#postparse-classify-run) | Classify pending database items of a taxonomy and store the results. |
| [`taxonomies`](#postparse-classify-taxonomies) | List configured and stored taxonomies with versions and result counts. |
| [`text`](#postparse-classify-text) | Classify free-form text (nothing is stored). |

### `postparse classify db`

**Deprecated.**

```text
Usage: postparse classify db [OPTIONS]
```

Deprecated: use `postparse classify run --taxonomy topics`.

Maps to `classify run --taxonomy topics` (--force → --scope reprocess,
--filter-hashtag → tag filter, default limit 1000).

| Option | Type | Default | Description |
|---|---|---|---|
| `--source` | `all` \| `instagram` \| `telegram` |  | Database source to classify (default: all) |
| `--classifier` | `recipe` \| `multiclass` \| `multilabel` |  | Ignored (the generic 'topics' taxonomy is used) |
| `--classes` | TEXT |  | Ignored (configure [[classification.taxonomies]] instead) |
| `--limit` | INTEGER (1..) |  | Maximum items sent to the LLM (default: 1000) |
| `--filter-hashtag` | TEXT |  | Only items with this hashtag |
| `--provider` | TEXT |  | LLM provider to use (default: from config) |
| `--force` | flag |  | Reprocess already classified items |
| `--replace` | flag |  | Ignored (results are versioned) |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

### `postparse classify run`

```text
Usage: postparse classify run [OPTIONS]
```

Classify pending database items of a taxonomy and store the results.

Old posts are never re-classified automatically: the default scope only
picks items collected after the taxonomy was created and items without
any classification. Use --backfill / --reprocess explicitly for the rest.

**Examples:**

```bash
postparse classify run --taxonomy topics --limit 100
postparse classify run -t topics --backfill --source instagram --since 2024-01-01
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--taxonomy`, `-t` | TEXT | `topics` | Taxonomy to classify into (see `classify taxonomies`) |
| `--source` | `all` \| `instagram` \| `telegram` | `all` | Restrict to one source |
| `--scope` | `default` \| `backfill` \| `reprocess` | `default` | default: new + never classified items; backfill: everything not yet classified for the current label set; reprocess: everything matching |
| `--backfill` | flag |  | Alias for --scope backfill |
| `--reprocess` | flag |  | Alias for --scope reprocess |
| `--with-transcript` | flag |  | Only items that have a transcript |
| `--since` | TEXT |  | Only items dated on/after DATE (YYYY-MM-DD) |
| `--limit` | INTEGER (1..) |  | Maximum items sent to the LLM |
| `--provider` | TEXT |  | LLM provider from [[llm.providers]] (default: default_provider) |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |
| `--no-wait-transcripts` | flag |  | Also classify items whose video transcripts are still pending |

### `postparse classify taxonomies`

```text
Usage: postparse classify taxonomies [OPTIONS]
```

List configured and stored taxonomies with versions and result counts.

| Option | Type | Default | Description |
|---|---|---|---|
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |
| `--output` | `text` \| `json` | `text` | Output format |

### `postparse classify text`

```text
Usage: postparse classify text [OPTIONS] [CONTENT]
```

Classify free-form text (nothing is stored).

**Examples:**

```bash
postparse classify text "Spaghetti Carbonara: Guanciale, Eigelb" --labels recipe,travel
postparse classify text "New FastAPI release" --labels recipe,tech --mode single
echo "Some text" | postparse classify text - --taxonomy topics --output json
```

| Option | Type | Default | Description |
|---|---|---|---|
| `CONTENT` (argument) | TEXT |  |  |
| `--taxonomy`, `-t` | TEXT |  | Configured taxonomy (default: topics) |
| `--labels` | TEXT |  | Ad-hoc labels, comma separated (e.g. recipe,travel,tech) |
| `--mode` | `single` \| `multi` | `multi` | Mode for --labels |
| `--provider` | TEXT |  | LLM provider from [[llm.providers]] (default: default_provider) |
| `--output` | `text` \| `json` | `text` | Output format |

## `postparse config`

```text
Usage: postparse config [OPTIONS] COMMAND [ARGS]...
```

View and validate configuration.

| Subcommand | Description |
|---|---|
| [`env`](#postparse-config-env) | List expected environment variables and whether they are set (never values). |
| [`show`](#postparse-config-show) | Display resolved paths and configuration (secrets masked). |
| [`validate`](#postparse-config-validate) | Validate configuration, paths and feature settings. |

### `postparse config env`

```text
Usage: postparse config env [OPTIONS]
```

List expected environment variables and whether they are set (never values).

### `postparse config show`

```text
Usage: postparse config show [OPTIONS]
```

Display resolved paths and configuration (secrets masked).

**Examples:**

```bash
postparse config show
postparse config show --section transcription --format json
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--section` | `paths` \| `database` \| `llm` \| `api` \| `telegram` \| `instagram` \| `transcription` \| `summarization` \| `enrichment` \| `classification` |  | Show one section |
| `--format` | `text` \| `json` |  | Output format |

### `postparse config validate`

```text
Usage: postparse config validate [OPTIONS]
```

Validate configuration, paths and feature settings.

Exit code 1 when a check fails (warnings are allowed).

| Option | Type | Default | Description |
|---|---|---|---|
| `--fix` | flag |  | Create missing data directories |

## `postparse db`

```text
Usage: postparse db [OPTIONS] COMMAND [ARGS]...
```

Database statistics, exports and maintenance (schema v2).

| Subcommand | Description |
|---|---|
| [`check`](#postparse-db-check) | Verify integrity, foreign keys, schema version and the search index. |
| [`export`](#postparse-db-export) | Export items to a JSON array or a CSV file (`-` writes to stdout). |
| [`migrate`](#postparse-db-migrate) | Apply pending schema v2 migrations (creates the database if needed). |
| [`migrate-v1`](#postparse-db-migrate-v1) | Migrate a schema v1 database into a new schema v2 database. |
| [`reindex`](#postparse-db-reindex) | Rebuild all search documents and optimize the full-text index. |
| [`stats`](#postparse-db-stats) | Show database statistics (counts, queues, coverage, size). |

### `postparse db check`

```text
Usage: postparse db check [OPTIONS]
```

Verify integrity, foreign keys, schema version and the search index.

| Option | Type | Default | Description |
|---|---|---|---|
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

### `postparse db export`

```text
Usage: postparse db export [OPTIONS] OUTPUT
```

Export items to a JSON array or a CSV file (`-` writes to stdout).

One row per item with tags and current labels; filters as in `search items`.

**Examples:**

```bash
postparse db export items.json
postparse db export posts.csv --source posts
postparse db export recipes.json --label topics:recipe --from 2024-01-01
postparse db export - --format csv --tag pasta --limit 100
```

| Option | Type | Default | Description |
|---|---|---|---|
| `OUTPUT` (argument, required) | FILE |  |  |
| `--format` | `json` \| `csv` |  | Export format (default: from the file extension, else json) |
| `--source` | `all` \| `instagram` \| `messages` \| `posts` \| `telegram` | `all` | What to export (posts = instagram, messages = telegram) |
| `--query`, `-q` | TEXT |  | Full-text query |
| `--tag`, `--hashtag` | TEXT |  | Tag filter, repeatable (any of): #hashtag, @mention or name |
| `--author` | TEXT |  | Author / owner filter, repeatable (any of) |
| `--kind` | `text` \| `image` \| `video` \| `carousel` \| `document` \| `audio` \| `other` |  | Item kind, repeatable (any of) |
| `--label` | TAXONOMY[:LABEL] |  | Current classification label, repeatable (same taxonomy, any label); a bare taxonomy matches any classified item |
| `--from` | YYYY-MM-DD |  | Items on or after this day (UTC) |
| `--to` | YYYY-MM-DD |  | Items on or before this day (UTC) |
| `--has-transcript/--no-transcript` | flag | `--no-transcript` | Only items with / without a video transcript |
| `--limit` | INTEGER (1..) |  | Maximum number of items (newest first) |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

### `postparse db migrate`

```text
Usage: postparse db migrate [OPTIONS]
```

Apply pending schema v2 migrations (creates the database if needed).

| Option | Type | Default | Description |
|---|---|---|---|
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

### `postparse db migrate-v1`

```text
Usage: postparse db migrate-v1 [OPTIONS]
```

Migrate a schema v1 database into a new schema v2 database.

| Option | Type | Default | Description |
|---|---|---|---|
| `--source` (required) | FILE |  | Schema v1 database (read-only) |
| `--target` (required) | FILE |  | Schema v2 database to create |
| `--downloads-dir` | DIRECTORY |  | Media folder the v1 paths refer to (default: Settings.downloads_dir) |
| `--report` | FILE |  | Write the JSON report to this file |
| `--instagram-tz` | TEXT | `Europe/Berlin` | Time zone of the naive v1 Instagram timestamps |
| `--overwrite` | flag |  | Replace an existing target database |

### `postparse db reindex`

```text
Usage: postparse db reindex [OPTIONS]
```

Rebuild all search documents and optimize the full-text index.

| Option | Type | Default | Description |
|---|---|---|---|
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

### `postparse db stats`

```text
Usage: postparse db stats [OPTIONS]
```

Show database statistics (counts, queues, coverage, size).

**Examples:**

```bash
postparse stats
postparse db stats --detailed --top 20
postparse stats --json
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--detailed` | flag |  | Also list top hashtags and mentions |
| `--top` | INTEGER (1..200) | `10` | Number of tags / labels to list |
| `--no-pending` | flag |  | Skip the pending classification counts (faster on large databases) |
| `--json` | flag |  | Print JSON instead of tables |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

## `postparse enrich`

```text
Usage: postparse enrich [OPTIONS] COMMAND [ARGS]...
```

Fetch linked pages, documents, YouTube videos and X posts.

Commands:

- run: fetch due links (new, legacy v1 texts, due retries)
- status: links per fetcher/status and domain

| Subcommand | Description |
|---|---|
| [`run`](#postparse-enrich-run) | Fetch linked URLs and store their text for search. |
| [`scrape`](#postparse-enrich-scrape) | Deprecated alias of `postparse enrich run`. (DEPRECATED) |
| [`status`](#postparse-enrich-status) | Show links per fetcher/status and domain, plus due retries. |
| [`urls`](#postparse-enrich-urls) | Deprecated no-op: links are extracted automatically when items are stored. (DEPRECATED) |

### `postparse enrich run`

```text
Usage: postparse enrich run [OPTIONS]
```

Fetch linked URLs and store their text for search.

Instagram links are never fetched (skipped). Requests are throttled per
domain (enrichment.min_domain_interval) and failed links are retried with
exponential backoff on later runs.

**Examples:**

```bash
postparse enrich run --limit 200
postparse enrich run --domain youtube.com --domain youtu.be
postparse enrich run --no-legacy
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--source` | `all` \| `telegram` \| `instagram` | `all` | Only links of items from this source |
| `--limit` | INTEGER (1..) |  | Maximum links this run |
| `--force` | flag |  | Refetch every link in scope (ignores earlier results and backoff) |
| `--no-legacy` | flag |  | Do not re-enrich links whose only text was migrated from v1 |
| `--domain` | TEXT |  | Only links on this domain (repeatable, e.g. youtube.com) |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

### `postparse enrich scrape`

**Deprecated.**

```text
Usage: postparse enrich scrape [OPTIONS]
```

Deprecated alias of `postparse enrich run`.

| Option | Type | Default | Description |
|---|---|---|---|
| `--source` | `all` \| `telegram` \| `instagram` | `all` | Only links of items from this source |
| `--limit` | INTEGER (1..) |  | Maximum links this run |
| `--force` | flag |  | Refetch every link in scope (ignores earlier results and backoff) |
| `--no-legacy` | flag |  | Do not re-enrich links whose only text was migrated from v1 |
| `--domain` | TEXT |  | Only links on this domain (repeatable, e.g. youtube.com) |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

### `postparse enrich status`

```text
Usage: postparse enrich status [OPTIONS]
```

Show links per fetcher/status and domain, plus due retries.

"legacy" links only have the text migrated from v1; "never" links have
not been fetched at all.

**Examples:**

```bash
postparse enrich status
postparse enrich status --source telegram --domains 30
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--source` | `all` \| `telegram` \| `instagram` | `all` | Only links of items from this source |
| `--domains` | INTEGER (1..) | `15` | Number of domains to list |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

### `postparse enrich urls`

**Deprecated.**

```text
Usage: postparse enrich urls [OPTIONS]
```

Deprecated no-op: links are extracted automatically when items are stored.

## `postparse extract`

```text
Usage: postparse extract [OPTIONS] [COMMAND] [ARGS]...
```

Extract saved items from Telegram and Instagram (schema v2 database).

Runs 'extract all' by default if no platform is specified.

| Subcommand | Description |
|---|---|
| [`all`](#postparse-extract-all) | Extract from every platform whose credentials are configured. |
| [`instagram`](#postparse-extract-instagram) | Collect saved Instagram posts (newest first, stops at known posts). |
| [`telegram`](#postparse-extract-telegram) | Collect Telegram Saved Messages (only new ones unless --full). |

### `postparse extract all`

```text
Usage: postparse extract all [OPTIONS]
```

Extract from every platform whose credentials are configured.

Telegram runs when TELEGRAM_API_ID/TELEGRAM_API_HASH are set, Instagram
when INSTAGRAM_USERNAME is set. The exit code is the most severe one of
the platforms (3 rate limited &gt; 2 login required &gt; 1 error).

**Examples:**

```bash
postparse extract all
postparse extract all --limit 100
postparse extract
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |
| `--limit` | INTEGER (1..) |  | Maximum items per platform. |
| `--force` | flag |  | Telegram: re-read everything; Instagram: walk the whole feed. |
| `--interactive/--no-interactive` | flag | `--interactive` | Allow login prompts (Telegram code / 2FA, Instagram 2FA code) in the terminal. |

### `postparse extract instagram`

```text
Usage: postparse extract instagram [OPTIONS]
```

Collect saved Instagram posts (newest first, stops at known posts).

Uses the saved session of INSTAGRAM_USERNAME (environment or config/.env)
and never logs in with the password: without a usable session it stops
with exit code 2. Import the session of your logged-in browser with
`postparse check instagram --import-session` in a terminal (no password),
or log in with `postparse check instagram --login` (the only command that
uses INSTAGRAM_PASSWORD; it may not yield a usable session, instaloader
#2487), then retry.

**Examples:**

```bash
postparse extract instagram
postparse extract instagram --limit 50
postparse extract instagram --force
postparse extract instagram --refresh-dates --refresh-limit 100
postparse extract instagram --transcribe
```

**Note:**

```text
New posts are throttled (several seconds each). If Instagram asks for a
confirmation, confirm the login in the Instagram app, run
`postparse check instagram --import-session` (or `--login`) and retry.
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |
| `--username` | TEXT |  | Instagram username (default: INSTAGRAM_USERNAME). |
| `--session` | TEXT |  | Session file path (default: &lt;sessions_dir&gt;/instagram_&lt;username&gt;, falling back to ./instagram_session). |
| `--limit` | INTEGER (1..) |  | Maximum posts to store. |
| `--stop-after-known` | INTEGER | `20` | Stop after N consecutive already stored posts (0 = walk the whole feed). |
| `--force` | flag |  | Walk the whole saved feed and update known posts too. |
| `--batch-size` | INTEGER (1..) | `25` | Posts per database transaction. |
| `--refresh-dates` | flag |  | Afterwards re-fetch publication dates of posts migrated from schema v1. |
| `--refresh-limit` | INTEGER (1..) |  | Maximum posts for --refresh-dates (default: all unverified). |
| `--transcribe` | flag |  | Afterwards transcribe and summarize the newly collected videos (fresh URLs). |
| `--interactive/--no-interactive` | flag | `--interactive` | Allow login prompts (Telegram code / 2FA, Instagram 2FA code) in the terminal. |

### `postparse extract telegram`

```text
Usage: postparse extract telegram [OPTIONS]
```

Collect Telegram Saved Messages (only new ones unless --full).

Credentials: TELEGRAM_API_ID, TELEGRAM_API_HASH (and optionally
TELEGRAM_PHONE) from the environment or config/.env.

**Examples:**

```bash
postparse extract telegram
postparse extract telegram --limit 100
postparse extract telegram --full
```

**Note:**

```text
On the first run Telegram sends a login code (and asks for your 2FA
password if set); enter them in this terminal.
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |
| `--session` | TEXT |  | Session file path or name (default: &lt;sessions_dir&gt;/telegram.session, falling back to data/cache/telegram_session.session). |
| `--limit` | INTEGER (1..) |  | Maximum messages to process. |
| `--full` | flag |  | Re-read all saved messages and update stored ones. |
| `--force` | flag |  | Alias for --full. |
| `--interactive/--no-interactive` | flag | `--interactive` | Allow login prompts (Telegram code / 2FA, Instagram 2FA code) in the terminal. |

## `postparse info`

```text
Usage: postparse info [OPTIONS]
```

Show installation, paths and database info.

## `postparse search`

```text
Usage: postparse search [OPTIONS] COMMAND [ARGS]...
```

Search saved items (full text, tags, labels, dates).

Commands:

- items: all sources, full-text query with snippets
- posts: Instagram posts (alias of `items --source instagram`)
- messages: Telegram messages (alias of `items --source telegram`)

| Subcommand | Description |
|---|---|
| [`items`](#postparse-search-items) | Search all items; QUERY is a full-text query (words AND, "phrases", prefix*). |
| [`messages`](#postparse-search-messages) | Search Telegram messages (alias of `search items --source telegram`). |
| [`posts`](#postparse-search-posts) | Search Instagram posts (alias of `search items --source instagram`). |

### `postparse search items`

```text
Usage: postparse search items [OPTIONS] [QUERY]
```

Search all items; QUERY is a full-text query (words AND, "phrases", prefix*).

The text index covers item text, transcripts, summaries, fetched link
texts and tags. Matched terms are shown in square brackets in the snippet.

**Examples:**

```bash
postparse search items pasta
postparse search items "pasta carbonara" --source instagram --limit 5
postparse search items --tag recipe --label topics:recipe --from 2024-01-01
postparse search items rezept --has-transcript --json
```

| Option | Type | Default | Description |
|---|---|---|---|
| `QUERY` (argument) | TEXT |  |  |
| `--source` | `instagram` \| `telegram` \| `all` | `all` | Restrict to one source |
| `--tag`, `--hashtag` | TEXT |  | Tag filter, repeatable (any of): #hashtag, @mention or name |
| `--author` | TEXT |  | Author / owner filter, repeatable (any of) |
| `--kind` | `text` \| `image` \| `video` \| `carousel` \| `document` \| `audio` \| `other` |  | Item kind, repeatable (any of) |
| `--label` | TAXONOMY[:LABEL] |  | Current classification label, repeatable (same taxonomy, any label); a bare taxonomy matches any classified item |
| `--from` | YYYY-MM-DD |  | Items on or after this day (UTC) |
| `--to` | YYYY-MM-DD |  | Items on or before this day (UTC) |
| `--has-transcript/--no-transcript` | flag | `--no-transcript` | Only items with / without a video transcript |
| `--limit` | INTEGER | `20` | Page size (1-500) |
| `--cursor` | TEXT |  | Continue after a previous page (printed next cursor) |
| `--json` | flag |  | Print JSON instead of a table |
| `--output` | `table` \| `json` |  | Output format (same as --json when 'json') |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

### `postparse search messages`

```text
Usage: postparse search messages [OPTIONS] [QUERY]
```

Search Telegram messages (alias of `search items --source telegram`).

**Examples:**

```bash
postparse search messages --hashtag recipe
postparse search messages --type photo --from 2024-01-01
postparse search messages python --output json
```

| Option | Type | Default | Description |
|---|---|---|---|
| `QUERY` (argument) | TEXT |  |  |
| `--type` | `audio` \| `document` \| `image` \| `photo` \| `text` \| `video` |  | Message type (photo = image; same as --kind) |
| `--tag`, `--hashtag` | TEXT |  | Tag filter, repeatable (any of): #hashtag, @mention or name |
| `--author` | TEXT |  | Author / owner filter, repeatable (any of) |
| `--kind` | `text` \| `image` \| `video` \| `carousel` \| `document` \| `audio` \| `other` |  | Item kind, repeatable (any of) |
| `--label` | TAXONOMY[:LABEL] |  | Current classification label, repeatable (same taxonomy, any label); a bare taxonomy matches any classified item |
| `--from` | YYYY-MM-DD |  | Items on or after this day (UTC) |
| `--to` | YYYY-MM-DD |  | Items on or before this day (UTC) |
| `--has-transcript/--no-transcript` | flag | `--no-transcript` | Only items with / without a video transcript |
| `--limit` | INTEGER | `20` | Page size (1-500) |
| `--cursor` | TEXT |  | Continue after a previous page (printed next cursor) |
| `--json` | flag |  | Print JSON instead of a table |
| `--output` | `table` \| `json` |  | Output format (same as --json when 'json') |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

### `postparse search posts`

```text
Usage: postparse search posts [OPTIONS] [QUERY]
```

Search Instagram posts (alias of `search items --source instagram`).

**Examples:**

```bash
postparse search posts --hashtag recipe
postparse search posts --hashtag recipe --hashtag cooking --type video
postparse search posts --from 2024-01-01 --to 2024-12-31 --limit 100
postparse search posts --username myuser --output json
```

| Option | Type | Default | Description |
|---|---|---|---|
| `QUERY` (argument) | TEXT |  |  |
| `--type` | `carousel` \| `image` \| `video` |  | Post type (same as --kind) |
| `--tag`, `--hashtag` | TEXT |  | Tag filter, repeatable (any of): #hashtag, @mention or name |
| `--author`, `--username`, `--owner` | TEXT |  | Author / owner filter, repeatable (any of) |
| `--kind` | `text` \| `image` \| `video` \| `carousel` \| `document` \| `audio` \| `other` |  | Item kind, repeatable (any of) |
| `--label` | TAXONOMY[:LABEL] |  | Current classification label, repeatable (same taxonomy, any label); a bare taxonomy matches any classified item |
| `--from` | YYYY-MM-DD |  | Items on or after this day (UTC) |
| `--to` | YYYY-MM-DD |  | Items on or before this day (UTC) |
| `--has-transcript/--no-transcript` | flag | `--no-transcript` | Only items with / without a video transcript |
| `--limit` | INTEGER | `20` | Page size (1-500) |
| `--cursor` | TEXT |  | Continue after a previous page (printed next cursor) |
| `--json` | flag |  | Print JSON instead of a table |
| `--output` | `table` \| `json` |  | Output format (same as --json when 'json') |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

## `postparse serve`

```text
Usage: postparse serve [OPTIONS]
```

Start the FastAPI server.

This command starts the FastAPI server using Uvicorn. The server provides
REST API endpoints for extraction, classification, and search operations.

**Examples:**

```bash
postparse serve
```

    postparse serve --port 8080 --reload

    postparse serve --workers 4 --log-level debug

**The API will be available at:**

```text
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
```

**Note:**

```text
Use --reload for development. For production, use multiple workers
without reload for better performance.
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--host` | TEXT |  | Host to bind |
| `--port` | INTEGER |  | Port to bind |
| `--reload` | flag |  | Enable auto-reload |
| `--workers` | INTEGER |  | Number of workers |
| `--log-level` | `debug` \| `info` \| `warning` \| `error` |  | Log level |

## `postparse stats`

```text
Usage: postparse stats [OPTIONS]
```

Show database statistics (counts, queues, coverage, size).

**Examples:**

```bash
postparse stats
postparse db stats --detailed --top 20
postparse stats --json
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--detailed` | flag |  | Also list top hashtags and mentions |
| `--top` | INTEGER (1..200) | `10` | Number of tags / labels to list |
| `--no-pending` | flag |  | Skip the pending classification counts (faster on large databases) |
| `--json` | flag |  | Print JSON instead of tables |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

## `postparse summarize`

```text
Usage: postparse summarize [OPTIONS] COMMAND [ARGS]...
```

Summarize transcribed items with an LLM.

Commands:

- run: summarize items whose transcript is newer than their summary

| Subcommand | Description |
|---|---|
| [`run`](#postparse-summarize-run) | Summarize items with a transcript and no summary newer than it. |

### `postparse summarize run`

```text
Usage: postparse summarize run [OPTIONS]
```

Summarize items with a transcript and no summary newer than it.

**Examples:**

```bash
postparse summarize run --limit 20
postparse summarize run --provider llama_cpp
postparse summarize run --force --item 42
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--limit` | INTEGER (1..) |  | Maximum items |
| `--provider` | TEXT |  | LLM provider (default: summarization.provider or llm default) |
| `--force` | flag |  | Re-summarize items that already have a summary |
| `--item` | INTEGER |  | Only this item (repeatable) |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

## `postparse transcribe`

```text
Usage: postparse transcribe [OPTIONS] COMMAND [ARGS]...
```

Transcribe saved videos (local faster-whisper or an OpenAI-compatible API).

Commands:

- run: work through the transcription queue
- status: queue counts, next retries and totals

| Subcommand | Description |
|---|---|
| [`run`](#postparse-transcribe-run) | Transcribe pending videos and store transcripts (no media files are kept). |
| [`status`](#postparse-transcribe-status) | Show the transcription queue per source and status. |

### `postparse transcribe run`

```text
Usage: postparse transcribe run [OPTIONS]
```

Transcribe pending videos and store transcripts (no media files are kept).

Videos whose stored URL is older than transcription.remote_url_max_age_hours
are re-fetched from Instagram (throttled, 20-60 s apart). A rate limit or an
invalid session stops the run cleanly; rerun later to continue.

**Examples:**

```bash
postparse transcribe run --limit 50
postparse transcribe run --backend api
postparse transcribe run --item 42
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--source` | `instagram` \| `telegram` \| `all` | `instagram` | Restrict to one source |
| `--limit` | INTEGER (1..) |  | Maximum media this run (default: transcription.limit = 50) |
| `--backend` | `local` \| `api` |  | ASR backend (default: transcription.backend) |
| `--no-refetch` | flag |  | Never re-fetch Instagram posts; media without a fresh URL stay pending |
| `--item` | INTEGER |  | Only media of this item id (repeatable; ignores retry backoff) |
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |
| `--interactive/--no-interactive` | flag | `--no-interactive` | Allow an Instagram 2FA prompt if a re-fetch needs a new login |

### `postparse transcribe status`

```text
Usage: postparse transcribe status [OPTIONS]
```

Show the transcription queue per source and status.

**Examples:**

```bash
postparse transcribe status
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--db` | FILE |  | Schema v2 database file (default: Settings.db_path) |

