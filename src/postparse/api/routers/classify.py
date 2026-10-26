"""
FastAPI router for classification endpoints.

All endpoints run on the shared :class:`~postparse.services.classification.ClassificationService`
and its cached :class:`~postparse.classification.TaxonomyClassifier` instances:

- ``/recipe`` and ``/batch``: ad-hoc single-label taxonomy ``recipe`` / ``not_recipe``
- ``/multi`` and ``/multi/batch``: ad-hoc single-label taxonomy from the request
  ``classes`` (default: labels of the configured ``topics`` taxonomy)
- ``/multilabel`` and ``/multilabel/batch``: the same as multi-label taxonomy
- ``/classifiers``: configured taxonomies and providers
- ``/run``: background job classifying pending database items (``postparse classify run``)
- ``/{taxonomy}`` and ``/{taxonomy}/batch``: classify texts into a configured or
  stored taxonomy; ``persist=true`` stores the results for ``item_id(s)`` as a
  classification run

Batch responses list every input as ``{input_index, ok, result | error}``; one
failing input never fails the request. Taxonomy names ``recipe``, ``batch``,
``multi``, ``multilabel``, ``classifiers`` and ``run`` are shadowed by the
fixed routes above.
"""

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, status

from postparse.api.dependencies import (
    RECIPE_SPEC,
    ClassifierFactory,
    get_cache_manager,
    get_classification_service,
    get_classifier_factory,
    get_config,
    get_job_runner,
    get_optional_auth,
    get_taxonomies,
)
from postparse.api.jobs.kinds import classify_job
from postparse.api.jobs.runner import JobRunner
from postparse.api.routers._common import accepted, item_filter_or_400
from postparse.api.schemas import (
    BatchClassifyRequest,
    BatchClassifyResponse,
    ClassifyRequest,
    ClassifyResponse,
)
from postparse.api.schemas.classify import (
    BatchItemError,
    BatchItemResult,
    BatchMultiClassifyRequest,
    BatchMultiClassifyResponse,
    BatchMultiLabelClassifyRequest,
    BatchMultiLabelClassifyResponse,
    LabelScoreResponse,
    MultiClassifyRequest,
    MultiClassifyResponse,
    MultiLabelClassifyRequest,
    MultiLabelClassifyResponse,
)
from postparse.api.schemas.pipeline import (
    ClassifyRunRequest,
    JobAcceptedResponse,
    LabelScore,
    PersistedInfo,
    TaxonomyBatchRequest,
    TaxonomyBatchResponse,
    TaxonomyClassifyRequest,
    TaxonomyClassifyResponse,
    drop_none,
)
from postparse.api.services.cache_manager import CacheManager
from postparse.classification import (
    DEFAULT_TAXONOMY,
    ClassificationError,
    ClassificationOutcome,
    TaxonomyClassifier,
    TaxonomySpec,
)
from postparse.llm.client import api_type_for, max_concurrency_for, output_mode_for
from postparse.llm.config import LLMConfig
from postparse.services.classification import ClassificationService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/classify",
    tags=["classify"],
    responses={
        400: {"description": "Invalid request"},
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
        503: {"description": "LLM service unavailable"},
    },
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_classifier(
    factory: ClassifierFactory, spec: TaxonomySpec, provider_name: str | None
) -> TaxonomyClassifier:
    """Build/fetch a classifier, mapping configuration problems to HTTP 400/503."""
    try:
        return factory(spec, provider_name)
    except ValueError as exc:
        detail = f"Invalid provider_name '{provider_name}': {exc}" if provider_name else str(exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc
    except Exception as exc:  # e.g. missing API key for a cloud provider
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"LLM provider unavailable: {exc}",
        ) from exc


async def _classify(classifier: TaxonomyClassifier, text: str, what: str) -> ClassificationOutcome:
    """Classify one text, mapping failures to HTTP 503."""
    try:
        return await classifier.aclassify(text)
    except ClassificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{what} failed: {exc}",
        ) from exc


