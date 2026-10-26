"""End-to-end fixtures: a schema v2 database written through the repositories the
collectors use, and the full API built by ``create_app`` with the real service
container (only the LLM is replaced by the deterministic keyword model)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from postparse.api.deps import build_services
from postparse.api.main import create_app
from postparse.config import Settings
from postparse.core.db import Database
from postparse.core.db.models import InstagramDetail, ItemUpsert, MediaInput, TelegramDetail
from postparse.core.db.repos import ItemsRepo
from postparse.core.utils.config import ConfigManager
from postparse.services.classification import ClassificationService
from tests.fake_llm import fake_classifier_factory

POSTS = [
    ("RCP1", "video", "Homemade pasta recipe with tomato sauce", "chef_anna",
     "2024-01-20T10:00:00Z", ("recipe", "pasta", "italian")),
    ("RCP2", "image", "Bake the chocolate cake: flour, eggs, sugar", "baker_bob",
     "2024-01-18T15:30:00Z", ("recipe", "dessert")),
    ("TRV1", "carousel", "Beach trip to Portugal, great hotel", "traveler",
     "2024-01-15T08:00:00Z", ("travel",)),
    ("TCH1", "image", "Unboxing my new laptop", "techie", None, ("tech",)),
]
MESSAGES = [
    (1001, "text", "Quick pasta sauce: garlic, oil, chili #recipe", "food_channel",
     "2024-01-22T12:00:00Z", ("recipe",)),
    (1002, "video", "Python 3.13 release video", "dev_news", "2024-01-21T09:00:00Z",
     ("python", "news")),
    (1003, "document", "Market report Q4", "finance", "2024-01-19T18:00:00Z", ("finance",)),
]


@pytest.fixture
def e2e_settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", db_path=tmp_path / "e2e.db")


@pytest.fixture
def e2e_db(e2e_settings: Settings) -> Database:
    assert e2e_settings.db_path is not None
    db = Database.open(e2e_settings.db_path)
    with db.transaction() as conn:
        repo = ItemsRepo(conn)
        for shortcode, kind, text, author, created, tags in POSTS:
            repo.upsert(ItemUpsert(
                source="instagram", external_id=shortcode, kind=kind, text=text, author=author,
                created_at=created, collected_at="2024-01-10T00:00:00Z", hashtags=tags,
                detail=InstagramDetail(shortcode, likes=5),
                media=(MediaInput(0, "video" if kind == "video" else "image"),),
            ))
        for message_id, kind, text, author, created, tags in MESSAGES:
            repo.upsert(ItemUpsert(
                source="telegram", external_id=f"42:{message_id}", kind=kind, text=text,
                author=author, created_at=created, hashtags=tags,
                detail=TelegramDetail(42, message_id),
            ))
    return db


@pytest.fixture
def e2e_client(e2e_db: Database, e2e_settings: Settings) -> Iterator[TestClient]:
    config = ConfigManager("config/config.toml")
    classification = ClassificationService(
        e2e_db, e2e_settings, config=config, classifier_factory=fake_classifier_factory()
    )
    services = build_services(e2e_settings, config, db=e2e_db, classification=classification)
    with TestClient(create_app(config=config, settings=e2e_settings, services=services)) as c:
        yield c
