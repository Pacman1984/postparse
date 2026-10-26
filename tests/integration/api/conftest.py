"""Fixtures for the API integration tests.

Every test gets a fresh schema v2 database in ``tmp_path`` seeded with a small
corpus (both sources, an undated item, tags, media with a transcript, a
summary, links, classifications). The app is built with
:func:`postparse.api.main.create_app` and services from
:func:`postparse.api.deps.build_services`; individual services are replaced by
fakes through ``build_services(**overrides)``. LLM calls go to the
deterministic keyword model of ``tests/fake_llm.py``; nothing touches the
network or real accounts.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from postparse.api.deps import ApiServices, build_services
from postparse.api.main import create_app
from postparse.api.services.cache_manager import CacheManager
from postparse.classification import TaxonomySpec
from postparse.config import Settings
from postparse.core.db import Database
from postparse.core.db.models import (
    InstagramDetail,
    ItemUpsert,
    MediaInput,
    TelegramDetail,
)
from postparse.core.db.repos import (
    ClassificationRepo,
    ItemsRepo,
    LinksRepo,
    MediaRepo,
    SummariesRepo,
    TranscriptsRepo,
)
from postparse.core.utils.config import ConfigManager
from postparse.services.classification import ClassificationService
from tests.fake_llm import fake_classifier_factory

TOPICS = TaxonomySpec.adhoc(
    {"recipe": "Cooking", "tech": "Software", "travel": "Trips"}, mode="multi", name="topics"
)


@pytest.fixture
def config() -> ConfigManager:
    """The test-suite config (``config/config.toml`` in the session directory)."""
    return ConfigManager("config/config.toml")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings with every path below ``tmp_path``."""
    return Settings(data_dir=tmp_path / "data", db_path=tmp_path / "api.db")


@pytest.fixture
def db(settings: Settings) -> Database:
    """Empty, migrated schema v2 database."""
    assert settings.db_path is not None
    return Database.open(settings.db_path)


@pytest.fixture
def seeded(db: Database) -> dict[str, int]:
    """Seed the corpus and return ``{name: item_id}``."""
    ids: dict[str, int] = {}
    with db.transaction() as conn:
        items = ItemsRepo(conn)

        def add(key: str, **kwargs: Any) -> None:
            ids[key], _ = items.upsert(ItemUpsert(**kwargs))

        add(
            "pasta",
            source="instagram",
            external_id="SC_PASTA",
            kind="video",
            text="Creamy pasta carbonara rezept https://example.com/carbonara",
            author="chef",
            url="https://www.instagram.com/p/SC_PASTA/",
            created_at="2024-03-10T12:00:00Z",
            hashtags=("pasta", "dinner"),
            mentions=("friend",),
            detail=InstagramDetail(
                "SC_PASTA", owner_id=7, typename="GraphVideo", likes=120, comments=4
            ),
            media=(MediaInput(0, "video", remote_url="https://cdn.example/pasta.mp4"),),
        )
        add(
            "cake",
            source="instagram",
            external_id="SC_CAKE",
            kind="image",
            text="Chocolate cake recipe",
            author="baker",
            created_at="2024-02-01T08:00:00Z",
            hashtags=("dessert",),
            detail=InstagramDetail("SC_CAKE", likes=10, comments=1),
            media=(MediaInput(0, "image", remote_url="https://cdn.example/cake.jpg"),),
        )
        add(
            "carousel",
            source="instagram",
            external_id="SC_TRIP",
            kind="carousel",
            text="Beach trip photos",
            author="chef",
            created_at="2023-07-01T10:00:00Z",
            hashtags=("travel",),
            detail=InstagramDetail("SC_TRIP"),
        )
        add(
            "python",
            source="telegram",
            external_id="100:1",
            kind="text",
            text="New Python release notes #python",
            author="pychannel",
            created_at="2024-03-31T23:59:59Z",
            hashtags=("python",),
            detail=TelegramDetail(100, 1, views=50),
        )
        add(
            "undated",
            source="telegram",
            external_id="100:2",
            kind="document",
            text="Undated pasta document",
            author="pychannel",
            collected_at="2024-01-15T00:00:00Z",
            hashtags=("pasta",),
            detail=TelegramDetail(100, 2),
        )
        add(
            "undated2",
            source="telegram",
            external_id="100:3",
            kind="text",
            text="Another undated note",
            author="other",
            collected_at="2024-01-15T00:00:00Z",
            detail=TelegramDetail(100, 3),
        )

        media_id = MediaRepo(conn).for_item(ids["pasta"])[0].id
        TranscriptsRepo(conn).add(
            media_id,
            backend="whisper",
            model="small",
            text="stir the guanciale",
            language="it",
            segments=[{"start": 0.0, "end": 1.5, "text": "stir the guanciale"}],
            duration_s=1.5,
        )
        MediaRepo(conn).mark_transcribed(media_id)
        SummariesRepo(conn).add(
            ids["pasta"],
            "A carbonara video.\n\n- Use guanciale\n- No cream",
            provider="fake",
            model="fake-model",
        )
        links = LinksRepo(conn)
        link_id = links.for_items([ids["pasta"]])[ids["pasta"]][0].id
        links.add_fetch(
            link_id,
            fetcher="generic",
            status="ok",
            http_status=200,
            title="Carbonara",
            text="The classic recipe",
        )

        repo = ClassificationRepo(conn)
        tax = repo.ensure_taxonomy("topics", "multi", ["recipe", "tech", "travel"])
        run = repo.create_run(tax.id)
        repo.add_result(run, ids["pasta"], "ok", [("recipe", 0.9)])
        repo.add_result(run, ids["cake"], "ok", ["recipe"])
        repo.add_result(run, ids["python"], "ok", ["tech"])
        repo.finish_run(run)
    return ids


@pytest.fixture
def classification(
    db: Database, settings: Settings, config: ConfigManager
) -> ClassificationService:
    """Classification service with the ``topics`` taxonomy and the fake keyword model."""
    return ClassificationService(
        db,
        settings,
        config=config,
        taxonomies={"topics": TOPICS},
        classifier_factory=fake_classifier_factory(),
    )


ServicesFactory = Callable[..., ApiServices]


@pytest.fixture
def make_services(
    db: Database, settings: Settings, config: ConfigManager, classification: ClassificationService
) -> ServicesFactory:
    """``make_services(**overrides)`` -> services on the test database."""

    def make(**overrides: Any) -> ApiServices:
        overrides.setdefault("classification", classification)
        overrides.setdefault("cache", CacheManager(False))
        return build_services(settings, config, db=db, **overrides)

    return make


ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_client(
    make_services: ServicesFactory, settings: Settings, config: ConfigManager
) -> Iterator[ClientFactory]:
    """``make_client(**overrides)`` -> started TestClient (lifespan entered)."""
    clients: list[TestClient] = []

    def make(**overrides: Any) -> TestClient:
        services = make_services(**overrides)
        app = create_app(config=config, settings=settings, services=services)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: ClientFactory, seeded: dict[str, int]) -> TestClient:
    """Client on the seeded database with default services."""
    return make_client()


def services_of(client: TestClient) -> ApiServices:
    """Return the service container behind a test client."""
    return client.app.state.services  # type: ignore[attr-defined]


def wait_for_job(client: TestClient, job_id: str, timeout: float = 10.0) -> dict[str, Any]:
    """Poll the job until it is completed or failed."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/v1/jobs/{job_id}").json()
        if data["status"] in ("completed", "failed"):
            return data
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish: {data}")