def _adhoc_spec(
    classes: dict[str, str] | None,
    taxonomies: Mapping[str, TaxonomySpec],
    *,
    mode: str,
) -> TaxonomySpec:
    """Build the ad-hoc spec for multi/multilabel requests.

    Request ``classes`` win; otherwise the labels of the configured default
    taxonomy (``topics``, derived from ``[[classification.classes]]``) are used.

    Raises:
        HTTPException: 400 if fewer than two classes are available.
    """
    if classes is None:
        default = taxonomies.get(DEFAULT_TAXONOMY)
        classes = {label.name: label.description for label in default.labels} if default else {}
    if len(classes) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "At least 2 classes are required for classification, "
                f"got {len(classes)}. Pass 'classes' or configure "
                "[[classification.classes]] / [[classification.taxonomies]]."
            ),
        )
    try:
        return TaxonomySpec.adhoc(classes, mode=mode, name=f"api_{mode}")  # type: ignore[arg-type]  # str validated by the request schema
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _details(outcome: ClassificationOutcome, classifier: TaxonomyClassifier) -> dict[str, Any]:
    """Extra fields returned in the recipe ``details`` dict."""
    return {
        "reasoning": outcome.reasoning,
        "provider": classifier.provider_name,
        "model": classifier.model_name,
    }


def _recipe_response(
    outcome: ClassificationOutcome,
    classifier: TaxonomyClassifier,
    elapsed: float,
    index: int | None = None,
) -> ClassifyResponse:
    return ClassifyResponse(
        label=outcome.label or "not_recipe",
        confidence=outcome.confidence if outcome.confidence is not None else 0.0,
        details=_details(outcome, classifier),
        processing_time=elapsed,
        classifier_used="llm",
        input_index=index,
    )


def _multi_response(
    outcome: ClassificationOutcome,
    classifier: TaxonomyClassifier,
    elapsed: float,
    index: int | None = None,
) -> MultiClassifyResponse:
    return MultiClassifyResponse(
        label=outcome.label or "",
        confidence=outcome.confidence if outcome.confidence is not None else 0.0,
        reasoning=outcome.reasoning,
        available_classes=list(classifier.spec.label_names),
        processing_time=elapsed,
        classifier_used="multi_class_llm",
        input_index=index,
    )


def _multilabel_response(
    outcome: ClassificationOutcome,
    classifier: TaxonomyClassifier,
    elapsed: float,
    index: int | None = None,
) -> MultiLabelClassifyResponse:
    return MultiLabelClassifyResponse(
        labels=[
            LabelScoreResponse(label=label, confidence=confidence or 0.0)
            for label, confidence in outcome.label_scores()
        ],
        reasoning=outcome.reasoning,
        available_classes=list(classifier.spec.label_names),
        processing_time=elapsed,
        classifier_used="multi_label_llm",
        input_index=index,
    )


def _batch_error(outcome: ClassificationOutcome) -> BatchItemError:
    """Error object of a failed batch input."""
    if outcome.status == "empty":
        return BatchItemError(code="empty_text", message="Text is empty")
    return BatchItemError(code="llm_error", message=outcome.error or "Classification failed")


async def _run_batch(
    classifier: TaxonomyClassifier,
    texts: list[str],
    build: Callable[..., Any],
) -> tuple[list[Any], list[BatchItemResult], int]:
    """Classify a batch with the classifier's concurrency.

    Returns:
        ``(successful results, per-input outcomes, failed count)``. One failing
        input never fails the request.
    """
    outcomes = await classifier.aclassify_many(texts)
    results: list[Any] = []
    items: list[BatchItemResult] = []
    failed = 0
    for index, outcome in enumerate(outcomes):
        if not outcome.succeeded:
            failed += 1
            items.append(BatchItemResult(input_index=index, ok=False, error=_batch_error(outcome)))
            continue
        built = build(outcome, classifier, outcome.latency_s, index)
        results.append(built)
        items.append(BatchItemResult(input_index=index, ok=True, result=built.model_dump()))
    return results, items, failed


