"""Taxonomies, classification runs and results.

Pending semantics (:meth:`ClassificationRepo.pending_items`):

* A result is *done* for a taxonomy when its status is ``ok`` or ``no_labels``
  and its run used the taxonomy's current ``label_set_sha256``. ``error``
  results never count as done.
* ``default``: not done AND (item ``collected_at >= taxonomy.created_at`` OR
  the item has no current result in any taxonomy). Old, already classified
  posts are therefore not processed automatically when a taxonomy is added.
* ``backfill``: every item that is not done.
* ``reprocess``: every item matching the filters.

A label-set change bumps ``taxonomies.version`` but keeps ``created_at``, so
``default`` keeps its cut-off while ``backfill`` re-classifies older items.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from postparse.core.db.filters import build_filter
from postparse.core.db.models import (
    ClassificationResult,
    ClassificationRun,
    CurrentClassification,
    ItemFilter,
    PendingScope,
    ResultStatus,
    RunStatus,
    Taxonomy,
    TaxonomyLabel,
    TaxonomyMode,
)
from postparse.core.timeutil import from_db_ts, to_db_ts, utcnow_ts

__all__ = ["ClassificationRepo", "label_set_hash"]

LabelSpec = TaxonomyLabel | str | Mapping[str, str] | tuple[str, str]


def _coerce_label(spec: LabelSpec) -> TaxonomyLabel:
    """Accept labels as TaxonomyLabel, name, ``(name, description)`` or mapping."""
    if isinstance(spec, TaxonomyLabel):
        label = spec
    elif isinstance(spec, str):
        label = TaxonomyLabel(spec)
    elif isinstance(spec, tuple):
        label = TaxonomyLabel(spec[0], spec[1])
    else:
        label = TaxonomyLabel(spec["name"], spec.get("description", ""))
    name = label.name.strip()
    if not name:
        raise ValueError("Label names must not be empty")
    return TaxonomyLabel(name, (label.description or "").strip())


def label_set_hash(mode: TaxonomyMode, labels: Sequence[TaxonomyLabel]) -> str:
    """Return the hash identifying a label set (order-independent, includes mode)."""
    canonical = json.dumps(
        {
            "mode": mode,
            "labels": sorted([lb.name, lb.description] for lb in labels),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _dumps(value: Any) -> str | None:
    """Encode an optional JSON value."""
    return json.dumps(value, ensure_ascii=False) if value is not None else None


class ClassificationRepo:
    """Access to taxonomies, runs, results and result labels.

    Args:
        conn: Open connection; the caller controls the transaction.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # -- taxonomies ---------------------------------------------------------

    def ensure_taxonomy(
        self,
        name: str,
        mode: TaxonomyMode,
        labels: Iterable[LabelSpec],
        *,
        is_legacy: bool = False,
    ) -> Taxonomy:
        """Create a taxonomy, or update it when its label set changed.

        A changed label set (names, descriptions or mode) bumps ``version``
        and ``label_set_sha256``; ``created_at`` is kept.

        Args:
            name: Unique taxonomy name.
            mode: ``single`` (at most one label per item) or ``multi``.
            labels: Labels in display order.
            is_legacy: Marks taxonomies imported from schema v1.

        Returns:
            The stored taxonomy.

        Raises:
            ValueError: If there are no labels or duplicate label names.
        """
        coerced = [_coerce_label(spec) for spec in labels]
        names = [label.name for label in coerced]
        if not coerced:
            raise ValueError("A taxonomy needs at least one label")
        if len(set(names)) != len(names):
            raise ValueError(f"Duplicate label names in taxonomy {name!r}")
        digest = label_set_hash(mode, coerced)
        labels_json = json.dumps(
            [{"name": lb.name, "description": lb.description} for lb in coerced],
            ensure_ascii=False,
        )
        existing = self.get_taxonomy(name)
        if existing is None:
            self.conn.execute(
                "INSERT INTO taxonomies (name, mode, labels, label_set_sha256, is_legacy) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, mode, labels_json, digest, int(is_legacy)),
            )
        elif existing.label_set_sha256 != digest:
            self.conn.execute(
                "UPDATE taxonomies SET mode = ?, labels = ?, label_set_sha256 = ?, "
                "version = version + 1, is_legacy = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (mode, labels_json, digest, int(is_legacy), existing.id),
            )
        elif existing.labels != tuple(coerced) or existing.is_legacy != is_legacy:
            # Same set, different order or legacy flag: no version bump.
            self.conn.execute(
                "UPDATE taxonomies SET labels = ?, is_legacy = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (labels_json, int(is_legacy), existing.id),
            )
        taxonomy = self.get_taxonomy(name)
        assert taxonomy is not None
        return taxonomy

    def get_taxonomy(self, name_or_id: str | int) -> Taxonomy | None:
        """Return a taxonomy by name or id."""
        column = "id" if isinstance(name_or_id, int) else "name"
        row = self.conn.execute(
            f"SELECT * FROM taxonomies WHERE {column} = ?", (name_or_id,)
        ).fetchone()
        return Taxonomy.from_row(row) if row else None

    def list_taxonomies(self) -> list[Taxonomy]:
        """Return all taxonomies ordered by name."""
        rows = self.conn.execute("SELECT * FROM taxonomies ORDER BY name").fetchall()
        return [Taxonomy.from_row(row) for row in rows]

    # -- runs ----------------------------------------------------------------

    def create_run(
        self,
        taxonomy_id: int,
        *,
        provider: str | None = None,
        model: str | None = None,
        prompt_sha256: str | None = None,
        params: Any = None,
        status: RunStatus = "running",
        started_at: datetime | str | None = None,
    ) -> int:
        """Start a classification run for the taxonomy's current label set.

        Args:
            taxonomy_id: Taxonomy id.
            provider: LLM provider name.
            model: Model name.
            prompt_sha256: Hash of the prompt template.
            params: JSON-serializable run parameters.
            status: ``running`` (default) or ``legacy`` for imported results.
            started_at: Start time (default: now).

        Returns:
            Run id.

        Raises:
            KeyError: If the taxonomy does not exist.
        """
        taxonomy = self.get_taxonomy(taxonomy_id)
        if taxonomy is None:
            raise KeyError(taxonomy_id)
        started = to_db_ts(started_at) if started_at is not None else utcnow_ts()
        row = self.conn.execute(
            "INSERT INTO classification_runs (taxonomy_id, provider, model, label_set_sha256, "
            "prompt_sha256, params, status, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "RETURNING id",
            (
                taxonomy_id,
                provider,
                model,
                taxonomy.label_set_sha256,
                prompt_sha256,
                _dumps(params),
                status,
                started,
            ),
        ).fetchone()
        return int(row[0])

    def get_run(self, run_id: int) -> ClassificationRun | None:
        """Return a run or ``None``."""
        row = self.conn.execute(
            "SELECT * FROM classification_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return ClassificationRun.from_row(row) if row else None

    def finish_run(
        self, run_id: int, status: RunStatus = "done", finished_at: datetime | None = None
    ) -> ClassificationRun:
        """Close a run and store its ok/failed counters (computed from results).

        Returns:
            The updated run.

        Raises:
            KeyError: If the run does not exist.
        """
        finished = to_db_ts(finished_at) if finished_at is not None else utcnow_ts()
        self.conn.execute(
            """
            UPDATE classification_runs SET
                status = ?,
                finished_at = ?,
                n_ok = (SELECT count(*) FROM classification_results
                        WHERE run_id = classification_runs.id
                          AND status IN ('ok', 'no_labels')),
                n_failed = (SELECT count(*) FROM classification_results
                            WHERE run_id = classification_runs.id AND status = 'error')
            WHERE id = ?
            """,
            (status, finished, run_id),
        )
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    # -- results -------------------------------------------------------------

    def add_result(
        self,
        run_id: int,
        item_id: int,
        status: ResultStatus,
        labels: Iterable[tuple[str, float | None] | str] = (),
        confidence: float | None = None,
        reasoning: str | None = None,
        details: Any = None,
        error: str | None = None,
    ) -> int:
        """Store the result for one item in a run (replacing an earlier one in that run).

        Args:
            run_id: Run id.
            item_id: Item id.
            status: ``ok`` (at least one label), ``no_labels`` (none applies)
                or ``error`` (no labels; will be retried).
            labels: ``(label, confidence)`` pairs or plain label names.
            confidence: Overall confidence in ``[0, 1]``.
            reasoning: Model explanation.
            details: JSON-serializable extra output.
            error: Error description for ``error`` results.

        Returns:
            Result id.

        Raises:
            KeyError: If the run does not exist.
            ValueError: If labels are unknown, inconsistent with ``status`` or
                violate a ``single`` taxonomy.
        """
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        taxonomy = self.get_taxonomy(run.taxonomy_id)
        assert taxonomy is not None
        pairs = [(lb, None) if isinstance(lb, str) else (lb[0], lb[1]) for lb in labels]
        names = [name for name, _ in pairs]
        unknown = sorted(set(names) - set(taxonomy.label_names))
        if unknown:
            raise ValueError(f"Unknown labels for taxonomy {taxonomy.name!r}: {unknown}")
        if len(set(names)) != len(names):
            raise ValueError("Duplicate labels in result")
        if status == "ok" and not pairs:
            raise ValueError("Status 'ok' requires at least one label")
        if status in ("no_labels", "error") and pairs:
            raise ValueError(f"Status {status!r} must not carry labels")
        if taxonomy.mode == "single" and len(pairs) > 1:
            raise ValueError(f"Taxonomy {taxonomy.name!r} is single-label")

        self.conn.execute(
            "DELETE FROM classification_results WHERE run_id = ? AND item_id = ?",
            (run_id, item_id),
        )
        row = self.conn.execute(
            "INSERT INTO classification_results (run_id, item_id, taxonomy_id, status, "
            "confidence, reasoning, details, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "RETURNING id",
            (run_id, item_id, run.taxonomy_id, status, confidence, reasoning,
             _dumps(details), error),
        ).fetchone()
        result_id = int(row[0])
        self.conn.executemany(
            "INSERT INTO result_labels (result_id, label, confidence) VALUES (?, ?, ?)",
            [(result_id, name, conf) for name, conf in pairs],
        )
        return result_id

    def get_result(self, result_id: int) -> ClassificationResult | None:
        """Return a result with its labels."""
        row = self.conn.execute(
            "SELECT * FROM classification_results WHERE id = ?", (result_id,)
        ).fetchone()
        if row is None:
            return None
        labels = self.conn.execute(
            "SELECT label, confidence FROM result_labels WHERE result_id = ? ORDER BY label",
            (result_id,),
        ).fetchall()
        return ClassificationResult(
            id=row["id"],
            run_id=row["run_id"],
            item_id=row["item_id"],
            taxonomy_id=row["taxonomy_id"],
            status=row["status"],
            labels=tuple((lb[0], lb[1]) for lb in labels),
            confidence=row["confidence"],
            reasoning=row["reasoning"],
            details=json.loads(row["details"]) if row["details"] is not None else None,
            error=row["error"],
            created_at=from_db_ts(row["created_at"]),
        )

    def current_for_items(
        self, item_ids: Sequence[int], taxonomy: str | None = None
    ) -> dict[int, list[CurrentClassification]]:
        """Return current classifications of several items in one query.

        Args:
            item_ids: Items.
            taxonomy: Restrict to one taxonomy name.

        Returns:
            ``{item_id: [CurrentClassification, ...]}`` ordered by taxonomy name.
        """
        result: dict[int, list[CurrentClassification]] = {}
        if not item_ids:
            return result
        sql = """
            SELECT v.item_id, v.taxonomy_id, tx.name AS taxonomy, v.result_id, v.run_id,
                   v.status, v.confidence, v.reasoning, v.created_at, ru.provider, ru.model,
                   (SELECT json_group_array(label) FROM
                       (SELECT label FROM result_labels WHERE result_id = v.result_id
                        ORDER BY coalesce(confidence, 0) DESC, label)) AS labels
            FROM v_current_classification AS v
            JOIN taxonomies AS tx ON tx.id = v.taxonomy_id
            JOIN classification_runs AS ru ON ru.id = v.run_id
            WHERE v.item_id IN (SELECT value FROM json_each(?))
        """
        params: list[object] = [json.dumps(list(item_ids))]
        if taxonomy is not None:
            sql += " AND tx.name = ?"
            params.append(taxonomy)
        sql += " ORDER BY v.item_id, tx.name"
        for row in self.conn.execute(sql, params).fetchall():
            result.setdefault(row["item_id"], []).append(
                CurrentClassification(
                    item_id=row["item_id"],
                    taxonomy_id=row["taxonomy_id"],
                    taxonomy=row["taxonomy"],
                    result_id=row["result_id"],
                    run_id=row["run_id"],
                    status=row["status"],
                    labels=tuple(json.loads(row["labels"])),
                    confidence=row["confidence"],
                    reasoning=row["reasoning"],
                    provider=row["provider"],
                    model=row["model"],
                    created_at=from_db_ts(row["created_at"]),
                )
            )
        return result

    # -- work selection ------------------------------------------------------

    def pending_items(
        self,
        taxonomy_id: int,
        *,
        scope: PendingScope = "default",
        filters: ItemFilter | None = None,
        limit: int | None = None,
    ) -> list[int]:
        """Return ids of items to classify (newest first).

        See the module docstring for the exact scope semantics.

        Args:
            taxonomy_id: Taxonomy id.
            scope: ``default``, ``backfill`` or ``reprocess``.
            filters: Additional item filter.
            limit: Maximum number of ids.

        Returns:
            Item ids ordered by ``sort_at`` descending.

        Raises:
            KeyError: If the taxonomy does not exist.
            ValueError: For an unknown scope.
        """
        taxonomy = self.get_taxonomy(taxonomy_id)
        if taxonomy is None:
            raise KeyError(taxonomy_id)
        if scope not in ("default", "backfill", "reprocess"):
            raise ValueError(f"Unknown scope: {scope!r}")
        where, params = build_filter(filters).where_with_fts_subquery()
        not_done = (
            "NOT EXISTS (SELECT 1 FROM classification_results AS cr "
            "JOIN classification_runs AS ru ON ru.id = cr.run_id "
            "WHERE cr.item_id = i.id AND cr.taxonomy_id = ? "
            "AND cr.status IN ('ok', 'no_labels') AND ru.label_set_sha256 = ?)"
        )
        if scope in ("default", "backfill"):
            where.append(not_done)
            params.extend([taxonomy.id, taxonomy.label_set_sha256])
        if scope == "default":
            where.append(
                "(i.collected_at >= ? OR NOT EXISTS (SELECT 1 FROM classification_results "
                "AS any_cr WHERE any_cr.item_id = i.id AND any_cr.status IN ('ok', 'no_labels')))"
            )
            params.append(to_db_ts(taxonomy.created_at))
        sql = "SELECT i.id FROM items AS i"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY i.sort_at DESC, i.id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [int(row[0]) for row in self.conn.execute(sql, params).fetchall()]
