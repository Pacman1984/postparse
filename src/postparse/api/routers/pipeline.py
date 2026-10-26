"""Processing endpoints: statistics, taxonomies and the transcription /
summarization / enrichment jobs (the CLI's ``stats``, ``classify taxonomies``,
``transcribe``, ``summarize`` and ``enrich`` commands).

Jobs return ``202`` with a ``job_id``; follow them with
``GET /api/v1/jobs/{job_id}`` or ``WS /api/v1/jobs/{job_id}/ws``.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import APIRouter, Depends, Query, status

from postparse.api.dependencies import (
    get_classification_service,
    get_enrichment_service,
    get_job_runner,
    get_optional_auth,
    get_services,
    get_summarization_service,
    get_transcription_service,
)
from postparse.api.deps import ApiServices
from postparse.api.jobs.kinds import enrich_job, summarize_job, transcribe_job
from postparse.api.jobs.runner import JobRunner
from postparse.api.routers._common import accepted
from postparse.api.schemas.pipeline import (
    EnrichmentRunRequest,
    JobAcceptedResponse,
    SummariesRunRequest,
    TranscriptionRunRequest,
    drop_none,
)
from postparse.services.classification import ClassificationService
from postparse.services.enrichment import EnrichmentService
from postparse.services.stats import collect_stats
from postparse.services.summarization import SummarizationService
from postparse.services.transcription import TranscriptionService

router = APIRouter(prefix="/api/v1", tags=["pipeline"])


@router.get(
    "/stats",
    summary="Database statistics",
    description="Same snapshot as `postparse stats --json` (counts per source and kind, "
    "tags, transcription queue, links, summaries, classification coverage).",
)
def get_stats(
    with_pending: bool = Query(default=True, description="Count pending items per taxonomy"),
    services: ApiServices = Depends(get_services),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> dict[str, Any]:
    """Return database statistics."""
    max_attempts = services.transcription.options.max_attempts
    stats = collect_stats(services.db, max_attempts=max_attempts, with_pending=with_pending)
    return stats.to_dict()


@router.get(
    "/taxonomies",
    summary="List taxonomies",
    description="Configured and stored taxonomies with versions, label sets and result counts.",
)
def list_taxonomies(
    classification: ClassificationService = Depends(get_classification_service),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> dict[str, list[dict[str, Any]]]:
    """Return the taxonomies."""
    infos = classification.list_taxonomies()
    return {"taxonomies": [dataclasses.asdict(info) for info in infos]}


# -- transcription ------------------------------------------------------------


@router.post(
    "/transcription/run",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a transcription job",
    description="""
    Transcribe due media (`postparse transcribe run`). Never prompts for an
    Instagram login; missing logins, rate limits, suspected blocks and an
    unavailable ASR backend fail the job with the matching `error_code`
    (committed transcripts are kept).
    """,
)
async def run_transcription(
    request: TranscriptionRunRequest,
    transcription: TranscriptionService = Depends(get_transcription_service),
    runner: JobRunner = Depends(get_job_runner),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> JobAcceptedResponse:
    """Start the job."""
    source = None if request.source == "all" else request.source
    job_id = runner.submit(
        "transcribe",
        drop_none(request.model_dump()),
        transcribe_job(
            transcription, source=source, limit=request.limit, backend=request.backend,
            refetch=request.refetch, item_ids=request.item_ids,
        ),
        total=request.limit,
    )
    return accepted(job_id, "transcribe")


@router.get(
    "/transcription/status",
    summary="Transcription queue and backend status",
    description="Queue counts per source and status, due/exhausted media and the "
    "configured backend (checked without loading a model).",
)
def transcription_status(
    transcription: TranscriptionService = Depends(get_transcription_service),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> dict[str, Any]:
    """Return the queue statistics."""
    stats = transcription.status()
    counts: dict[tuple[str, str], int] = stats.pop("counts", {})
    by_source: dict[str, dict[str, int]] = {}
    for (source, state), n in counts.items():
        by_source.setdefault(source, {})[state] = n
    return {"status": by_source, **stats, "backend": backend_status(transcription)}


def backend_status(transcription: TranscriptionService) -> dict[str, Any]:
    """Check the configured ASR backend cheaply (no model load, no request)."""
    try:
        backend = transcription.backend()
        backend.check()
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return {"kind": transcription.options.backend, "status": "unavailable",
                "error": str(exc)}
    return {"kind": transcription.options.backend, "status": "available",
            "name": getattr(backend, "name", None), "model": getattr(backend, "model", None)}


# -- summaries ---------------------------------------------------------------


@router.post(
    "/summaries/run",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a summarization job",
    description="Summarize transcribed items without a current summary "
    "(`postparse summarize run`).",
)
async def run_summaries(
    request: SummariesRunRequest,
    summarization: SummarizationService = Depends(get_summarization_service),
    runner: JobRunner = Depends(get_job_runner),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> JobAcceptedResponse:
    """Start the job."""
    job_id = runner.submit(
        "summarize",
        drop_none(request.model_dump()),
        summarize_job(
            summarization, limit=request.limit, provider=request.provider,
            force=request.force, item_ids=request.item_ids,
        ),
        total=request.limit,
    )
    return accepted(job_id, "summarize")


# -- enrichment ----------------------------------------------------------------


@router.post(
    "/enrichment/run",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a link enrichment job",
    description="Fetch due links and store their texts (`postparse enrich run`).",
)
async def run_enrichment(
    request: EnrichmentRunRequest,
    enrichment: EnrichmentService = Depends(get_enrichment_service),
    runner: JobRunner = Depends(get_job_runner),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> JobAcceptedResponse:
    """Start the job."""
    job_id = runner.submit(
        "enrich",
        drop_none(request.model_dump()),
        enrich_job(
            enrichment, source=request.source, limit=request.limit, force=request.force,
            refresh_legacy=request.refresh_legacy, domains=request.domains,
        ),
        total=request.limit,
    )
    return accepted(job_id, "enrich")


@router.get(
    "/enrichment/status",
    summary="Link enrichment status",
    description="Links per fetcher/status, top domains, due and retry counts.",
)
def enrichment_status(
    source: str = Query(default="all", pattern="^(all|telegram|instagram)$"),
    top_domains: int = Query(default=15, ge=1, le=200),
    enrichment: EnrichmentService = Depends(get_enrichment_service),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> dict[str, Any]:
    """Return enrichment statistics."""
    data = enrichment.status(source=source, top_domains=top_domains)  # type: ignore[arg-type]
    by_state = data.pop("by_state", {})
    domains = data.pop("domains", [])
    return {
        **data,
        "by_state": [
            {"fetcher": fetcher, "status": state, "count": n}
            for (fetcher, state), n in sorted(by_state.items())
        ],
        "domains": [{"domain": domain, "states": states} for domain, states in domains],
    }
