"""Tests for the schema v1 -> v2 data migration (``postparse.core.db.legacy_v1``)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from postparse.cli.main import cli
from postparse.core.data.database import SocialMediaDatabase
from postparse.core.db import Database, legacy_v1
from postparse.core.db.legacy_v1 import (
    LEGACY_FETCHER,
    LegacyMigrationError,
    logical_digest,
    migrate_v1,
)
from postparse.core.db.models import ItemFilter, LabelFilter
from postparse.core.db.repos import ClassificationRepo
from postparse.services.query import QueryService

GOOD_TEXT = "Café schön"
MOJIBAKE = GOOD_TEXT.encode("utf-8").decode("latin-1")  # 'CafÃ© schÃ¶n'
CHAT = 999


def _touch(root: Path, rel: str, payload: bytes = b"x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _build_v1(path: Path, downloads: Path) -> None:
    """Create a small v1 database with the real v1 DDL and edge cases."""
    SocialMediaDatabase(str(path))  # creates the v1 tables
    conn = sqlite3.connect(path)
    ig = [
        # id, shortcode, caption, is_video, typename, created_at (naive local), fetched_at
        (1, "AAA", "Pasta #Rezept https://example.com/a", 1, "GraphVideo",
         "2024-01-15T10:00:00", "2024-02-01 12:00:00"),
        # Ambiguous hour (DST end in Europe/Berlin): fold=0 -> CEST.
        (2, "BBB", "", 0, "GraphSidecar", "2024-10-27T02:30:00", "2024-11-01 08:00:00"),
        # Nonexistent hour (DST start): fold=0 -> pre-transition offset (CET).
        (3, "CCC", "Bild", 0, "GraphImage", "2024-03-31T02:30:00", "2024-04-01 08:00:00"),
        (4, "DDD", None, 1, None, "2024-07-01T12:00:00", "2024-07-02 08:00:00"),
    ]
    for row in ig:
        conn.execute(
            "INSERT INTO instagram_posts (id, shortcode, post_url, owner_username, owner_id, "
            "caption, is_video, media_url, typename, likes, comments, is_saved, source, "
            "created_at, fetched_at) VALUES (?, ?, ?, 'cook', 42, ?, ?, 'https://cdn/x', ?, "
            "5, 1, 1, 'saved', ?, ?)",
            (row[0], row[1], f"https://instagram.com/p/{row[1]}", row[2], row[3], row[4],
             row[5], row[6]),
        )
    conn.executemany(
        "INSERT INTO instagram_hashtags (post_id, hashtag) VALUES (?, ?)",
        [(1, "rezept"), (1, "pasta"), (3, "pasta")],
    )
    conn.executemany(
        "INSERT INTO instagram_mentions (post_id, username) VALUES (?, ?)",
        [(1, "chef"), (3, "chef")],
    )

    referenced = "telegram/2024/05/01/11_a.jpg"
    _touch(downloads, referenced, b"image-11")
    _touch(downloads, "telegram/2024/05/02/12_b.jpg", b"image-12")  # recovered (+1 day)
    _touch(downloads, "telegram/2024/05/01/13_a.jpg")  # ambiguous: two files
    _touch(downloads, "telegram/2024/05/01/13_b.jpg")
    _touch(downloads, "telegram/2024/06/10/14_doc.pdf")  # out of window
    _touch(downloads, "telegram/2024/05/01/777_x.jpg")  # no such message
    tg = [
        # id, message_id, chat_id, content, type, media_urls, created_at, saved_at, expanded
        (1, 10, CHAT, "Hallo #Pasta @Koch https://example.org/x", "text", None,
         "2024-05-01T10:00:00+00:00", "2024-05-01 10:05:00", f"Seite: {MOJIBAKE}"),
        (2, 11, CHAT, "Foto", "image",
         json.dumps(["data\\downloads\\" + referenced.replace("/", "\\")]),
         "2024-05-01T11:00:00+00:00", "2024-05-01 11:05:00", None),
        (3, 12, CHAT, None, "image", None, "2024-05-01T23:30:00+00:00",
         "2024-05-02 00:05:00", None),
        (4, 13, CHAT, None, "image", None, "2024-05-01T12:00:00+00:00",
         "2024-05-01 12:05:00", None),
        (5, 14, CHAT, "doc", "document", None, "2024-05-01T13:00:00+00:00",
         "2024-05-01 13:05:00", None),
        (6, 15, CHAT, "links: https://a.example/1", "text", None,
         "2024-05-02T10:00:00+00:00", "2024-05-02 10:05:00",
         "https://a.example/1\nhttps://b.example/2\n"),
        (7, 16, CHAT, "zwei https://c.example/1 und https://d.example/2", "text", None,
         "2024-05-03T10:00:00+00:00", "2024-05-03 10:05:00", "scraped from two pages"),
        (8, 17, CHAT, "ohne Datum, mail me@example.org", "text", None, None,
         "2024-05-04 10:05:00", None),
        (9, 0, 123456, "test #ignore", "text", None, "2024-01-01T00:00:00.000001+00:00",
         "2024-01-01 00:00:00", None),
        (10, 1, 123456, "test 2", "text", None, "2024-01-01T00:00:00+00:00",
         "2024-01-01 00:00:00", None),
    ]
    for row in tg:
        conn.execute(
            "INSERT INTO telegram_messages (id, message_id, chat_id, content, content_type, "
            "media_urls, views, forwards, reply_to_msg_id, created_at, saved_at, "
            "content_expanded) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)",
            row,
        )
    meta_old = json.dumps({"temperature": 0.1})
    meta_new = json.dumps({"temperature": 0.2})
    analysis = [
        # content_id, source, classifier, type, run_id, label, conf, reasoning, meta,
        # provider, model, details, analyzed_at
        (1, "instagram", "recipe_llm", "single", None, "recipe", 0.9, None, None,
         "qwen_remote", "m-recipe", json.dumps({"ingredients": 3}), "2025-12-02 00:00:00"),
        (2, "instagram", "recipe_llm", "single", None, "not_recipe", 0.8, None, None,
         "qwen_remote", "m-recipe", json.dumps({"ingredients": 0}), "2025-12-02 00:00:01"),
        # Old model: two v1 runs for one item -> only the latest group counts.
        (1, "telegram", "multilabel_llm", "multi_label", "r1", "food", 0.7, None, meta_old,
         "lama.cpp", "m-old", None, "2026-03-03 10:00:00"),
        (1, "telegram", "multilabel_llm", "multi_label", "r1", "travel", 0.4, None, meta_old,
         "lama.cpp", "m-old", None, "2026-03-03 10:00:00"),
        (1, "telegram", "multilabel_llm", "multi_label", "r2", "food", 0.9, "why", meta_old,
         "lama.cpp", "m-old", None, "2026-03-03 11:00:00"),
        # New model: duplicate label in one run, max confidence wins.
        (1, "telegram", "multilabel_llm", "multi_label", "r3", "food", 0.6, None, meta_new,
         "lama.cpp", "m-new", None, "2026-07-07 09:00:00"),
        (1, "telegram", "multilabel_llm", "multi_label", "r3", "food", 0.8, "because",
         meta_new, "lama.cpp", "m-new", None, "2026-07-07 09:00:01"),
        (1, "telegram", "multilabel_llm", "multi_label", "r3", "tech", 0.5, None, meta_new,
         "lama.cpp", "m-new", None, "2026-07-07 09:00:01"),
        (7, "telegram", "multilabel_llm", "multi_label", "r4", "tech", 1.0, None, meta_new,
         "lama.cpp", "m-new", None, "2026-07-08 09:00:00"),
        # Test message and an unknown content id.
        (9, "telegram", "multilabel_llm", "multi_label", "r5", "tech", 1.0, None, meta_new,
         "lama.cpp", "m-new", None, "2026-07-08 09:00:00"),
        (9999, "telegram", "multilabel_llm", "multi_label", "r6", "tech", 1.0, None, meta_new,
         "lama.cpp", "m-new", None, "2026-07-08 09:00:00"),
    ]
    conn.executemany(
        "INSERT INTO content_analysis (content_id, content_source, classifier_name, "
        "classification_type, run_id, label, confidence, reasoning, llm_metadata, "
        "llm_provider, llm_model, details_json, analyzed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        analysis,
    )
    conn.commit()
    conn.close()


@pytest.fixture
def v1(tmp_path: Path) -> tuple[Path, Path]:
    """``(v1 database, downloads dir)``."""
    downloads = tmp_path / "data" / "downloads"
    source = tmp_path / "v1.db"
    _build_v1(source, downloads)
    return source, downloads


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _q(path: Path, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(path)
    try:
        return [tuple(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def test_migrates_and_verifies(v1: tuple[Path, Path], tmp_path: Path) -> None:
    source, downloads = v1
    before_hash, before_mtime = _sha(source), source.stat().st_mtime_ns
    target = tmp_path / "out" / "v2.db"

    report = migrate_v1(source, target, downloads_dir=downloads)

    assert report.ok and not report.mismatches
    assert all(check["ok"] for check in report.verification)
    assert target.exists() and not Path(f"{target}.tmp").exists()
    assert _sha(source) == before_hash and source.stat().st_mtime_ns == before_mtime
    json.loads(report.to_json())  # serializable

    assert report.items["instagram"] == 4 and report.items["telegram"] == 8
    assert report.dropped["telegram_test_rows"] == 2
    assert report.dropped["analysis_test_rows"] == 1
    assert report.classification["rows_unmapped"] == 1
    assert report.timestamps["instagram_created_ambiguous_dst"] == 1
    assert report.timestamps["instagram_created_nonexistent_dst"] == 1


def test_item_mapping(v1: tuple[Path, Path], tmp_path: Path) -> None:
    source, downloads = v1
    target = tmp_path / "v2.db"
    migrate_v1(source, target, downloads_dir=downloads)

    items = {
        r[0]: r[1:]
        for r in _q(target, "SELECT external_id, kind, text, author, url, created_at, "
                            "collected_at FROM items ORDER BY id")
    }
    assert items["AAA"] == ("video", "Pasta #Rezept https://example.com/a", "cook",
                            "https://www.instagram.com/p/AAA/", "2024-01-15T09:00:00.000Z",
                            "2024-02-01T12:00:00.000Z")
    assert items["BBB"][0] == "carousel" and items["BBB"][4] == "2024-10-27T00:30:00.000Z"
    assert items["CCC"][0] == "image" and items["CCC"][4] == "2024-03-31T01:30:00.000Z"
    assert items["DDD"][0] == "video"  # typename missing -> is_video
    assert items[f"{CHAT}:10"][:3] == ("text", "Hallo #Pasta @Koch https://example.org/x", None)
    assert items[f"{CHAT}:10"][4:] == ("2024-05-01T10:00:00.000Z", "2024-05-01T10:05:00.000Z")
    assert items[f"{CHAT}:14"][0] == "document"
    assert items[f"{CHAT}:17"][4] is None
    assert not any(key.startswith("123456:") for key in items)

    assert _q(target, "SELECT shortcode, owner_id, typename, likes FROM instagram_posts "
                      "ORDER BY item_id")[0] == ("AAA", 42, "GraphVideo", 5)
    assert _q(target, "SELECT count(*) FROM telegram_messages WHERE chat_id = ?",
              (CHAT,)) == [(8,)]


def test_tags(v1: tuple[Path, Path], tmp_path: Path) -> None:
    source, downloads = v1
    target = tmp_path / "v2.db"
    migrate_v1(source, target, downloads_dir=downloads)
    rows = _q(target, "SELECT i.external_id, t.kind, t.name FROM item_tags it "
                      "JOIN tags t ON t.id = it.tag_id JOIN items i ON i.id = it.item_id "
                      "ORDER BY 1, 2, 3")
    assert rows == [
        ("999:10", "hashtag", "pasta"),
        ("999:10", "mention", "koch"),
        ("AAA", "hashtag", "pasta"),
        ("AAA", "hashtag", "rezept"),
        ("AAA", "mention", "chef"),
        ("CCC", "hashtag", "pasta"),
        ("CCC", "mention", "chef"),
    ]  # no tag from the e-mail address or the dropped test row


def test_media_and_orphans(v1: tuple[Path, Path], tmp_path: Path) -> None:
    source, downloads = v1
    target = tmp_path / "v2.db"
    report = migrate_v1(source, target, downloads_dir=downloads)

    media = {
        r[0]: r[1:]
        for r in _q(target, "SELECT i.external_id, m.position, m.media_type, m.local_path, "
                            "m.mime, m.size_bytes, m.sha256, m.transcript_status, m.remote_url "
                            "FROM media m JOIN items i ON i.id = m.item_id")
    }
    assert set(media) == {"AAA", f"{CHAT}:11", f"{CHAT}:12"}
    assert media["AAA"] == (0, "video", None, None, None, None, "pending", None)
    assert media[f"{CHAT}:11"][:5] == (0, "image", "telegram/2024/05/01/11_a.jpg",
                                       "image/jpeg", 8)
    assert media[f"{CHAT}:11"][5] == hashlib.sha256(b"image-11").hexdigest()
    assert media[f"{CHAT}:12"][2] == "telegram/2024/05/02/12_b.jpg"

    assert report.media["orphans_on_disk"] == 5
    assert report.media["orphans_recovered"] == 1
    assert report.media["instagram_sidecars_without_media"] == 1
    assert report.ambiguous_files == ["telegram/2024/05/01/13_a.jpg",
                                      "telegram/2024/05/01/13_b.jpg"]
    assert report.unmatched_files == ["telegram/2024/05/01/777_x.jpg",
                                      "telegram/2024/06/10/14_doc.pdf"]
    assert report.media["files_unmatched_out_of_window"] == 1
    assert report.media["files_unmatched_no_message"] == 1


def test_links_and_expanded_text(v1: tuple[Path, Path], tmp_path: Path) -> None:
    pytest.importorskip("ftfy")
    source, downloads = v1
    target = tmp_path / "v2.db"
    report = migrate_v1(source, target, downloads_dir=downloads)

    links = _q(target, "SELECT i.external_id, l.url FROM item_links il "
                       "JOIN links l ON l.id = il.link_id JOIN items i ON i.id = il.item_id "
                       "ORDER BY 1, il.position")
    assert links == [
        ("999:10", "https://example.org/x"),
        ("999:15", "https://a.example/1"),
        ("999:15", "https://b.example/2"),  # from the raw URL list
        ("999:16", "https://c.example/1"),
        ("999:16", "https://d.example/2"),
        ("AAA", "https://example.com/a"),
    ]
    fetches = _q(target, "SELECT l.url, lf.fetcher, lf.status, lf.text, lf.fetched_at "
                         "FROM link_fetches lf JOIN links l ON l.id = lf.link_id")
    assert fetches == [("https://example.org/x", LEGACY_FETCHER, "ok", f"Seite: {GOOD_TEXT}",
                        "2024-05-01T10:05:00.000Z")]
    legacy = _q(target, "SELECT i.external_id, le.text FROM legacy_expanded_text le "
                        "JOIN items i ON i.id = le.item_id")
    assert legacy == [("999:16", "scraped from two pages")]
    assert report.expanded["ftfy_available"] is True
    assert report.expanded["repaired"] == 1
    assert report.expanded["url_lists"] == 1

    service = QueryService(Database.open(target))
    assert service.count(ItemFilter(q="schön")) == 1  # fetched text is searchable
    assert service.count(ItemFilter(q="scraped")) == 1


def test_without_ftfy(
    v1: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, downloads = v1
    monkeypatch.setattr(legacy_v1, "_load_ftfy", lambda: None)
    target = tmp_path / "v2.db"
    report = migrate_v1(source, target, downloads_dir=downloads)
    assert report.ok
    assert report.expanded["ftfy_available"] is False
    assert report.expanded["repaired"] == 0
    assert _q(target, "SELECT text FROM link_fetches") == [(f"Seite: {MOJIBAKE}",)]


def test_classifications(v1: tuple[Path, Path], tmp_path: Path) -> None:
    source, downloads = v1
    target = tmp_path / "v2.db"
    report = migrate_v1(source, target, downloads_dir=downloads)

    runs = _q(target, "SELECT r.id, t.name, r.provider, r.model, r.status, r.params, "
                      "r.started_at, r.finished_at, r.n_ok FROM classification_runs r "
                      "JOIN taxonomies t ON t.id = r.taxonomy_id ORDER BY r.id")
    assert [(r[1], r[3], r[4], r[8]) for r in runs] == [
        ("recipe_legacy", "m-recipe", "legacy", 2),
        ("topics", "m-old", "legacy", 1),
        ("topics", "m-new", "legacy", 2),
    ]
    assert json.loads(str(runs[1][5])) == {"temperature": 0.1}
    assert runs[1][6:8] == ("2026-03-03T10:00:00.000Z", "2026-03-03T11:00:00.000Z")

    taxonomies = {
        r[0]: (r[1], r[2], json.loads(str(r[3])))
        for r in _q(target, "SELECT name, mode, is_legacy, labels FROM taxonomies")
    }
    assert taxonomies["topics"][:2] == ("multi", 0)
    assert [lb["name"] for lb in taxonomies["topics"][2]] == ["food", "tech", "travel"]
    assert taxonomies["recipe_legacy"][:2] == ("single", 1)

    labels = _q(target, "SELECT r.model, i.external_id, rl.label, rl.confidence, cr.confidence, "
                        "cr.reasoning FROM result_labels rl "
                        "JOIN classification_results cr ON cr.id = rl.result_id "
                        "JOIN classification_runs r ON r.id = cr.run_id "
                        "JOIN items i ON i.id = cr.item_id ORDER BY r.id, 2, 3")
    assert labels == [
        ("m-recipe", "AAA", "recipe", 0.9, 0.9, None),
        ("m-recipe", "BBB", "not_recipe", 0.8, 0.8, None),
        ("m-old", "999:10", "food", 0.9, 0.9, "why"),  # only the latest v1 run group
        ("m-new", "999:10", "food", 0.8, 0.8, "because"),  # duplicate label -> max
        ("m-new", "999:10", "tech", 0.5, 0.8, "because"),
        ("m-new", "999:16", "tech", 1.0, 1.0, None),
    ]
    details = _q(target, "SELECT details FROM classification_results WHERE details IS NOT NULL")
    assert sorted(json.loads(str(d[0]))["ingredients"] for d in details) == [0, 3]
    assert report.classification["superseded_rows"] == 2
    assert report.classification["duplicate_label_rows_removed"] == 1

    db = Database.open(target)
    with db.read() as conn:
        repo = ClassificationRepo(conn)
        item_id = conn.execute("SELECT id FROM items WHERE external_id = '999:10'").fetchone()[0]
        current = repo.current_for_items([item_id], taxonomy="topics")[item_id][0]
        assert current.model == "m-new" and set(current.labels) == {"food", "tech"}
        topics = repo.get_taxonomy("topics")
        assert topics is not None
        assert item_id not in repo.pending_items(topics.id, scope="backfill")
    service = QueryService(db)
    assert service.count(ItemFilter(labels=LabelFilter("topics", ("tech",)))) == 2
    assert service.count(ItemFilter(labels=LabelFilter("recipe_legacy", ("recipe",)))) == 1


def test_idempotent(v1: tuple[Path, Path], tmp_path: Path) -> None:
    source, downloads = v1
    first = migrate_v1(source, tmp_path / "a.db", downloads_dir=downloads)
    second = migrate_v1(source, tmp_path / "b.db", downloads_dir=downloads)
    third = migrate_v1(source, tmp_path / "a.db", downloads_dir=downloads, overwrite=True)
    assert first.logical_sha256 == second.logical_sha256 == third.logical_sha256
    assert logical_digest(tmp_path / "a.db") == first.logical_sha256
    for field_name in ("items", "tags", "media", "links", "expanded", "classification"):
        assert getattr(first, field_name) == getattr(second, field_name)


def test_refuses_existing_target(v1: tuple[Path, Path], tmp_path: Path) -> None:
    source, downloads = v1
    target = tmp_path / "v2.db"
    target.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        migrate_v1(source, target, downloads_dir=downloads)
    assert target.read_bytes() == b"keep me"
    with pytest.raises(LegacyMigrationError):
        migrate_v1(source, source, downloads_dir=downloads, overwrite=True)


def test_refuses_v2_source(tmp_path: Path) -> None:
    v2 = tmp_path / "already.db"
    Database.open(v2)
    with pytest.raises(LegacyMigrationError):
        migrate_v1(v2, tmp_path / "out.db", downloads_dir=tmp_path)


def test_verification_failure_keeps_target(
    v1: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, downloads = v1
    target = tmp_path / "v2.db"
    original = legacy_v1._Migrator.classifications

    def broken(self: legacy_v1._Migrator) -> None:
        original(self)
        self.dst.execute("DELETE FROM result_labels WHERE label = 'tech'")

    monkeypatch.setattr(legacy_v1._Migrator, "classifications", broken)
    with pytest.raises(LegacyMigrationError) as excinfo:
        migrate_v1(source, target, downloads_dir=downloads)
    report = excinfo.value.report
    assert report is not None and not report.ok
    assert any("classification.labels" in m for m in report.mismatches)
    assert not target.exists() and not Path(f"{target}.tmp").exists()


def test_cli_writes_report(v1: tuple[Path, Path], tmp_path: Path) -> None:
    source, downloads = v1
    target = tmp_path / "v2.db"
    report_path = tmp_path / "report.json"
    runner = CliRunner()
    args = ["db", "migrate-v1", "--source", str(source), "--target", str(target),
            "--downloads-dir", str(downloads), "--report", str(report_path)]
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["ok"] is True and data["items"]["telegram"] == 8
    assert runner.invoke(cli, args).exit_code == 1  # target exists
    assert runner.invoke(cli, [*args, "--overwrite"]).exit_code == 0
    assert runner.invoke(cli, ["db", "check", "--db", str(target)]).exit_code == 0
