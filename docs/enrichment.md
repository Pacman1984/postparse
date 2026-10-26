# Link enrichment

Saved posts often only *point* at the interesting content: an article, a PDF, a
YouTube video, an X post. `postparse enrich run` fetches every linked URL once and
stores its text, so the linked content becomes searchable and is part of the
summary and classification input.

## How links get into the database

Links are extracted automatically whenever an item is stored (collector,
v1 migration): URLs in the item text are normalized (`core/urls.py`) and written
to `links` / `item_links`. There is no separate extraction step (`enrich urls`
is a deprecated no-op).

## Fetchers

`FetchRouter` picks the first fetcher that accepts a link; the generic fetcher
handles the rest.

| Fetcher | Links | What is stored |
|---|---|---|
| `instagram` | Instagram URLs | nothing: recorded as `skipped` without a request (Instagram content is only collected by the logged-in, throttled collector) |
| `youtube` | video URLs (`watch?v=`, `youtu.be/`, `/shorts/`, `/embed/`, `/live/`) | title and channel via **oEmbed**; description, upload date, duration, tags, chapters via **yt-dlp** (optional extra `youtube`); a transcript via **youtube-transcript-api** preferring `transcript_languages` (`de`, `en`), falling back to any language. `ok` when at least a title was found. |
| `x` | X / Twitter post URLs | post text, author, media and quoted post via the **fxtwitter** JSON API (no login); `publish.twitter.com` oEmbed as fallback. Non-post X URLs (profiles, searches) are `skipped`. |
| `document` | URLs ending in a document extension, or responses with a PDF/Office content type | markdown text via **markitdown** (PDF, DOCX, PPTX, XLSX), run in a worker thread with plugins disabled |
| `generic` | everything else | HTML main text via **trafilatura** (with title, author, date, site name, description); **readability-lxml** as well when trafilatura finds less than `min_text_chars`, the longer text wins. `text/plain` / `text/markdown` stored as-is; other content types (images, video, JSON) `skipped`. |

Non-video YouTube URLs (channels, playlists) go to the generic fetcher. Without
the `youtube` extra (`uv sync --extra youtube`, pinned `yt-dlp`) YouTube links
still get oEmbed data and transcripts.

## Politeness and limits

* An honest User-Agent: `postparse/<version> (+project URL)` unless
  `enrichment.user_agent` is set.
* At most `concurrency` (4) links in flight; at least `min_domain_interval`
  (1 s) between two requests to the same domain. The queue is interleaved across
  domains so one slow domain does not block the others.
* Per request timeout `timeout` (15 s), total time per link 4× the timeout.
* Bodies larger than `max_body_mb` (5) — `max_document_mb` (20) for documents —
  are skipped; stored text is cut to `max_text_chars` (20000).

## Selection and retries

Without `--force`, a run selects:

1. links that were **never fetched**;
2. **legacy** links whose only text was imported from schema v1 (fetcher
   `legacy_v1`), so they are re-enriched with the new stack (`--no-legacy` leaves
   them alone). The legacy text stays as fallback; search uses the newest `ok`
   fetch;
3. links whose newest fetch **failed** and whose retry is due: exponential
   backoff from the last attempt (`backoff_minutes` 60, doubling, capped at
   `max_backoff_hours` 168), giving up after `max_attempts` (4) failures in a row.

Links whose newest fetch is `ok` or `skipped` are never refetched automatically.
`--force` refetches every link in scope, ignoring earlier results and backoff.
Each result is stored in its own transaction and the search documents of the
linking items are refreshed. When all links of an item have a fresh result, the
item's v1 `legacy_expanded_text` is deleted.

```bash
postparse enrich run --limit 200
postparse enrich run --source telegram
postparse enrich run --domain youtube.com --domain youtu.be
postparse enrich run --no-legacy
postparse enrich status                       # per fetcher/status, top domains, due retries
postparse enrich status --source telegram --domains 30
```

Exit codes of `enrich run`: `0` success, `1` error, `130` interrupted.

The API equivalents are `POST /api/v1/enrichment/run` (job) and
`GET /api/v1/enrichment/status`.

## Configuration

`[enrichment]` keys and defaults are listed in
[`config/config.example.toml`](https://github.com/Pacman1984/postparse/blob/master/config/config.example.toml);
`postparse config show --section enrichment` prints the effective values.