# ---------------------------------------------------------------------------
# Recipe (legacy binary classification)
# ---------------------------------------------------------------------------


@router.post(
    "/recipe",
    response_model=ClassifyResponse,
    summary="Classify text as recipe or non-recipe",
    description="""
    Classify a single text as `recipe` or `not_recipe` (an ad-hoc single-label
    taxonomy on the generic LLM classifier).

    `details` contains the model's `reasoning` plus `provider` and `model`.

    Specify `provider_name` to use another configured LLM provider.
    """,
)
async def classify_recipe(
    request: ClassifyRequest,
    factory: ClassifierFactory = Depends(get_classifier_factory),
    user: dict | None = Depends(get_optional_auth),
) -> ClassifyResponse:
    """
    Classify single text as recipe or non-recipe.

    Example:
        POST /api/v1/classify/recipe
        {"text": "Boil pasta for 10 minutes, drain, add tomato sauce", "provider_name": "lm_studio"}

        Response:
        {"label": "recipe", "confidence": 0.95,
         "details": {"reasoning": "...", "provider": "lm_studio", "model": "..."},
         "processing_time": 0.234, "classifier_used": "llm"}
    """
    start = time.perf_counter()
    classifier = _get_classifier(factory, RECIPE_SPEC, request.provider_name)
    outcome = await _classify(classifier, request.text, "Classification")
    return _recipe_response(outcome, classifier, time.perf_counter() - start)


@router.post(
    "/batch",
    response_model=BatchClassifyResponse,
    summary="Classify multiple texts in batch",
    description="""
    Classify up to 100 texts as `recipe` / `not_recipe`. Failed texts are
    counted in `failed_count` and left out of `results`.
    """,
)
async def classify_batch(
    request: BatchClassifyRequest,
    factory: ClassifierFactory = Depends(get_classifier_factory),
    user: dict | None = Depends(get_optional_auth),
) -> BatchClassifyResponse:
    """Classify multiple texts as recipe or non-recipe."""
    start = time.perf_counter()
    classifier = _get_classifier(factory, RECIPE_SPEC, request.provider_name)
    results, items, failed = await _run_batch(classifier, request.texts, _recipe_response)
    return BatchClassifyResponse(
        results=results,
        items=items,
        total_processed=len(request.texts),
        failed_count=failed,
        total_processing_time=time.perf_counter() - start,
    )


# ---------------------------------------------------------------------------
# Multi-class (single label from custom classes)
# ---------------------------------------------------------------------------


@router.post(
    "/multi",
    response_model=MultiClassifyResponse,
    summary="Classify text into custom categories",
    description="""
    Classify a text into exactly one of the given `classes` (dict of class
    name → description; minimum 2). Without `classes`, the labels of the
    configured `topics` taxonomy are used. Returns label, confidence,
    reasoning and the available classes.
    """,
)
async def classify_multi(
    request: MultiClassifyRequest,
    factory: ClassifierFactory = Depends(get_classifier_factory),
    taxonomies: dict[str, TaxonomySpec] = Depends(get_taxonomies),
    user: dict | None = Depends(get_optional_auth),
) -> MultiClassifyResponse:
    """
    Classify single text into custom categories.

    Example:
        POST /api/v1/classify/multi
        {"text": "Check out this new FastAPI library!",
         "classes": {"recipe": "Cooking", "python_package": "Python libraries"}}
    """
    start = time.perf_counter()
    spec = _adhoc_spec(request.classes, taxonomies, mode="single")
    classifier = _get_classifier(factory, spec, request.provider_name)
    outcome = await _classify(classifier, request.text, "Multi-class classification")
    return _multi_response(outcome, classifier, time.perf_counter() - start)


