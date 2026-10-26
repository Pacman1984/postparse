"""Shared fixtures for CLI tests: a seeded schema v2 database."""

from __future__ import annotations

from pathlib import Path

import pytest

from postparse.config import clear_settings_cache
from postparse.core.db import Database
from postparse.core.db.models import InstagramDetail, ItemUpsert, MediaInput, TelegramDetail
from postparse.core.db.repos import (
    ClassificationRepo,
    ItemsRepo,
    LinksRepo,
    SummariesRepo,
    TranscriptsRepo,
)


def seed_v2(path: Path) -> dict[str, int]:
    """Create a small schema v2 corpus at ``path`` and return item ids by key."""
    db = Database.open(path)
    ids: dict[str, int] = {}
    with db.transaction() as conn:
        items = ItemsRepo(conn)

        def add(key: str, **kwargs: object) -> None:
            ids[key], _ = items.upsert(ItemUpsert(**kwargs))  # type: ignore[arg-type]

        add("pasta", source="instagram", external_id="p1", kind="video",
            text="Creamy pasta carbonara", author="chef",
            created_at="2024-03-10T12:00:00Z", hashtags=("pasta", "dinner"),
            detail=InstagramDetail("p1"), media=(MediaInput(0, "video"),),
            links=("https://example.com/carbonara",))
        add("cake", source="instagram", external_id="p2", kind="image",
            text="Chocolate cake recipe", author="baker",
            created_at="2024-02-01T08:00:00Z", hashtags=("dessert", "pasta"),
            detail=InstagramDetail("p2"))
        add("python", source="telegram", external_id="1:1", kind="text",
            text="New Python release notes", author="news",
            created_at="2024-03-31T23:59:59Z", detail=TelegramDetail(1, 1),
            links=("https://python.org/news",))
        add("doc", source="telegram", external_id="1:2", kind="document",
            text="Pasta document", author="news",
            created_at="2024-01-15T00:00:00Z", detail=TelegramDetail(1, 2))

        media_id = conn.execute(
            "SELECT id FROM media WHERE item_id = ?", (ids["pasta"],)
        ).fetchone()[0]
        TranscriptsRepo(conn).add(media_id, backend="whisper", model="small",
                                  text="stir the guanciale")
        SummariesRepo(conn).add(ids["pasta"], "A carbonara video")
        links = LinksRepo(conn)
        link_id = conn.execute("SELECT id FROM links WHERE domain = 'example.com'").fetchone()[0]
        links.add_fetch(link_id, fetcher="trafilatura", status="ok", title="Carbonara",
                        text="Recipe text")

        repo = ClassificationRepo(conn)
        tax = repo.ensure_taxonomy("topics", "multi", ["food", "tech"])
        run = repo.create_run(tax.id)
        repo.add_result(run, ids["pasta"], "ok", [("food", 0.9)])
        repo.add_result(run, ids["cake"], "ok", ["food"])
        repo.add_result(run, ids["python"], "ok", ["tech"])
    return ids


@pytest.fixture
def v2_db(tmp_path: Path) -> tuple[Path, dict[str, int]]:
    """A seeded schema v2 database file and its item ids."""
    path = tmp_path / "v2.db"
    return path, seed_v2(path)


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Settings are cached per config path; tests change env vars and cwd."""
    clear_settings_cache()
    yield
    clear_settings_cache()
