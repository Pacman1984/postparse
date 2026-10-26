-- Schema v1 DDL (the legacy v1 database class, removed in WP8c).
--
-- Copied verbatim from its __create_tables method, including the columns
-- older databases received through ALTER TABLE. Used by tests that build v1 fixture
-- databases for the v1 -> v2 migration (postparse.core.db.legacy_v1).

CREATE TABLE IF NOT EXISTS instagram_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shortcode TEXT NOT NULL UNIQUE,
    post_url TEXT NOT NULL,  -- Full URL to post
    owner_username TEXT,
    owner_id INTEGER,
    caption TEXT,
    is_video BOOLEAN,
    media_url TEXT,  -- URL to media content
    typename TEXT,  -- Type of post (GraphImage, GraphVideo, etc)
    likes INTEGER,
    comments INTEGER,
    is_saved BOOLEAN NOT NULL DEFAULT 0,  -- Whether this is a saved post
    source TEXT NOT NULL DEFAULT 'saved',  -- Where this post was found (saved, profile, hashtag, etc)
    created_at TIMESTAMP,  -- When the post was created on Instagram
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- When we fetched the post
);

CREATE TABLE IF NOT EXISTS instagram_hashtags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER,
    hashtag TEXT NOT NULL,
    FOREIGN KEY(post_id) REFERENCES instagram_posts(id),
    UNIQUE(post_id, hashtag)
);

CREATE TABLE IF NOT EXISTS instagram_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER,
    username TEXT NOT NULL,
    FOREIGN KEY(post_id) REFERENCES instagram_posts(id),
    UNIQUE(post_id, username)
);

CREATE TABLE IF NOT EXISTS telegram_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL UNIQUE,
    chat_id INTEGER,
    content TEXT,
    content_type TEXT NOT NULL,
    media_urls TEXT,
    views INTEGER,
    forwards INTEGER,
    reply_to_msg_id INTEGER,
    created_at TIMESTAMP,
    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS telegram_hashtags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,
    hashtag TEXT NOT NULL,
    FOREIGN KEY(message_id) REFERENCES telegram_messages(id),
    UNIQUE(message_id, hashtag)
);

CREATE TABLE IF NOT EXISTS content_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL,
    content_source TEXT NOT NULL,
    classifier_name TEXT NOT NULL,
    classification_type TEXT NOT NULL DEFAULT 'single',
    run_id TEXT,
    label TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT,
    llm_metadata TEXT,
    llm_provider TEXT,
    llm_model TEXT,
    details_json TEXT,
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Columns added by __add_column_if_not_exists (content_analysis.llm_provider,
-- llm_model and details_json are already part of the CREATE statement above).
ALTER TABLE telegram_messages ADD COLUMN content_expanded TEXT;
ALTER TABLE instagram_posts ADD COLUMN content_expanded TEXT;

CREATE TABLE IF NOT EXISTS content_enrichments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL,
    content_source TEXT NOT NULL,
    enrichment_type TEXT NOT NULL,
    enricher_name TEXT NOT NULL,
    generated_text TEXT,
    source_url TEXT,
    metadata_json TEXT,
    llm_provider TEXT,
    llm_model TEXT,
    llm_metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