@router.post(
    "/multi/batch",
    response_model=BatchMultiClassifyResponse,
    summary="Classify multiple texts into custom categories",
    description="""
    Batch version of `/multi` for up to 100 texts. Individual failures are
    counted in `failed_count` and do not stop the batch.
    """,
)
async def classify_multi_batch(
    request: BatchMultiClassifyRequest,
    factory: ClassifierFactory = Depends(get_classifier_factory),
    taxonomies: dict[str, TaxonomySpec] = Depends(get_taxonomies),
    user: dict | None = Depends(get_optional_auth),
) -> BatchMultiClassifyResponse:
    """Classify multiple texts into custom categories."""
    start = time.perf_counter()
    spec = _adhoc_spec(request.classes, taxonomies, mode="single")
    classifier = _get_classifier(factory, spec, request.provider_name)
    results, items, failed = await _run_batch(classifier, request.texts, _multi_response)
    return BatchMultiClassifyResponse(
        results=results,
        items=items,
        total_processed=len(request.texts),
        failed_count=failed,
        total_processing_time=time.perf_counter() - start,
    )


# ---------------------------------------------------------------------------
# Multi-label (0..N labels from custom classes)
# ---------------------------------------------------------------------------


@router.post(
    "/multilabel",
    response_model=MultiLabelClassifyResponse,
    summary="Classify text with multiple labels",
    description="Assign ALL matching categories (0..N) to a text.",
)
async def classify_multilabel(
    request: MultiLabelClassifyRequest,
    factory: ClassifierFactory = Depends(get_classifier_factory),
    taxonomies: dict[str, TaxonomySpec] = Depends(get_taxonomies),
    user: dict | None = Depends(get_optional_auth),
) -> MultiLabelClassifyResponse:
    """Classify single text with multi-label assignment.

    Each label carries the overall confidence of the answer.
    """
    start = time.perf_counter()
    spec = _adhoc_spec(request.classes, taxonomies, mode="multi")
    classifier = _get_classifier(factory, spec, request.provider_name)
    outcome = await _classify(classifier, request.text, "Multi-label classification")
    return _multilabel_response(outcome, classifier, time.perf_counter() - start)


@router.post(
    "/multilabel/batch",
    response_model=BatchMultiLabelClassifyResponse,
    summary="Classify multiple texts with multiple labels",
    description="Batch multi-label classification for up to 100 texts.",
)
async def classify_multilabel_batch(
    request: BatchMultiLabelClassifyRequest,
    factory: ClassifierFactory = Depends(get_classifier_factory),
    taxonomies: dict[str, TaxonomySpec] = Depends(get_taxonomies),
    user: dict | None = Depends(get_optional_auth),
) -> BatchMultiLabelClassifyResponse:
    """Classify multiple texts with multi-label assignment."""
    start = time.perf_counter()
    spec = _adhoc_spec(request.classes, taxonomies, mode="multi")
    classifier = _get_classifier(factory, spec, request.provider_name)
    results, items, failed = await _run_batch(classifier, request.texts, _multilabel_response)
    return BatchMultiLabelClassifyResponse(
        results=results,
        items=items,
        total_processed=len(request.texts),
        failed_count=failed,
        total_processing_time=time.perf_counter() - start,
    )


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


