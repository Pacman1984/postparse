"""Classification workflow over the schema v2 database.

:class:`ClassificationService` selects pending items for a taxonomy, composes
their text (caption, transcripts, summary, linked pages, legacy expanded
text), classifies them with a :class:`~postparse.classification.TaxonomyClassifier`
and stores one result per item in a classification run.

Selection follows :meth:`ClassificationRepo.pending_items`: the ``default``
scope only picks items collected after the taxonomy was created plus items
that were never classified at all, so old posts are only (re)processed with an
explicit ``backfill`` or ``reprocess``.

Example:
    >>> service = ClassificationService.from_config("config/config.toml")
    >>> report = service.classify_pending("topics", limit=50)
    >>> report.ok, report.errors, report.skipped_waiting_transcript
    (48, 1, 3)
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from postparse.classification.classifier import (
    ClassificationError,
    ClassificationOutcome,
    TaxonomyClassifier,
)
from postparse.classification.taxonomy import (
    DEFAULT_TAXONOMY,
    LabelSpec,
    TaxonomyMode,
    TaxonomySpec,
    load_taxonomies,
    spec_from_db,
)
from postparse.core.db.connection import Database
from postparse.core.db.models import ItemFilter, PendingScope, RunStatus
from postparse.core.db.repos import (
    ClassificationRepo,
    ItemsRepo,
    LinksRepo,
    MediaRepo,
    SummariesRepo,
    TranscriptsRepo,
)
from postparse.llm.client import run_sync, select_provider
from postparse.llm.config import LLMConfig, ProviderConfig

if TYPE_CHECKING:
    from postparse.config import Settings
    from postparse.core.utils.config import ConfigManager

__all__ = [
    "DEFAULT_MAX_INPUT_CHARS",
    "ClassificationService",
    "ClassifierFactory",
    "ComposedInput",
    "ProgressUpdate",
    "RunReport",
    "TaxonomyInfo",
    "compose_inputs",
]

logger = logging.getLogger(__name__)

#: Default character budget of the composed classifier input.
DEFAULT_MAX_INPUT_CHARS = 8000
#: Items composed and dispatched per batch (results are committed per item).
DEFAULT_CHUNK_SIZE = 32
_MAX_ERROR_SAMPLES = 10

ClassifierFactory = Callable[[TaxonomySpec, str | None], TaxonomyClassifier]
ProgressStatus = Literal[
    "ok", "no_labels", "error", "skipped_empty", "skipped_waiting_transcript"
]


# ---------------------------------------------------------------------------
# Input composition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComposedInput:
    """Classifier input for one item.

    Attributes:
        item_id: Item id.
        text: Labelled sections joined by blank lines (empty when nothing is known).
        sections: Names of the sections that contributed text.
        truncated: Whether the character budget cut something off.
        waiting_transcript: The item has media whose transcript is still pending.
    """

    item_id: int
    text: str
    sections: tuple[str, ...] = ()
    truncated: bool = False
    waiting_transcript: bool = False


def _clean(text: str | None) -> str:
    """Strip a text; ``None`` becomes empty."""
    return (text or "").strip()


def compose_inputs(
    conn: sqlite3.Connection,
    item_ids: Sequence[int],
    max_chars: int = DEFAULT_MAX_INPUT_CHARS,
) -> dict[int, ComposedInput]:
    """Build the classifier input for several items.

    Sections, in priority order: caption/message text, current transcript(s),
    latest summary, latest successful fetch of each linked page, legacy v1
    expanded text. Each section is labelled; the whole input is cut to
    ``max_chars`` (a single linked page gets at most a quarter of the budget).

    Args:
        conn: Open connection.
        item_ids: Items to compose.
        max_chars: Character budget.

    Returns:
        ``{item_id: ComposedInput}`` for every existing item.
    """
    if not item_ids:
        return {}
    ids = list(item_ids)
    items_repo = ItemsRepo(conn)
    items = {item_id: items_repo.get(item_id) for item_id in ids}
    media = MediaRepo(conn).for_items(ids)
    transcripts = TranscriptsRepo(conn).current_for_items(ids)
    summaries = SummariesRepo(conn).latest_for_items(ids)
    links_repo = LinksRepo(conn)
    links = links_repo.for_items(ids)
    fetches = links_repo.latest_ok_fetches(
        sorted({link.id for item_links in links.values() for link in item_links})
    )
    expanded = items_repo.legacy_expanded_texts(ids)

    result: dict[int, ComposedInput] = {}
    for item_id in ids:
        item = items.get(item_id)
        if item is None:
            continue
        sections: list[tuple[str, str, str, int | None]] = []  # (name, header, text, cap)
        if _clean(item.text):
            sections.append(("text", "Caption", _clean(item.text), None))
        for index, transcript in enumerate(transcripts.get(item_id, [])):
            if _clean(transcript.text):
                header = "Transcript" if index == 0 else f"Transcript {index + 1}"
                sections.append(("transcript", header, _clean(transcript.text), None))
        summary = summaries.get(item_id)
        if summary is not None and _clean(summary.text):
            sections.append(("summary", "Summary", _clean(summary.text), None))
        for link in links.get(item_id, []):
            fetch = fetches.get(link.id)
            if fetch is None or not _clean(fetch.text):
                continue
            title = _clean(fetch.title)
            header = f"Linked page ({link.domain})" + (f": {title}" if title else "")
            sections.append(("link", header, _clean(fetch.text), max(max_chars // 4, 1)))
        if _clean(expanded.get(item_id)):
            sections.append(("legacy_expanded_text", "Expanded text", _clean(expanded[item_id]),
                             None))

        parts: list[str] = []
        used_sections: list[str] = []
        remaining = max_chars
        truncated = False
        for name, header, text, cap in sections:
            prefix = f"[{header}]\n"
            budget = remaining - len(prefix) - (2 if parts else 0)
            if cap is not None:
                budget = min(budget, cap)
            if budget <= 0:
                truncated = True
                break
            if len(text) > budget:
                text = text[: max(budget - 1, 0)].rstrip() + "…"
                truncated = True
            block = prefix + text
            parts.append(block)
            remaining -= len(block) + (2 if len(parts) > 1 else 0)
            if name not in used_sections:
                used_sections.append(name)
        waiting = any(m.transcript_status == "pending" for m in media.get(item_id, []))
        result[item_id] = ComposedInput(
            item_id=item_id,
            text="\n\n".join(parts),
            sections=tuple(used_sections),
            truncated=truncated,
            waiting_transcript=waiting,
        )
    return result


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RunReport:
    """Summary of a :meth:`ClassificationService.classify_pending` call.

    Attributes:
        taxonomy: Taxonomy name.
        taxonomy_version: Taxonomy version after ``ensure_taxonomy``.
        scope: Selection scope.
        run_id: Classification run id (``None`` when nothing was pending).
        provider: Provider name.
        model: Model name.
        output_mode: Structured output strategy.
        status: Final run status.
        candidates: Pending items found by the selection.
        ok: Results with labels.
        no_labels: Multi-label results without labels.
        errors: Failed items (they stay pending).
        skipped_empty: Items without any text (no result stored).
        skipped_waiting_transcript: Items with pending transcripts (no result stored).
        duration_s: Wall time in seconds.
        error_samples: Up to ten ``(item_id, message)`` pairs.
    """

    taxonomy: str
    taxonomy_version: int
    scope: PendingScope
    run_id: int | None = None
    provider: str | None = None
    model: str | None = None
    output_mode: str | None = None
    status: RunStatus | Literal["empty"] = "empty"
    candidates: int = 0
    ok: int = 0
    no_labels: int = 0
    errors: int = 0
    skipped_empty: int = 0
    skipped_waiting_transcript: int = 0
    duration_s: float = 0.0
    error_samples: list[tuple[int, str]] = field(default_factory=list)

    @property
    def classified(self) -> int:
        """Items sent to the model (ok + no_labels + errors)."""
        return self.ok + self.no_labels + self.errors

    @property
    def skipped(self) -> int:
        """Items skipped without a result."""
        return self.skipped_empty + self.skipped_waiting_transcript

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        data = dataclasses.asdict(self)
        data["classified"] = self.classified
        data["skipped"] = self.skipped
        return data


@dataclass(frozen=True, slots=True)
class ProgressUpdate:
    """Progress callback payload (one per handled item).

    Attributes:
        item_id: Item just handled.
        status: What happened to it.
        handled: Items handled so far (classified + skipped).
        total: Upper bound of items to handle (``candidates`` capped by ``limit``).
        report: Live report (counters so far).
    """

    item_id: int
    status: ProgressStatus
    handled: int
    total: int
    report: RunReport


@dataclass(frozen=True, slots=True)
class TaxonomyInfo:
    """A taxonomy as listed by :meth:`ClassificationService.list_taxonomies`.

    Attributes:
        name: Taxonomy name.
        mode: ``single`` or ``multi``.
        labels: Label names.
        configured: Defined in the configuration.
        in_db: Stored in the database.
        version: Database version (``None`` if not stored yet).
        is_legacy: Imported from schema v1.
        in_sync: Configured label set equals the stored one.
        runs: Number of runs.
        results: Result counts by status.
        classified_items: Items with a current result.
    """

    name: str
    mode: str
    labels: tuple[str, ...]
    configured: bool
    in_db: bool
    version: int | None = None
    is_legacy: bool = False
    in_sync: bool | None = None
    runs: int = 0
    results: Mapping[str, int] = field(default_factory=dict)
    classified_items: int = 0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _filter_params(item_filter: ItemFilter | None) -> dict[str, Any] | None:
    """Return the non-empty fields of a filter as JSON-friendly values."""
    if item_filter is None:
        return None
    data: dict[str, Any] = {}
    for f in dataclasses.fields(item_filter):
        value = getattr(item_filter, f.name)
        if value is None or value == ():
            continue
        data[f.name] = json.loads(json.dumps(
            dataclasses.asdict(value) if dataclasses.is_dataclass(value) else value,
            default=str,
        ))
    return data


class ClassificationService:
    """Classify database items into taxonomies and persist the results.

    Args:
        db: Schema v2 database.
        settings: Application settings (kept for future use, e.g. paths).
        llm_config: LLM providers; loaded from ``config`` when omitted.
        config: ``ConfigManager`` for taxonomies, providers and options.
        taxonomies: Explicit taxonomy specs (override the configuration).
        classifier_factory: ``(spec, provider_name) -> TaxonomyClassifier``;
            the default builds a classifier from the provider configuration.
        max_input_chars: Character budget of the composed input (default:
            ``[classification] max_input_chars`` or 8000).
        chunk_size: Items composed and dispatched per batch.
    """

    def __init__(
        self,
        db: Database,
        settings: Settings | None = None,
        llm_config: LLMConfig | None = None,
        *,
        config: ConfigManager | None = None,
        taxonomies: Mapping[str, TaxonomySpec] | None = None,
        classifier_factory: ClassifierFactory | None = None,
        max_input_chars: int | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        self.db = db
        self.settings = settings
        self.config = config
        section: Mapping[str, Any] = {}
        if config is not None:
            section = config.get_section("classification") or {}
        if taxonomies is None:
            taxonomies = load_taxonomies(section) if section else {}
        self.taxonomies: dict[str, TaxonomySpec] = dict(taxonomies)
        if llm_config is None and config is not None:
            try:
                llm_config = LLMConfig.from_config_manager(config)
            except (ValueError, TypeError) as exc:
                logger.warning("No usable LLM configuration: %s", exc)
        self.llm_config = llm_config
        self.classifier_factory = classifier_factory
        self.max_input_chars = int(
            max_input_chars or section.get("max_input_chars") or DEFAULT_MAX_INPUT_CHARS
        )
        self.chunk_size = max(1, chunk_size)
        self._classifiers: dict[tuple[str, str | None], TaxonomyClassifier] = {}

    @classmethod
    def from_config(
        cls,
        config_path: str | Path | None = None,
        *,
        db_path: str | Path | None = None,
    ) -> ClassificationService:
        """Create a service from a config file (database from ``Settings.db_path``).

        Args:
            config_path: Config file; ``None`` uses the standard search.
            db_path: Database file overriding the settings.

        Returns:
            Configured service.
        """
        from postparse.config import get_settings
        from postparse.core.utils.config import ConfigManager

        settings = get_settings(config_path)
        config = ConfigManager(config_path)
        path = Path(db_path) if db_path is not None else settings.db_path
        assert path is not None
        return cls(Database.open(path), settings, config=config)

    # -- taxonomies -----------------------------------------------------------

    def taxonomy_spec(self, name: str) -> TaxonomySpec:
        """Return the configured spec, or one rebuilt from the database.

        Args:
            name: Taxonomy name.

        Returns:
            Taxonomy spec.

        Raises:
            KeyError: If the taxonomy is neither configured nor stored.
        """
        if name in self.taxonomies:
            return self.taxonomies[name]
        with self.db.read() as conn:
            stored = ClassificationRepo(conn).get_taxonomy(name)
        if stored is None:
            known = ", ".join(sorted(self.taxonomies)) or "none"
            raise KeyError(f"Unknown taxonomy '{name}' (configured: {known})")
        return spec_from_db(stored)

    def list_taxonomies(self) -> list[TaxonomyInfo]:
        """Return configured and stored taxonomies with versions and result counts."""
        with self.db.read() as conn:
            repo = ClassificationRepo(conn)
            stored = {tx.name: tx for tx in repo.list_taxonomies()}
            stats = repo.taxonomy_stats()
        infos: list[TaxonomyInfo] = []
        for name in [*self.taxonomies, *sorted(set(stored) - set(self.taxonomies))]:
            spec = self.taxonomies.get(name)
            tx = stored.get(name)
            counters = stats.get(tx.id, {}) if tx is not None else {}
            infos.append(
                TaxonomyInfo(
                    name=name,
                    mode=spec.mode if spec is not None else tx.mode,  # type: ignore[union-attr]
                    labels=spec.label_names if spec is not None else tx.label_names,  # type: ignore[union-attr]
                    configured=spec is not None,
                    in_db=tx is not None,
                    version=tx.version if tx is not None else None,
                    is_legacy=tx.is_legacy if tx is not None else False,
                    in_sync=(
                        spec.label_set_sha256 == tx.label_set_sha256
                        if spec is not None and tx is not None
                        else None
                    ),
                    runs=counters.get("runs", 0),
                    results={k: counters.get(k, 0) for k in ("ok", "no_labels", "error")},
                    classified_items=counters.get("classified_items", 0),
                )
            )
        return infos

    # -- classifiers ------------------------------------------------------------

    def provider_config(self, provider: str | None = None) -> ProviderConfig:
        """Return the named (or default) provider configuration.

        Raises:
            ValueError: If no LLM configuration is available or the provider is unknown.
        """
        if self.llm_config is None:
            raise ValueError("No LLM providers configured ([llm] section missing)")
        return select_provider(self.llm_config, provider)

    def classifier_for(self, spec: TaxonomySpec, provider: str | None = None) -> TaxonomyClassifier:
        """Return a (cached) classifier for a spec and provider."""
        key = (spec.spec_sha256, provider)
        cached = self._classifiers.get(key)
        if cached is not None:
            return cached
        if self.classifier_factory is not None:
            classifier = self.classifier_factory(spec, provider)
        else:
            classifier = TaxonomyClassifier.from_provider(spec, self.provider_config(provider))
        self._classifiers[key] = classifier
        return classifier

    # -- ad-hoc -------------------------------------------------------------------

    def classify_text(
        self,
        text: str,
        taxonomy_name: str | None = None,
        *,
        labels: Sequence[str] | Mapping[str, str] | Sequence[LabelSpec] | None = None,
        mode: TaxonomyMode = "multi",
        provider: str | None = None,
    ) -> ClassificationOutcome:
        """Classify a text without storing anything.

        Args:
            text: Content to classify.
            taxonomy_name: Configured/stored taxonomy (default ``topics``
                unless ``labels`` are given).
            labels: Ad-hoc labels (names or ``{name: description}``).
            mode: Mode for ad-hoc labels.
            provider: Provider name (default provider when omitted).

        Returns:
            Outcome (``empty`` for blank text, without calling the model).

        Raises:
            KeyError: Unknown taxonomy.
            ClassificationError: The model call failed.
        """
        if labels is not None and taxonomy_name is None:
            spec = TaxonomySpec.adhoc(labels, mode=mode)
        else:
            spec = self.taxonomy_spec(taxonomy_name or DEFAULT_TAXONOMY)
        if not (text or "").strip():
            return ClassificationOutcome(status="empty")
        return self.classifier_for(spec, provider).classify(text)

    # -- persistent runs ----------------------------------------------------------

    def classify_pending(
        self,
        taxonomy_name: str,
        *,
        scope: PendingScope = "default",
        filters: ItemFilter | None = None,
        limit: int | None = None,
        provider: str | None = None,
        wait_for_transcripts: bool = True,
        progress: Callable[[ProgressUpdate], None] | None = None,
    ) -> RunReport:
        """Classify pending items of a taxonomy and store the results.

        Synchronous wrapper around :meth:`aclassify_pending`.
        """
        return run_sync(
            self.aclassify_pending(
                taxonomy_name,
                scope=scope,
                filters=filters,
                limit=limit,
                provider=provider,
                wait_for_transcripts=wait_for_transcripts,
                progress=progress,
            )
        )

    def _effective_filter(
        self, spec: TaxonomySpec, filters: ItemFilter | None
    ) -> ItemFilter | None:
        """Restrict the filter to the taxonomy's sources."""
        if not spec.sources:
            return filters
        if filters is not None and filters.source is not None:
            if filters.source not in spec.sources:
                raise ValueError(
                    f"Taxonomy '{spec.name}' only applies to {', '.join(spec.sources)}"
                )
            return filters
        if len(spec.sources) == 1:
            base = filters or ItemFilter()
            return dataclasses.replace(base, source=spec.sources[0])  # type: ignore[arg-type]
        return filters

    async def aclassify_pending(
        self,
        taxonomy_name: str,
        *,
        scope: PendingScope = "default",
        filters: ItemFilter | None = None,
        limit: int | None = None,
        provider: str | None = None,
        wait_for_transcripts: bool = True,
        progress: Callable[[ProgressUpdate], None] | None = None,
    ) -> RunReport:
        """Classify pending items of a taxonomy and store the results.

        Args:
            taxonomy_name: Configured (or stored) taxonomy.
            scope: ``default`` (new + never classified), ``backfill`` (all not
                done for the current label set) or ``reprocess`` (everything
                matching ``filters``).
            filters: Additional item filter.
            limit: Maximum number of items sent to the model (skipped items
                do not count).
            provider: Provider name (default provider when omitted).
            wait_for_transcripts: Skip items whose media still wait for a
                transcript, so videos are classified after transcription.
            progress: Called once per handled item.

        Returns:
            Run report. Errors are stored as ``error`` results and stay pending.

        Raises:
            KeyError: Unknown taxonomy.
            ValueError: Invalid scope, provider or source restriction.
        """
        if scope not in ("default", "backfill", "reprocess"):
            raise ValueError(f"Unknown scope: {scope!r}")
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        started = time.perf_counter()
        spec = self.taxonomy_spec(taxonomy_name)
        effective = self._effective_filter(spec, filters)
        classifier = self.classifier_for(spec, provider)

        with self.db.transaction() as conn:
            repo = ClassificationRepo(conn)
            taxonomy = repo.ensure_taxonomy(
                spec.name, spec.mode, spec.db_labels(), is_legacy=spec.is_legacy
            )
            candidates = repo.pending_items(taxonomy.id, scope=scope, filters=effective)
            report = RunReport(
                taxonomy=taxonomy.name,
                taxonomy_version=taxonomy.version,
                scope=scope,
                provider=classifier.provider_name,
                model=classifier.model_name,
                output_mode=classifier.output_mode,
                candidates=len(candidates),
            )
            if not candidates:
                report.duration_s = time.perf_counter() - started
                return report
            report.run_id = repo.create_run(
                taxonomy.id,
                provider=classifier.provider_name,
                model=classifier.model_name,
                prompt_sha256=classifier.prompt_sha256,
                params={
                    "scope": scope,
                    "filters": _filter_params(effective),
                    "limit": limit,
                    "wait_for_transcripts": wait_for_transcripts,
                    "max_input_chars": self.max_input_chars,
                    "output_mode": classifier.output_mode,
                    "taxonomy_version": taxonomy.version,
                },
            )
            report.status = "running"
        run_id = report.run_id
        logger.info(
            "Classification run %d: taxonomy=%s scope=%s candidates=%d provider=%s model=%s",
            run_id, spec.name, scope, len(candidates), report.provider, report.model,
        )

        total = min(len(candidates), limit) if limit is not None else len(candidates)
        handled = 0

        def notify(item_id: int, status: ProgressStatus) -> None:
            nonlocal handled
            handled += 1
            if progress is not None:
                progress(ProgressUpdate(item_id, status, handled, total, report))

        semaphore = asyncio.Semaphore(classifier.max_concurrency)

        async def classify_one(composed: ComposedInput) -> None:
            async with semaphore:
                try:
                    outcome = await classifier.aclassify(composed.text)
                except ClassificationError as exc:
                    outcome = ClassificationOutcome(status="error", error=str(exc))
            status = self._store_result(run_id, composed, outcome, report)
            notify(composed.item_id, status)

        scheduled = 0
        final_status: RunStatus = "done"
        try:
            for offset in range(0, len(candidates), self.chunk_size):
                if limit is not None and scheduled >= limit:
                    break
                chunk = candidates[offset : offset + self.chunk_size]
                with self.db.read() as conn:
                    composed_inputs = compose_inputs(conn, chunk, self.max_input_chars)
                work: list[ComposedInput] = []
                for item_id in chunk:
                    composed = composed_inputs.get(item_id)
                    if composed is None:
                        continue
                    if wait_for_transcripts and composed.waiting_transcript:
                        report.skipped_waiting_transcript += 1
                        notify(item_id, "skipped_waiting_transcript")
                        continue
                    if not composed.text:
                        report.skipped_empty += 1
                        notify(item_id, "skipped_empty")
                        continue
                    if limit is not None and scheduled >= limit:
                        break
                    work.append(composed)
                    scheduled += 1
                tasks = [asyncio.ensure_future(classify_one(c)) for c in work]
                try:
                    await asyncio.gather(*tasks)
                except BaseException:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise
        except BaseException:
            final_status = "failed"
            raise
        finally:
            with self.db.transaction() as conn:
                ClassificationRepo(conn).finish_run(run_id, status=final_status)
            report.status = final_status
            report.duration_s = time.perf_counter() - started
            logger.info(
                "Classification run %d %s: ok=%d no_labels=%d errors=%d skipped_empty=%d "
                "waiting_transcript=%d in %.1fs",
                run_id, final_status, report.ok, report.no_labels, report.errors,
                report.skipped_empty, report.skipped_waiting_transcript, report.duration_s,
            )
        return report

    def _store_result(
        self,
        run_id: int,
        composed: ComposedInput,
        outcome: ClassificationOutcome,
        report: RunReport,
    ) -> ProgressStatus:
        """Persist one outcome in its own transaction and update the report."""
        details = {
            "input_chars": len(composed.text),
            "sections": list(composed.sections),
            "truncated": composed.truncated,
            "latency_s": round(outcome.latency_s, 3),
            "requests": outcome.requests,
        }
        status: ProgressStatus
        with self.db.transaction() as conn:
            repo = ClassificationRepo(conn)
            try:
                if outcome.status == "ok":
                    repo.add_result(
                        run_id, composed.item_id, "ok",
                        labels=outcome.label_scores(),
                        confidence=outcome.confidence,
                        reasoning=outcome.reasoning,
                        details=details,
                    )
                    status = "ok"
                elif outcome.status == "no_labels":
                    repo.add_result(
                        run_id, composed.item_id, "no_labels",
                        confidence=outcome.confidence,
                        reasoning=outcome.reasoning,
                        details=details,
                    )
                    status = "no_labels"
                else:
                    raise ValueError(outcome.error or f"Unexpected outcome {outcome.status!r}")
            except ValueError as exc:
                message = str(exc)
                repo.add_result(run_id, composed.item_id, "error", error=message, details=details)
                status = "error"
        if status == "ok":
            report.ok += 1
        elif status == "no_labels":
            report.no_labels += 1
        else:
            report.errors += 1
            if len(report.error_samples) < _MAX_ERROR_SAMPLES:
                report.error_samples.append((composed.item_id, outcome.error or message))
        return status
