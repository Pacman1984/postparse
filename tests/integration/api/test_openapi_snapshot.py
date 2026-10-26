"""Every route of the pre-port API (snapshot ``tests/fixtures/openapi_paths_v1.json``)
must still exist; new routes are allowed."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.routing import APIWebSocketRoute, iter_route_contexts

from postparse.api.main import create_app

SNAPSHOT = Path(__file__).resolve().parents[2] / "fixtures" / "openapi_paths_v1.json"
NEW_ROUTES = {
    "GET /api/v1/items",
    "GET /api/v1/items/{item_id}",
    "GET /api/v1/items/{item_id}/transcript",
    "GET /api/v1/items/{item_id}/summary",
    "GET /api/v1/stats",
    "GET /api/v1/taxonomies",
    "POST /api/v1/transcription/run",
    "GET /api/v1/transcription/status",
    "POST /api/v1/summaries/run",
    "POST /api/v1/enrichment/run",
    "GET /api/v1/enrichment/status",
    "POST /api/v1/classify/run",
    "POST /api/v1/classify/{taxonomy}",
    "POST /api/v1/classify/{taxonomy}/batch",
    "GET /api/v1/jobs",
    "WS /api/v1/jobs/{job_id}/ws",
}


def _routes(config, settings) -> set[str]:
    app = create_app(config=config, settings=settings)
    spec = app.openapi()
    routes = {
        f"{method.upper()} {path}" for path, ops in spec["paths"].items() for method in ops
    }
    # FastAPI >= 0.14x keeps included routers nested; iter_route_contexts flattens them.
    routes |= {
        f"WS {ctx.path}"
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.original_route, APIWebSocketRoute)
    }
    return routes


def test_snapshot_paths_still_exist(config, settings) -> None:
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert len(expected) == 27
    missing = sorted(set(expected) - _routes(config, settings))
    assert missing == []


def test_new_routes_exist(config, settings) -> None:
    assert NEW_ROUTES - _routes(config, settings) == set()


def test_list_endpoints_document_query_parameters(config, settings) -> None:
    """Search filters are query parameters now (the old GET bodies were unusable)."""
    spec = create_app(config=config, settings=settings).openapi()
    for path in ("/api/v1/search/posts", "/api/v1/search/messages"):
        op = spec["paths"][path]["get"]
        assert "requestBody" not in op
        names = {p["name"] for p in op["parameters"]}
        assert {"hashtags", "start_date", "end_date", "content_type", "cursor", "q"} <= names
    params = {p["name"]: p for p in spec["paths"]["/api/v1/instagram/posts"]["get"]["parameters"]}
    assert params["offset"].get("deprecated") is True
    assert {"cursor", "tags", "owner_username"} <= set(params)