@router.get(
    "/classifiers",
    response_model=dict[str, list[dict[str, Any]]],
    summary="List available classifiers",
    description="List classifier endpoints, configured taxonomies and LLM providers.",
)
def list_classifiers(
    config: Any = Depends(get_config),
    service: ClassificationService = Depends(get_classification_service),
    user: dict | None = Depends(get_optional_auth),
) -> dict[str, list[dict[str, Any]]]:
    """List available classifiers, taxonomies and providers."""
    providers: list[dict[str, Any]] = []
    try:
        llm_config = service.llm_config or (
            LLMConfig.from_config_manager(config) if config is not None else None
        )
        if llm_config is not None:
            providers = [
                {
                    "name": provider.name,
                    "status": "configured",
                    "default": provider.name == llm_config.default_provider,
                    "model": provider.model,
                    "api_type": api_type_for(provider),
                    "output_mode": output_mode_for(provider),
                    "max_concurrency": max_concurrency_for(provider),
                }
                for provider in llm_config.providers
            ]
    except (ValueError, TypeError) as exc:
        # pydantic.ValidationError is a ValueError subclass. A broken LLM config
        # must not turn the listing into a 500; report what is available.
        logger.warning("Could not load LLM provider configuration: %s", exc)

    taxonomies = [spec.to_dict() for spec in service.taxonomies.values()]
    return {
        "classifiers": [
            {
                "type": "llm",
                "name": "recipe",
                "description": "Binary recipe classification (recipe/not_recipe)",
                "endpoint": "/api/v1/classify/recipe",
            },
            {
                "type": "multi_class_llm",
                "name": "multi",
                "description": "Single-label classification into custom classes",
                "endpoint": "/api/v1/classify/multi",
            },
            {
                "type": "multi_label_llm",
                "name": "multilabel",
                "description": "Multi-label classification (0..N labels per text)",
                "endpoint": "/api/v1/classify/multilabel",
            },
            {
                "type": "taxonomy",
                "name": "taxonomy",
                "description": "Classification into a configured taxonomy (optionally persisted)",
                "endpoint": "/api/v1/classify/{taxonomy}",
            },
        ],
        "taxonomies": taxonomies,
        "providers": providers,
    }


# ---------------------------------------------------------------------------
# Persisted classification runs (job)
# ---------------------------------------------------------------------------


@router.post(
    "/run",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a classification run",
    description="""
    Classify pending database items of a taxonomy in the background and store
    the results (`postparse classify run`). `scope`: `default` (new and never
    classified items), `backfill` (everything not done for the current label
    set) or `reprocess` (everything matching `filters`).
    """,
)
async def run_classification(
    request: ClassifyRunRequest,
    service: ClassificationService = Depends(get_classification_service),
    runner: JobRunner = Depends(get_job_runner),
    user: dict | None = Depends(get_optional_auth),
) -> JobAcceptedResponse:
    """Start the job."""
    await _spec_or_404(service, request.taxonomy)
    item_filter = None
    if request.filters is not None:
        f = request.filters
        item_filter = item_filter_or_400(
            q=f.q,
            source=f.source,
            tags=f.tags,
            authors=f.authors,
            kinds=f.kinds,
            labels=f.labels,
            date_from=f.date_from,
            date_to=f.date_to,
            has_transcript=f.has_transcript,
        )
    job_id = runner.submit(
        "classify",
        drop_none(request.model_dump()),
        classify_job(
            service,
            taxonomy=request.taxonomy,
            scope=request.scope,
            filters=item_filter,
            limit=request.limit,
            provider=request.provider,
            wait_for_transcripts=request.wait_for_transcripts,
        ),
        total=request.limit,
    )
    return accepted(job_id, "classify")


# ---------------------------------------------------------------------------
# Taxonomy classification
# ---------------------------------------------------------------------------


async def _spec_or_404(service: ClassificationService, name: str) -> TaxonomySpec:
    """Resolve a configured/stored taxonomy (may read the database: worker thread)."""
    try:
        return await anyio.to_thread.run_sync(service.taxonomy_spec, name)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc.args[0] if exc.args else exc)
        ) from exc


def _taxonomy_result(
    outcome: ClassificationOutcome,
    classifier: TaxonomyClassifier,
    elapsed: float,
) -> TaxonomyClassifyResponse:
    return TaxonomyClassifyResponse(
        taxonomy=classifier.spec.name,
        mode=classifier.spec.mode,
        status=outcome.status,
        label=outcome.label,
        labels=[LabelScore(label=lb, confidence=c) for lb, c in outcome.label_scores()],
        confidence=outcome.confidence,
        reasoning=outcome.reasoning,
        available_labels=list(classifier.spec.label_names),
        provider=classifier.provider_name,
        model=classifier.model_name,
        processing_time=elapsed,
    )


