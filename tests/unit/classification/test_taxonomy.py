"""Tests for taxonomy specs and their configuration loading."""

from __future__ import annotations

import pytest

from postparse.classification.taxonomy import (
    DEFAULT_TAXONOMY,
    LabelSpec,
    TaxonomySpec,
    load_taxonomies,
    spec_from_db,
)
from postparse.core.db.models import TaxonomyLabel
from postparse.core.db.repos.classification import label_set_hash
from postparse.core.utils.config import ConfigManager


def test_adhoc_from_names_and_mapping() -> None:
    by_names = TaxonomySpec.adhoc(["recipe", " travel "], mode="multi")
    assert by_names.label_names == ("recipe", "travel")
    by_map = TaxonomySpec.adhoc({"recipe": "Cooking", "tech": "Software"}, mode="single")
    assert by_map.labels == (LabelSpec("recipe", "Cooking"), LabelSpec("tech", "Software"))
    assert by_map.mode == "single"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"labels": []}, "at least one label"),
        ({"labels": ["a"], "mode": "single"}, "at least two labels"),
        ({"labels": ["a", "a"]}, "Duplicate"),
        ({"labels": ["a", "b"], "mode": "bogus"}, "mode"),
        ({"labels": ["a", "b"], "sources": ("myspace",)}, "unknown sources"),
        ({"labels": ["a", "b"], "mode": "single", "max_labels": 1}, "max_labels"),
        ({"labels": ["a", "b"], "max_labels": 0}, "max_labels"),
        ({"labels": [""]}, "must not be empty"),
    ],
)
def test_invalid_specs_are_rejected(kwargs: dict, message: str) -> None:
    params = {"name": "t", "mode": "multi", **kwargs}
    with pytest.raises(ValueError, match=message):
        TaxonomySpec(**params)


def test_label_set_hash_matches_database_hash() -> None:
    spec = TaxonomySpec.adhoc({"b": "B", "a": "A"}, mode="multi")
    expected = label_set_hash("multi", [TaxonomyLabel("b", "B"), TaxonomyLabel("a", "A")])
    assert spec.label_set_sha256 == expected
    # Order does not matter for the label set, but instructions change the spec hash.
    reordered = TaxonomySpec.adhoc({"a": "A", "b": "B"}, mode="multi")
    assert reordered.label_set_sha256 == spec.label_set_sha256
    with_instructions = TaxonomySpec.adhoc({"a": "A", "b": "B"}, instructions="German posts")
    assert with_instructions.spec_sha256 != reordered.spec_sha256


def test_specs_are_hashable_and_comparable() -> None:
    first = TaxonomySpec.adhoc(["x", "y"], mode="single")
    second = TaxonomySpec(name="adhoc", mode="single", labels=[LabelSpec("x"), "y"])
    assert first == second
    assert hash(first) == hash(second)


def test_load_configured_taxonomies() -> None:
    section = {
        "classes": [{"name": "ignored", "description": "legacy"}],
        "taxonomies": [
            {
                "name": "topics",
                "mode": "multi",
                "max_labels": 2,
                "instructions": "Posts are mostly German.",
                "sources": ["instagram"],
                "labels": [
                    {"name": "recipe", "description": "Cooking"},
                    {"name": "travel"},
                ],
            },
            {"name": "kind", "mode": "single", "labels": ["tutorial", "news", "other"]},
        ],
    }
    specs = load_taxonomies(section)
    assert list(specs) == ["topics", "kind"]
    topics = specs["topics"]
    assert topics.max_labels == 2
    assert topics.sources == ("instagram",)
    assert topics.labels[0] == LabelSpec("recipe", "Cooking")
    assert specs["kind"].label_names == ("tutorial", "news", "other")


def test_duplicate_taxonomy_names_are_rejected() -> None:
    section = {"taxonomies": [{"name": "t", "labels": ["a"]}, {"name": "t", "labels": ["b"]}]}
    with pytest.raises(ValueError, match="configured twice"):
        load_taxonomies(section)


def test_legacy_classes_become_topics(tmp_path) -> None:
    """The test fixture config only has [[classification.classes]]."""
    specs = load_taxonomies(ConfigManager())
    assert list(specs) == [DEFAULT_TAXONOMY]
    topics = specs[DEFAULT_TAXONOMY]
    assert topics.mode == "multi"
    assert topics.label_names == ("recipe", "python_package", "movie_review")
    assert topics.labels[0].description.startswith("Cooking")


def test_no_classification_config_yields_nothing() -> None:
    assert load_taxonomies({}) == {}


def test_spec_from_db_keeps_legacy_flag(tmp_path) -> None:
    from postparse.core.db import Database
    from postparse.core.db.repos import ClassificationRepo

    db = Database.open(tmp_path / "t.db")
    with db.transaction() as conn:
        stored = ClassificationRepo(conn).ensure_taxonomy(
            "recipe_legacy", "single", ["recipe", "not_recipe"], is_legacy=True
        )
    spec = spec_from_db(stored)
    assert spec.is_legacy is True
    assert spec.label_names == ("recipe", "not_recipe")
    assert spec.label_set_sha256 == stored.label_set_sha256
