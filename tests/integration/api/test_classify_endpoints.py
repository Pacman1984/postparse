"""Integration tests for /api/v1/classify/* on the generic TaxonomyClassifier.

The classifier factory dependency is overridden with a deterministic
FunctionModel (see ``tests/fake_llm.py``); no LLM is contacted.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from postparse.api.dependencies import (
    RECIPE_SPEC,
    clear_classifier_cache,
    get_cached_classifier,
    get_classifier_factory,
)
from postparse.api.main import app
from tests.fake_llm import FAIL_MARKER, fake_classifier_factory, keyword_model

pytestmark = pytest.mark.integration

RECIPE = "Boil pasta for 10 minutes, drain, add tomato sauce and basil"
NON_RECIPE = "Just finished watching the news, nice weather today"
CLASSES = {
    "recipe": "Cooking instructions or ingredients",
    "python_package": "Python libraries or packages",
    "movie_review": "Movie or film discussion",
}


@pytest.fixture
def prompts() -> list[str]:
    return []


@pytest.fixture
def client(prompts: list[str]) -> Iterator[TestClient]:
    factory = fake_classifier_factory(keyword_model(calls=prompts))
    app.dependency_overrides[get_classifier_factory] = lambda: factory
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# -- recipe -----------------------------------------------------------------


def test_recipe_single(client: TestClient) -> None:
    response = client.post("/api/v1/classify/recipe", json={"text": RECIPE})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["label"] == "recipe"
    assert data["confidence"] == pytest.approx(0.9)
    assert data["classifier_used"] == "llm"
    assert data["details"] == {
        "reasoning": "keyword match", "provider": "fake", "model": "fake-model"
    }
    assert data["processing_time"] >= 0


def test_recipe_negative(client: TestClient) -> None:
    response = client.post("/api/v1/classify/recipe", json={"text": NON_RECIPE})
    assert response.status_code == 200
    assert response.json()["label"] == "not_recipe"


def test_recipe_provider_override_and_invalid_provider(client: TestClient) -> None:
    ok = client.post("/api/v1/classify/recipe",
                     json={"text": RECIPE, "provider_name": "other"})
    assert ok.json()["details"]["provider"] == "other"
    bad = client.post("/api/v1/classify/recipe",
                      json={"text": RECIPE, "provider_name": "missing"})
    assert bad.status_code == 400
    assert "missing" in bad.text


def test_recipe_llm_failure_is_503(client: TestClient) -> None:
    response = client.post("/api/v1/classify/recipe", json={"text": f"{RECIPE} {FAIL_MARKER}"})
    assert response.status_code == 503


def test_recipe_batch_with_partial_failure(client: TestClient) -> None:
    response = client.post(
        "/api/v1/classify/batch",
        json={"texts": [RECIPE, NON_RECIPE, f"x {FAIL_MARKER}"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_processed"] == 3
    assert data["failed_count"] == 1
    assert [(r["input_index"], r["label"]) for r in data["results"]] == [
        (0, "recipe"), (1, "not_recipe")
    ]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/classify/recipe", {"text": ""}),
        ("/api/v1/classify/recipe", {"text": "   "}),
        ("/api/v1/classify/recipe", {"text": "a" * 10001}),
        ("/api/v1/classify/recipe", {"classifier_type": "llm"}),
        ("/api/v1/classify/batch", {"texts": []}),
        ("/api/v1/classify/batch", {"texts": [RECIPE] * 101}),
        ("/api/v1/classify/multi", {"text": "x", "classes": {"only": "one"}}),
        ("/api/v1/classify/multi/batch", {"texts": [], "classes": CLASSES}),
        ("/api/v1/classify/multilabel", {"text": "", "classes": CLASSES}),
    ],
)
def test_request_validation(client: TestClient, path: str, payload: dict) -> None:
    assert client.post(path, json=payload).status_code == 422


# -- multi-class --------------------------------------------------------------


def test_multi_with_runtime_classes(client: TestClient, prompts: list[str]) -> None:
    response = client.post(
        "/api/v1/classify/multi",
        json={"text": "Check out this new FastAPI library", "classes": CLASSES},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["label"] == "python_package"
    assert data["available_classes"] == list(CLASSES)
    assert data["classifier_used"] == "multi_class_llm"
    assert data["reasoning"] == "keyword match"
    assert "FastAPI" in prompts[-1]


def test_multi_defaults_to_config_classes(client: TestClient) -> None:
    response = client.post("/api/v1/classify/multi", json={"text": "Great movie last night"})
    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "movie_review"
    assert data["available_classes"] == ["recipe", "python_package", "movie_review"]


def test_multi_batch(client: TestClient) -> None:
    response = client.post(
        "/api/v1/classify/multi/batch",
        json={"texts": [RECIPE, "pip install requests", f"{FAIL_MARKER}"], "classes": CLASSES},
    )
    data = response.json()
    assert response.status_code == 200
    assert [r["label"] for r in data["results"]] == ["recipe", "python_package"]
    assert data["failed_count"] == 1
    assert all(r["available_classes"] == list(CLASSES) for r in data["results"])


def test_multi_llm_failure_and_bad_provider(client: TestClient) -> None:
    failed = client.post("/api/v1/classify/multi",
                         json={"text": FAIL_MARKER, "classes": CLASSES})
    assert failed.status_code == 503
    bad = client.post("/api/v1/classify/multi",
                      json={"text": "x", "classes": CLASSES, "provider_name": "missing"})
    assert bad.status_code == 400


# -- multi-label ----------------------------------------------------------------


def test_multilabel(client: TestClient) -> None:
    response = client.post(
        "/api/v1/classify/multilabel",
        json={"text": "Movie night with a pasta recipe", "classes": CLASSES},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert {lbl["label"] for lbl in data["labels"]} == {"recipe", "movie_review"}
    assert all(lbl["confidence"] == pytest.approx(0.9) for lbl in data["labels"])
    assert data["classifier_used"] == "multi_label_llm"
    assert data["available_classes"] == list(CLASSES)


def test_multilabel_no_match_returns_empty_list(client: TestClient) -> None:
    response = client.post("/api/v1/classify/multilabel",
                           json={"text": "Good morning", "classes": CLASSES})
    assert response.status_code == 200
    assert response.json()["labels"] == []


def test_multilabel_batch(client: TestClient) -> None:
    response = client.post(
        "/api/v1/classify/multilabel/batch",
        json={"texts": ["pasta recipe", "hello", FAIL_MARKER], "classes": CLASSES},
    )
    data = response.json()
    assert data["total_processed"] == 3
    assert data["failed_count"] == 1
    assert [[lbl["label"] for lbl in r["labels"]] for r in data["results"]] == [["recipe"], []]


# -- listing ---------------------------------------------------------------------


def test_list_classifiers(client: TestClient) -> None:
    response = client.get("/api/v1/classify/classifiers")
    assert response.status_code == 200
    data = response.json()
    assert [c["type"] for c in data["classifiers"]] == ["llm", "multi_class_llm",
                                                        "multi_label_llm"]
    assert [t["name"] for t in data["taxonomies"]] == ["topics"]
    assert data["taxonomies"][0]["mode"] == "multi"
    providers = {p["name"]: p for p in data["providers"]}
    assert providers["lm_studio"]["default"] is True
    assert providers["lm_studio"]["output_mode"] == "native"
    assert providers["lm_studio"]["max_concurrency"] == 1
    assert providers["openai"]["output_mode"] == "tool"
    assert all("status" in p for p in data["providers"])


# -- real factory (no override) ----------------------------------------------------


def test_real_factory_caches_per_spec_and_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_resolve(cfg):
        calls.append(cfg.name)
        return cfg

    monkeypatch.setattr("postparse.llm.client.resolve_provider_model", fake_resolve)
    clear_classifier_cache()
    first = get_cached_classifier(RECIPE_SPEC, None)
    assert get_cached_classifier(RECIPE_SPEC, None) is first
    named = get_cached_classifier(RECIPE_SPEC, "lm_studio")
    assert get_cached_classifier(RECIPE_SPEC, "LM_STUDIO") is named
    other = get_cached_classifier(RECIPE_SPEC, "ollama")
    assert other is not first
    assert first.provider_name == "lm_studio"
    assert first.output_mode == "native"
    assert calls == ["lm_studio", "ollama"]
    with pytest.raises(ValueError, match="not found"):
        get_cached_classifier(RECIPE_SPEC, "missing")


def test_startup_survives_unreachable_llm() -> None:
    """Lifespan warm-up must not fail when the LLM server is down (closed port)."""
    with TestClient(app) as test_client:
        assert test_client.get("/health").status_code == 200
        # Without override, the real (blocked) model answers 503.
        response = test_client.post("/api/v1/classify/recipe", json={"text": RECIPE})
        assert response.status_code == 503
