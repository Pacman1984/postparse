"""Taxonomy specifications: which labels exist and how they are assigned.

Taxonomies are configured in ``config.toml``::

    [[classification.taxonomies]]
    name = "topics"
    mode = "multi"                 # "single": exactly one label, "multi": 0..N
    instructions = "Posts are mostly German."
    sources = ["instagram", "telegram"]   # optional; empty = all sources
    max_labels = 3                 # optional, multi only
    labels = [
        { name = "recipe", description = "Cooking instructions or ingredients" },
        { name = "travel", description = "Places, trips, hotels" },
    ]

Backward compatibility: without ``[[classification.taxonomies]]`` the legacy
``[[classification.classes]]`` list becomes the multi-label taxonomy
:data:`DEFAULT_TAXONOMY` (``topics``).

Example:
    >>> specs = load_taxonomies(ConfigManager())
    >>> specs["topics"].label_names
    ('recipe', 'python_package', 'movie_review')
    >>> TaxonomySpec.adhoc(["recipe", "tech"], mode="single").mode
    'single'
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from postparse.core.db.models import Taxonomy, TaxonomyLabel
from postparse.core.db.repos.classification import label_set_hash

__all__ = [
    "DEFAULT_TAXONOMY",
    "LabelSpec",
    "TaxonomyMode",
    "TaxonomySpec",
    "load_taxonomies",
    "spec_from_db",
]

logger = logging.getLogger(__name__)

TaxonomyMode = Literal["single", "multi"]

#: Name of the default taxonomy (derived from ``[[classification.classes]]``).
DEFAULT_TAXONOMY = "topics"

_VALID_SOURCES = ("instagram", "telegram")


@dataclass(frozen=True, slots=True)
class LabelSpec:
    """A label with an optional description shown to the model.

    Attributes:
        name: Label identifier stored in the database.
        description: What belongs to this label (ideally with examples).
    """

    name: str
    description: str = ""

    def __post_init__(self) -> None:
        name = (self.name or "").strip()
        if not name:
            raise ValueError("Label names must not be empty")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", (self.description or "").strip())


LabelInput = LabelSpec | str | Mapping[str, Any] | tuple[str, str]


def _coerce_label(value: LabelInput) -> LabelSpec:
    """Accept a LabelSpec, a name, a ``(name, description)`` tuple or a mapping."""
    if isinstance(value, LabelSpec):
        return value
    if isinstance(value, str):
        return LabelSpec(value)
    if isinstance(value, tuple):
        return LabelSpec(value[0], value[1])
    if isinstance(value, Mapping):
        return LabelSpec(str(value.get("name", "")), str(value.get("description", "") or ""))
    raise TypeError(f"Unsupported label definition: {value!r}")


@dataclass(frozen=True, slots=True)
class TaxonomySpec:
    """Definition of a taxonomy used for classification.

    Attributes:
        name: Unique taxonomy name (also the database name).
        mode: ``single`` (exactly one label) or ``multi`` (zero or more).
        labels: Labels in display order.
        instructions: Extra instructions appended to the system prompt.
        sources: Item sources the taxonomy applies to (empty: all).
        max_labels: Upper bound for ``multi`` outputs (``None``: unbounded).
    """

    name: str
    mode: TaxonomyMode
    labels: tuple[LabelSpec, ...]
    instructions: str = ""
    sources: tuple[str, ...] = ()
    max_labels: int | None = None
    is_legacy: bool = field(default=False, compare=False)

    def __post_init__(self) -> None:
        name = (self.name or "").strip()
        if not name:
            raise ValueError("Taxonomy name must not be empty")
        if self.mode not in ("single", "multi"):
            raise ValueError(f"Taxonomy {name!r}: mode must be 'single' or 'multi'")
        labels = tuple(_coerce_label(label) for label in self.labels)
        names = [label.name for label in labels]
        if not labels:
            raise ValueError(f"Taxonomy {name!r} needs at least one label")
        if self.mode == "single" and len(labels) < 2:
            raise ValueError(f"Single-label taxonomy {name!r} needs at least two labels")
        if len(set(names)) != len(names):
            raise ValueError(f"Duplicate label names in taxonomy {name!r}")
        sources = tuple(dict.fromkeys(s.strip().lower() for s in self.sources if s.strip()))
        unknown = sorted(set(sources) - set(_VALID_SOURCES))
        if unknown:
            raise ValueError(f"Taxonomy {name!r}: unknown sources {unknown}")
        if self.max_labels is not None:
            if self.mode != "multi":
                raise ValueError(f"Taxonomy {name!r}: max_labels requires mode 'multi'")
            if self.max_labels < 1:
                raise ValueError(f"Taxonomy {name!r}: max_labels must be >= 1")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "instructions", (self.instructions or "").strip())

    # -- construction -------------------------------------------------------

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> TaxonomySpec:
        """Build a spec from a ``[[classification.taxonomies]]`` table.

        Args:
            data: Table with ``name``, ``mode``, ``labels`` and optional
                ``instructions``, ``sources``, ``max_labels``.

        Returns:
            Validated taxonomy spec.

        Raises:
            ValueError: If the table is invalid.
        """
        labels = data.get("labels") or []
        if isinstance(labels, Mapping):
            labels = [LabelSpec(str(k), str(v or "")) for k, v in labels.items()]
        return cls(
            name=str(data.get("name", "")),
            mode=data.get("mode", "multi"),
            labels=tuple(_coerce_label(label) for label in labels),
            instructions=str(data.get("instructions", "") or ""),
            sources=tuple(data.get("sources") or ()),
            max_labels=data.get("max_labels"),
        )

    @classmethod
    def adhoc(
        cls,
        labels: Sequence[LabelInput] | Mapping[str, str],
        *,
        mode: TaxonomyMode = "multi",
        name: str = "adhoc",
        instructions: str = "",
        max_labels: int | None = None,
    ) -> TaxonomySpec:
        """Build a throw-away spec from a label list or ``{name: description}``.

        Args:
            labels: Label names, ``(name, description)`` pairs or a mapping.
            mode: ``single`` or ``multi``.
            name: Spec name (not persisted).
            instructions: Extra prompt instructions.
            max_labels: Upper bound for multi outputs.

        Returns:
            Validated taxonomy spec.
        """
        if isinstance(labels, Mapping):
            items: list[LabelSpec] = [LabelSpec(k, v or "") for k, v in labels.items()]
        else:
            items = [_coerce_label(label) for label in labels]
        return cls(
            name=name,
            mode=mode,
            labels=tuple(items),
            instructions=instructions,
            max_labels=max_labels,
        )

    # -- derived values ------------------------------------------------------

    @property
    def label_names(self) -> tuple[str, ...]:
        """Label names in display order."""
        return tuple(label.name for label in self.labels)

    def db_labels(self) -> list[TaxonomyLabel]:
        """Labels as database :class:`TaxonomyLabel` values."""
        return [TaxonomyLabel(label.name, label.description) for label in self.labels]

    @property
    def label_set_sha256(self) -> str:
        """Hash of mode + labels, identical to the database ``label_set_sha256``."""
        return label_set_hash(self.mode, self.db_labels())

    @property
    def spec_sha256(self) -> str:
        """Hash of everything that influences classification (for caching)."""
        canonical = json.dumps(
            {
                "name": self.name,
                "mode": self.mode,
                "labels": [[lb.name, lb.description] for lb in self.labels],
                "instructions": self.instructions,
                "max_labels": self.max_labels,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable description."""
        return {
            "name": self.name,
            "mode": self.mode,
            "labels": [{"name": lb.name, "description": lb.description} for lb in self.labels],
            "instructions": self.instructions,
            "sources": list(self.sources),
            "max_labels": self.max_labels,
        }


