"""Shared helpers for the enrichment tests: DB rows, a fake fetcher, a tiny PDF."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from postparse.core.db import Database
from postparse.core.db.models import ItemUpsert, Link
from postparse.core.db.repos import LEGACY_FETCHER, ItemsRepo, LinksRepo
from postparse.enrichment.fetchers.base import FetchResult
from postparse.enrichment.fetchers.router import FetchRouter
from postparse.enrichment.options import EnrichmentOptions

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def add_item(
    db: Database,
    external_id: str,
    urls: list[str],
    *,
    source: str = "telegram",
    text: str = "Schau dir das an",
) -> int:
    """Insert an item linking to ``urls``; return its id."""
    with db.transaction() as conn:
        item_id, _ = ItemsRepo(conn).upsert(
            ItemUpsert(
                source=source,  # type: ignore[arg-type]
                external_id=external_id,
                kind="text",
                text=text + " " + " ".join(urls),
                links=tuple(urls),
            )
        )
    return item_id


def link_id(db: Database, url: str) -> int:
    with db.transaction() as conn:
        return LinksRepo(conn).ensure(url)


def add_legacy_fetch(db: Database, url: str, text: str, *, at: datetime | None = None) -> None:
    """Record a migrated v1 fetch (``legacy_v1``) for ``url``."""
    with db.transaction() as conn:
        repo = LinksRepo(conn)
        repo.add_fetch(
            repo.ensure(url),
            fetcher=LEGACY_FETCHER,
            status="ok",
            text=text,
            fetched_at=at or datetime(2025, 1, 1, tzinfo=UTC),
        )


def add_fetch(
    db: Database,
    url: str,
    status: str,
    *,
    at: datetime,
    fetcher: str = "generic",
    text: str | None = None,
) -> None:
    with db.transaction() as conn:
        repo = LinksRepo(conn)
        repo.add_fetch(
            repo.ensure(url),
            fetcher=fetcher,
            status=status,  # type: ignore[arg-type]
            text=text,
            error=None if status == "ok" else "boom",
            fetched_at=at,
        )


def fts_ids(db: Database, query: str) -> list[int]:
    with db.read() as conn:
        rows = conn.execute(
            "SELECT rowid FROM items_fts WHERE items_fts MATCH ? ORDER BY rowid", (query,)
        ).fetchall()
    return [row[0] for row in rows]


class ScriptedFetcher:
    """Fetcher returning scripted results per URL (default: ok with a text)."""

    name = "fake"
    uses_network = True

    def __init__(self, results: dict[str, FetchResult | Callable[[], FetchResult]] | None = None):
        self.results = dict(results or {})
        self.calls: list[str] = []

    def matches(self, link: Link) -> bool:
        return True

    async def fetch(self, link: Link, client: httpx.AsyncClient) -> FetchResult:
        self.calls.append(link.url)
        value = self.results.get(link.url)
        if callable(value):
            return value()
        if value is not None:
            return FetchResult(
                value.status,
                fetcher=value.fetcher or self.name,
                http_status=value.http_status,
                title=value.title,
                text=value.text,
                metadata=dict(value.metadata),
                error=value.error,
            )
        return FetchResult(
            "ok",
            fetcher=self.name,
            title=f"Title of {link.url}",
            text=f"Fresh text from {link.domain}",
        )


def router_factory(fetcher: Any) -> Callable[[EnrichmentOptions], FetchRouter]:
    """Router factory with ``fetcher`` as the only fetcher and no throttling."""

    def build(options: EnrichmentOptions) -> FetchRouter:
        return FetchRouter(
            [], fetcher, options, transport=httpx.MockTransport(lambda request: httpx.Response(599))
        )

    return build


def make_pdf(text: str) -> bytes:
    """Return a minimal one-page PDF showing ``text`` (Helvetica, valid xref)."""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)