async def _persist(
    service: ClassificationService,
    cache: CacheManager,
    taxonomy: str,
    outcomes: list[tuple[int, ClassificationOutcome]],
    classifier: TaxonomyClassifier,
) -> PersistedInfo:
    """Store outcomes as one run (worker thread) and invalidate the cache."""

    def store() -> PersistedInfo:
        run_id, persisted = service.persist_outcomes(taxonomy, outcomes, classifier=classifier)
        cache.invalidate()
        return PersistedInfo(run_id=run_id, result_ids=[p.result_id for p in persisted])

    try:
        return await anyio.to_thread.run_sync(store)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc.args[0] if exc.args else exc)
        ) from exc


@router.post(
    "/{taxonomy}",
    response_model=TaxonomyClassifyResponse,
    summary="Classify a text into a taxonomy",
    description="""
    Classify `text` into a configured (or stored) taxonomy, e.g. `topics`.
    With `persist=true` the result is stored for `item_id` as a classification
    run and becomes the item's current classification.
    """,
)
async def classify_taxonomy(
    taxonomy: str,
    request: TaxonomyClassifyRequest,
    service: ClassificationService = Depends(get_classification_service),
    factory: ClassifierFactory = Depends(get_classifier_factory),
    cache: CacheManager = Depends(get_cache_manager),
    user: dict | None = Depends(get_optional_auth),
) -> TaxonomyClassifyResponse:
    """Classify one text."""
    if request.persist and request.item_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="persist=true requires item_id"
        )
    start = time.perf_counter()
    spec = await _spec_or_404(service, taxonomy)
    classifier = _get_classifier(factory, spec, request.provider_name)
    outcome = await _classify(classifier, request.text, "Classification")
    response = _taxonomy_result(outcome, classifier, time.perf_counter() - start)
    if request.persist:
        assert request.item_id is not None
        response.persisted = await _persist(
            service, cache, taxonomy, [(request.item_id, outcome)], classifier
        )
    return response


@router.post(
    "/{taxonomy}/batch",
    response_model=TaxonomyBatchResponse,
    summary="Classify several texts into a taxonomy",
    description="""
    Up to 100 texts. `results` lists every input as `{input_index, ok, result
    | error{code, message}}` (codes: `empty_text`, `llm_error`). With
    `persist=true`, `item_ids` (same length as `texts`) are required; failed
    inputs are stored as `error` results and stay pending.
    """,
)
async def classify_taxonomy_batch(
    taxonomy: str,
    request: TaxonomyBatchRequest,
    service: ClassificationService = Depends(get_classification_service),
    factory: ClassifierFactory = Depends(get_classifier_factory),
    cache: CacheManager = Depends(get_cache_manager),
    user: dict | None = Depends(get_optional_auth),
) -> TaxonomyBatchResponse:
    """Classify several texts."""
    if request.item_ids is not None and len(request.item_ids) != len(request.texts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="item_ids must have the same length as texts",
        )
    if request.persist and request.item_ids is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="persist=true requires item_ids"
        )
    start = time.perf_counter()
    spec = await _spec_or_404(service, taxonomy)
    classifier = _get_classifier(factory, spec, request.provider_name)
    outcomes = await classifier.aclassify_many(request.texts)
    results: list[BatchItemResult] = []
    failed = 0
    for index, outcome in enumerate(outcomes):
        if outcome.succeeded:
            body = _taxonomy_result(outcome, classifier, outcome.latency_s).model_dump()
            results.append(BatchItemResult(input_index=index, ok=True, result=body))
        else:
            failed += 1
            results.append(
                BatchItemResult(input_index=index, ok=False, error=_batch_error(outcome))
            )
    persisted = None
    if request.persist:
        assert request.item_ids is not None
        persisted = await _persist(
            service,
            cache,
            taxonomy,
            list(zip(request.item_ids, outcomes, strict=True)),
            classifier,
        )
    return TaxonomyBatchResponse(
        taxonomy=spec.name,
        results=results,
        total_processed=len(request.texts),
        failed_count=failed,
        total_processing_time=time.perf_counter() - start,
        persisted=persisted,
    )