def spec_from_db(taxonomy: Taxonomy) -> TaxonomySpec:
    """Build a spec from a stored taxonomy (no instructions or sources).

    Args:
        taxonomy: Database taxonomy row.

    Returns:
        Spec mirroring the stored label set.
    """
    return TaxonomySpec(
        name=taxonomy.name,
        mode=taxonomy.mode,
        labels=tuple(LabelSpec(lb.name, lb.description) for lb in taxonomy.labels),
        is_legacy=taxonomy.is_legacy,
    )


def _classes_from_section(section: Mapping[str, Any]) -> list[LabelSpec]:
    """Read the legacy ``[[classification.classes]]`` list."""
    labels: list[LabelSpec] = []
    for entry in section.get("classes", []) or []:
        if isinstance(entry, Mapping) and entry.get("name"):
            labels.append(LabelSpec(str(entry["name"]), str(entry.get("description", "") or "")))
        elif isinstance(entry, str) and entry.strip():
            labels.append(LabelSpec(entry))
    return labels


def load_taxonomies(config: Any) -> dict[str, TaxonomySpec]:
    """Load configured taxonomies.

    Args:
        config: A ``ConfigManager`` (anything with ``get_section``) or the
            ``[classification]`` section as a mapping.

    Returns:
        ``{name: spec}`` in configuration order. Without
        ``[[classification.taxonomies]]`` the ``[[classification.classes]]``
        list is returned as the multi-label taxonomy ``topics``; empty when
        neither exists.

    Raises:
        ValueError: If a configured taxonomy is invalid or names repeat.
    """
    if isinstance(config, Mapping):
        section: Mapping[str, Any] = config
    else:
        section = config.get_section("classification") or {}

    specs: dict[str, TaxonomySpec] = {}
    for table in _iter_tables(section.get("taxonomies")):
        spec = TaxonomySpec.from_mapping(table)
        if spec.name in specs:
            raise ValueError(f"Taxonomy {spec.name!r} is configured twice")
        specs[spec.name] = spec
    if specs:
        return specs

    classes = _classes_from_section(section)
    if classes:
        specs[DEFAULT_TAXONOMY] = TaxonomySpec(
            name=DEFAULT_TAXONOMY, mode="multi", labels=tuple(classes)
        )
    return specs


def _iter_tables(value: Any) -> Iterable[Mapping[str, Any]]:
    """Accept a list of tables or a ``{name: table}`` mapping."""
    if not value:
        return []
    if isinstance(value, Mapping):
        return [{"name": name, **table} for name, table in value.items()]
    return [table for table in value if isinstance(table, Mapping)]
