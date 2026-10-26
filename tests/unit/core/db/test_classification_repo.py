"""Tests for taxonomies, runs, results and pending-item selection."""

from __future__ import annotations

import sqlite3

import pytest

from postparse.core.db.models import ItemFilter, ItemUpsert, TaxonomyLabel
from postparse.core.db.repos import ClassificationRepo, ItemsRepo

OLD = "2020-01-01T00:00:00.000Z"


def _item(
    conn: sqlite3.Connection,
    ext: str,
    *,
    collected_at: str | None = None,
    source: str = "telegram",
    text: str = "x",
) -> int:
    item_id, _ = ItemsRepo(conn).upsert(
        ItemUpsert(source, ext, "text", text=text, collected_at=collected_at)  # type: ignore[arg-type]
    )
    return item_id


def _backdate_taxonomy(conn: sqlite3.Connection, taxonomy_id: int, ts: str) -> None:
    conn.execute("UPDATE taxonomies SET created_at = ? WHERE id = ?", (ts, taxonomy_id))


def test_ensure_taxonomy_versioning(conn: sqlite3.Connection) -> None:
    repo = ClassificationRepo(conn)
    first = repo.ensure_taxonomy("topics", "multi", ["food", ("tech", "Software")])
    assert first.version == 1
    assert first.labels == (TaxonomyLabel("food"), TaxonomyLabel("tech", "Software"))

    same = repo.ensure_taxonomy("topics", "multi", [("tech", "Software"), "food"])
    assert (same.id, same.version, same.label_set_sha256) == (first.id, 1, first.label_set_sha256)

    bumped = repo.ensure_taxonomy("topics", "multi", ["food", "tech", "travel"])
    assert bumped.id == first.id
    assert bumped.version == 2
    assert bumped.label_set_sha256 != first.label_set_sha256
    assert bumped.created_at == first.created_at

    with pytest.raises(ValueError):
        repo.ensure_taxonomy("dupes", "multi", ["a", "a"])
    with pytest.raises(ValueError):
        repo.ensure_taxonomy("empty", "multi", [])


def test_add_result_validation(conn: sqlite3.Connection) -> None:
    repo = ClassificationRepo(conn)
    tax = repo.ensure_taxonomy("kind", "single", ["recipe", "other"])
    run = repo.create_run(tax.id, provider="p", model="m", params={"t": 0})
    item_id = _item(conn, "1")
    with pytest.raises(ValueError, match="Unknown labels"):
        repo.add_result(run, item_id, "ok", ["nope"])
    with pytest.raises(ValueError, match="single-label"):
        repo.add_result(run, item_id, "ok", ["recipe", "other"])
    with pytest.raises(ValueError):
        repo.add_result(run, item_id, "ok", [])
    with pytest.raises(ValueError):
        repo.add_result(run, item_id, "no_labels", ["recipe"])

    result_id = repo.add_result(
        run, item_id, "ok", [("recipe", 0.9)], confidence=0.9, reasoning="flour", details={"raw": 1}
    )
    result = repo.get_result(result_id)
    assert result is not None
    assert result.labels == (("recipe", 0.9),)
    assert result.details == {"raw": 1}

    # Re-adding in the same run replaces the result.
    replaced = repo.get_result(repo.add_result(run, item_id, "no_labels"))
    assert replaced is not None
    assert (replaced.status, replaced.labels) == ("no_labels", ())
    assert (
        conn.execute(
            "SELECT count(*) FROM classification_results WHERE run_id = ?", (run,)
        ).fetchone()[0]
        == 1
    )

    finished = repo.finish_run(run)
    assert (finished.status, finished.n_ok, finished.n_failed) == ("done", 1, 0)
    assert finished.finished_at is not None


def test_current_classification_is_newest_success(conn: sqlite3.Connection) -> None:
    repo = ClassificationRepo(conn)
    tax = repo.ensure_taxonomy("topics", "multi", ["a", "b"])
    item_id = _item(conn, "1")
    repo.add_result(repo.create_run(tax.id), item_id, "ok", ["a"])
    repo.add_result(repo.create_run(tax.id, model="m2"), item_id, "ok", [("b", 0.7), ("a", 0.9)])
    repo.add_result(repo.create_run(tax.id), item_id, "error", error="timeout")

    (current,) = repo.current_for_items([item_id])[item_id]
    assert current.labels == ("a", "b")  # ordered by confidence
    assert current.model == "m2"
    assert current.taxonomy == "topics"


def test_pending_scopes(conn: sqlite3.Connection) -> None:
    repo = ClassificationRepo(conn)
    other = repo.ensure_taxonomy("other", "multi", ["x"])
    old_classified = _item(conn, "old-classified", collected_at=OLD)
    old_never = _item(conn, "old-never", collected_at=OLD)
    repo.add_result(repo.create_run(other.id), old_classified, "ok", ["x"])

    tax = repo.ensure_taxonomy("topics", "multi", ["a", "b"])
    _backdate_taxonomy(conn, tax.id, "2023-01-01T00:00:00.000Z")
    new_item = _item(conn, "new")
    done_ok = _item(conn, "done-ok")
    done_none = _item(conn, "done-none")
    errored = _item(conn, "errored")
    run = repo.create_run(tax.id)
    repo.add_result(run, done_ok, "ok", ["a"])
    repo.add_result(run, done_none, "no_labels")
    repo.add_result(run, errored, "error", error="boom")

    default = set(repo.pending_items(tax.id))
    assert default == {old_never, new_item, errored}
    backfill = set(repo.pending_items(tax.id, scope="backfill"))
    assert backfill == {old_classified, old_never, new_item, errored}
    reprocess = set(repo.pending_items(tax.id, scope="reprocess"))
    assert reprocess == {old_classified, old_never, new_item, done_ok, done_none, errored}

    # Filters and limit apply on top of the scope.
    assert repo.pending_items(tax.id, scope="reprocess", limit=2) == [errored, done_none]
    filtered = repo.pending_items(tax.id, scope="backfill", filters=ItemFilter(q="nothing"))
    assert filtered == []

    with pytest.raises(ValueError):
        repo.pending_items(tax.id, scope="everything")  # type: ignore[arg-type]


def test_label_set_change_makes_items_pending_again(conn: sqlite3.Connection) -> None:
    repo = ClassificationRepo(conn)
    tax = repo.ensure_taxonomy("topics", "multi", ["a"])
    _backdate_taxonomy(conn, tax.id, "2023-01-01T00:00:00.000Z")
    old = _item(conn, "old", collected_at=OLD)
    recent = _item(conn, "recent")
    run = repo.create_run(tax.id)
    repo.add_result(run, old, "ok", ["a"])
    repo.add_result(run, recent, "ok", ["a"])
    assert repo.pending_items(tax.id) == []

    bumped = repo.ensure_taxonomy("topics", "multi", ["a", "b"])
    assert bumped.version == 2
    # Default keeps the creation cut-off: only the recent item is redone.
    assert repo.pending_items(tax.id) == [recent]
    assert set(repo.pending_items(tax.id, scope="backfill")) == {old, recent}
    # The previous result stays current for display until reclassified.
    assert repo.current_for_items([old])[old][0].labels == ("a",)
