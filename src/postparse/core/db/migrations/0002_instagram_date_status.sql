-- PostParse schema v2, migration 0002: provenance of Instagram publication dates.
--
-- Items migrated from schema v1 got their created_at from instaloader's naive
-- local ``post.date`` interpreted in an assumed timezone. The collector stores
-- ``Post.date_utc`` directly and marks the row 'verified'; ``extract instagram
-- --refresh-dates`` re-fetches the unverified rows.
--
--   NULL          created_at is unverified (v1 migration, assumed timezone)
--   'verified'    created_at comes from instaloader's date_utc
--   'unavailable' the post could not be fetched any more (deleted / private)
ALTER TABLE instagram_posts ADD COLUMN date_status TEXT
    CHECK (date_status IS NULL OR date_status IN ('verified', 'unavailable'));
