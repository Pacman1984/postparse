-- PostParse schema v2, initial version.
--
-- Conventions:
--   * All tables are STRICT.
--   * Every timestamp is UTC text 'YYYY-MM-DDTHH:MM:SS.sssZ' (see core/timeutil.py),
--     enforced by CHECK constraints; defaults use strftime('%Y-%m-%dT%H:%M:%fZ','now').
--   * JSON columns are TEXT guarded by json_valid().
--   * One statement per line-terminated ';' (the migration runner splits on
--     complete statements; trigger bodies are handled correctly).

-- ---------------------------------------------------------------------------
-- Items (one row per collected post/message, any source)
-- ---------------------------------------------------------------------------
CREATE TABLE items (
    id            INTEGER PRIMARY KEY,
    source        TEXT NOT NULL CHECK (source IN ('instagram', 'telegram')),
    external_id   TEXT NOT NULL,
    kind          TEXT NOT NULL
                  CHECK (kind IN ('text', 'image', 'video', 'carousel', 'document', 'audio', 'other')),
    text          TEXT,
    author        TEXT,
    url           TEXT,
    created_at    TEXT
                  CHECK (created_at IS NULL OR created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'),
    collected_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                  CHECK (collected_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                  CHECK (updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'),
    sort_at       TEXT GENERATED ALWAYS AS (coalesce(created_at, collected_at)) VIRTUAL,
    UNIQUE (source, external_id)
) STRICT;

CREATE INDEX items_source_sort ON items (source, sort_at DESC, id DESC);
CREATE INDEX items_sort ON items (sort_at DESC, id DESC);
CREATE INDEX items_author ON items (author);
CREATE INDEX items_kind ON items (kind);

CREATE TABLE instagram_posts (
    item_id          INTEGER PRIMARY KEY REFERENCES items (id) ON DELETE CASCADE,
    shortcode        TEXT NOT NULL UNIQUE,
    owner_id         INTEGER,
    typename         TEXT,
    likes            INTEGER,
    comments         INTEGER,
    saved_feed_rank  INTEGER
) STRICT;

CREATE TABLE telegram_messages (
    item_id           INTEGER PRIMARY KEY REFERENCES items (id) ON DELETE CASCADE,
    chat_id           INTEGER NOT NULL,
    message_id        INTEGER NOT NULL,
    views             INTEGER,
    forwards          INTEGER,
    reply_to_msg_id   INTEGER,
    fwd_from_name     TEXT,
    fwd_from_id       INTEGER,
    fwd_from_post_id  INTEGER,
    UNIQUE (chat_id, message_id)
) STRICT;

-- ---------------------------------------------------------------------------
-- Tags (hashtags and mentions)
-- ---------------------------------------------------------------------------
CREATE TABLE tags (
    id    INTEGER PRIMARY KEY,
    kind  TEXT NOT NULL CHECK (kind IN ('hashtag', 'mention')),
    name  TEXT NOT NULL COLLATE NOCASE,
    UNIQUE (kind, name)
) STRICT;

CREATE TABLE item_tags (
    item_id  INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags (id),
    PRIMARY KEY (item_id, tag_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX item_tags_tag ON item_tags (tag_id, item_id);

-- ---------------------------------------------------------------------------
-- Media and transcripts
-- ---------------------------------------------------------------------------
CREATE TABLE media (
    id                  INTEGER PRIMARY KEY,
    item_id             INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    position            INTEGER NOT NULL DEFAULT 0,
    media_type          TEXT NOT NULL CHECK (media_type IN ('image', 'video', 'audio', 'document', 'other')),
    local_path          TEXT UNIQUE,  -- POSIX path relative to Settings.downloads_dir
    remote_url          TEXT,
    remote_url_seen_at  TEXT
                        CHECK (remote_url_seen_at IS NULL OR remote_url_seen_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'),
    mime                TEXT,
    size_bytes          INTEGER,
    duration_s          REAL,
    sha256              TEXT,
    transcript_status   TEXT NOT NULL DEFAULT 'none'
                        CHECK (transcript_status IN ('none', 'pending', 'transcribed', 'no_audio', 'failed', 'skipped')),
    attempts            INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,
    next_attempt_at     TEXT
                        CHECK (next_attempt_at IS NULL OR next_attempt_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                        CHECK (updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'),
    UNIQUE (item_id, position)
) STRICT;

CREATE INDEX media_transcript_queue ON media (transcript_status, next_attempt_at)
    WHERE transcript_status IN ('pending', 'failed');

CREATE TABLE transcripts (
    id          INTEGER PRIMARY KEY,
    media_id    INTEGER NOT NULL REFERENCES media (id) ON DELETE CASCADE,
    backend     TEXT NOT NULL,
    model       TEXT NOT NULL,
    language    TEXT,
    text        TEXT NOT NULL,
    segments    TEXT CHECK (segments IS NULL OR json_valid(segments)),
    duration_s  REAL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'),
    UNIQUE (media_id, backend, model)
) STRICT;

-- ---------------------------------------------------------------------------
-- Summaries
-- ---------------------------------------------------------------------------
CREATE TABLE summaries (
    id             INTEGER PRIMARY KEY,
    item_id        INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    provider       TEXT,
    model          TEXT,
    prompt_sha256  TEXT,
    text           TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                   CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z')
) STRICT;

CREATE INDEX summaries_item ON summaries (item_id, id DESC);

-- ---------------------------------------------------------------------------
-- Links and link enrichment
-- ---------------------------------------------------------------------------
CREATE TABLE links (
    id      INTEGER PRIMARY KEY,
    url     TEXT NOT NULL UNIQUE,  -- normalized, see core/urls.py
    domain  TEXT NOT NULL
) STRICT;

CREATE TABLE item_links (
    item_id   INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    link_id   INTEGER NOT NULL REFERENCES links (id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    PRIMARY KEY (item_id, link_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX item_links_link ON item_links (link_id);

CREATE TABLE link_fetches (
    id           INTEGER PRIMARY KEY,
    link_id      INTEGER NOT NULL REFERENCES links (id) ON DELETE CASCADE,
    fetcher      TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('ok', 'error', 'skipped')),
    http_status  INTEGER,
    title        TEXT,
    text         TEXT,
    metadata     TEXT CHECK (metadata IS NULL OR json_valid(metadata)),
    error        TEXT,
    fetched_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                 CHECK (fetched_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z')
) STRICT;

CREATE INDEX link_fetches_link ON link_fetches (link_id, fetched_at DESC);

-- Text produced by the v1 "expanded text" enrichment, kept for search only.
CREATE TABLE legacy_expanded_text (
    item_id  INTEGER PRIMARY KEY REFERENCES items (id) ON DELETE CASCADE,
    text     TEXT NOT NULL
) STRICT;

-- ---------------------------------------------------------------------------
-- Classification (generic taxonomies)
-- ---------------------------------------------------------------------------
CREATE TABLE taxonomies (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL UNIQUE,
    mode              TEXT NOT NULL CHECK (mode IN ('single', 'multi')),
    version           INTEGER NOT NULL DEFAULT 1,
    labels            TEXT NOT NULL CHECK (json_valid(labels)),  -- [{"name": ..., "description": ...}]
    label_set_sha256  TEXT NOT NULL,
    is_legacy         INTEGER NOT NULL DEFAULT 0 CHECK (is_legacy IN (0, 1)),
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                      CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                      CHECK (updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z')
) STRICT;

CREATE TABLE classification_runs (
    id                INTEGER PRIMARY KEY,
    taxonomy_id       INTEGER NOT NULL REFERENCES taxonomies (id),
    provider          TEXT,
    model             TEXT,
    label_set_sha256  TEXT,
    prompt_sha256     TEXT,
    params            TEXT CHECK (params IS NULL OR json_valid(params)),
    status            TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed', 'legacy')),
    started_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                      CHECK (started_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'),
    finished_at       TEXT
                      CHECK (finished_at IS NULL OR finished_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'),
    n_ok              INTEGER NOT NULL DEFAULT 0,
    n_failed          INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE INDEX classification_runs_taxonomy ON classification_runs (taxonomy_id);

CREATE TABLE classification_results (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES classification_runs (id) ON DELETE CASCADE,
    item_id      INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    taxonomy_id  INTEGER NOT NULL REFERENCES taxonomies (id),
    status       TEXT NOT NULL CHECK (status IN ('ok', 'no_labels', 'error')),
    confidence   REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    reasoning    TEXT,
    details      TEXT CHECK (details IS NULL OR json_valid(details)),
    error        TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                 CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'),
    UNIQUE (run_id, item_id)
) STRICT;

CREATE INDEX classification_results_current ON classification_results (taxonomy_id, item_id, id DESC);
CREATE INDEX classification_results_item ON classification_results (item_id);

CREATE TABLE result_labels (
    result_id   INTEGER NOT NULL REFERENCES classification_results (id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    confidence  REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    PRIMARY KEY (result_id, label)
) STRICT, WITHOUT ROWID;

CREATE INDEX result_labels_label ON result_labels (label, result_id);

-- Newest successful result (ok / no_labels) per (item, taxonomy). Errors never count.
CREATE VIEW v_current_classification AS
SELECT cr.id AS result_id,
       cr.run_id,
       cr.item_id,
       cr.taxonomy_id,
       cr.status,
       cr.confidence,
       cr.reasoning,
       cr.details,
       cr.created_at
FROM classification_results AS cr
WHERE cr.status IN ('ok', 'no_labels')
  AND cr.id = (
      SELECT max(cr2.id)
      FROM classification_results AS cr2
      WHERE cr2.taxonomy_id = cr.taxonomy_id
        AND cr2.item_id = cr.item_id
        AND cr2.status IN ('ok', 'no_labels')
  );

-- ---------------------------------------------------------------------------
-- Full-text search: search_docs is the content table, items_fts indexes it.
-- Rows are written by SearchRepo.refresh() (INSERT ... ON CONFLICT DO UPDATE).
-- ---------------------------------------------------------------------------
CREATE TABLE search_docs (
    item_id  INTEGER PRIMARY KEY REFERENCES items (id) ON DELETE CASCADE,
    body     TEXT,  -- item text
    extra    TEXT,  -- transcripts, latest summary, fetched link texts, legacy expanded text
    tags     TEXT   -- space-separated tag names
) STRICT;

CREATE VIRTUAL TABLE items_fts USING fts5 (
    body,
    extra,
    tags,
    content = 'search_docs',
    content_rowid = 'item_id',
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER search_docs_ai AFTER INSERT ON search_docs BEGIN
    INSERT INTO items_fts (rowid, body, extra, tags)
    VALUES (new.item_id, new.body, new.extra, new.tags);
END;

CREATE TRIGGER search_docs_ad AFTER DELETE ON search_docs BEGIN
    INSERT INTO items_fts (items_fts, rowid, body, extra, tags)
    VALUES ('delete', old.item_id, old.body, old.extra, old.tags);
END;

CREATE TRIGGER search_docs_au AFTER UPDATE ON search_docs BEGIN
    INSERT INTO items_fts (items_fts, rowid, body, extra, tags)
    VALUES ('delete', old.item_id, old.body, old.extra, old.tags);
    INSERT INTO items_fts (rowid, body, extra, tags)
    VALUES (new.item_id, new.body, new.extra, new.tags);
END;
