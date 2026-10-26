"""Generic background job runner for the API.

:class:`JobRunner` runs one service call per job on top of the existing
:class:`~postparse.api.services.job_manager.JobManager` (state) and
:class:`~postparse.api.services.websocket_manager.WebSocketManager` (live
events):

* ``submit(kind, params, coro_factory)`` creates the job and schedules
  ``coro_factory(progress)`` as an asyncio task. Blocking service calls are
  wrapped with :func:`in_thread` (``anyio.to_thread.run_sync``), so the event
  loop never runs sqlite or HTTP work itself.
* ``progress(processed, total, message)`` may be called from any thread. Each
  call updates the job and queues a WebSocket event; one sender task per job
  delivers the events in order.
* Errors become failed jobs with an ``error_code``: typed collector errors
  (:class:`AuthRequired`, :class:`RateLimited`), reports whose
  ``stopped_reason`` signals a hard stop (``auth_required``,
  ``rate_limited``, ``suspected_block``, ``backend_unavailable``) and any
  other exception (``internal_error``).
* The response cache is invalidated after every job, because even a partial
  run may have committed data.

Example:
    >>> job_id = runner.submit(
    ...     "transcribe", {"limit": 5},
    ...     in_thread(lambda progress: service.run(limit=5, progress=adapt(progress))),
    ... )
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, get_args

import anyio

from postparse.api.schemas.telegram import ExtractionStatus
from postparse.api.services.job_manager import JobManager
from postparse.api.services.websocket_manager import WebSocketManager

__all__ = [
    "FAILURE_STOP_REASONS",
    "JOB_KINDS",
    "CoroFactory",
    "JobKind",
    "JobRunner",
    "ProgressSink",
    "error_code_for",
    "in_thread",
    "report_to_dict",
]

logger = logging.getLogger(__name__)

JobKind = Literal[
    "telegram_extract", "instagram_extract", "transcribe", "summarize", "enrich", "classify"
]
JOB_KINDS: tuple[str, ...] = get_args(JobKind)

#: ``progress(processed, total=None, message=None)``; safe to call from any thread.
ProgressSink = Callable[..., None]
#: ``coro_factory(progress) -> awaitable service result``.
CoroFactory = Callable[[ProgressSink], Awaitable[Any]]

#: Report ``stopped_reason`` values that turn a returned report into a failed job.
FAILURE_STOP_REASONS: frozenset[str] = frozenset(
    {"auth_required", "rate_limited", "suspected_block", "backend_unavailable"}
)

_PROCESSED_KEYS = ("processed", "handled", "classified", "summarized")


def error_code_for(exc: BaseException) -> str:
    """Map an exception raised by a service to a job ``error_code``."""
    from postparse.collectors.base import AuthRequired, CredentialsMissing, RateLimited

    if isinstance(exc, CredentialsMissing):
        return "credentials_missing"
    if isinstance(exc, AuthRequired):
        return "auth_required"
    if isinstance(exc, RateLimited):
        return "rate_limited"
    name = type(exc).__name__
    if name in ("BackendUnavailable",):
        return "backend_unavailable"
    if name in ("ClassificationError", "SummarizationError") or name.startswith("LLM"):
        return "llm_error"
    if isinstance(exc, (KeyError, ValueError)):
        return "invalid_request"
    return "internal_error"


def report_to_dict(result: Any) -> dict[str, Any] | None:
    """Turn a service report into a JSON-serializable dict."""
    if result is None:
        return None
    if isinstance(result, Mapping):
        return dict(result)
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        return dataclasses.asdict(result)
    return {"value": str(result)}


def in_thread(func: Callable[[ProgressSink], Any]) -> CoroFactory:
    """Wrap a blocking ``func(progress)`` so it runs in a worker thread.

    Args:
        func: Blocking callable receiving the progress sink.

    Returns:
        Coroutine factory for :meth:`JobRunner.submit`.
    """

    async def factory(progress: ProgressSink) -> Any:
        return await anyio.to_thread.run_sync(func, progress)

    return factory


def _processed(data: Mapping[str, Any] | None, fallback: int) -> int:
    if data:
        for key in _PROCESSED_KEYS:
            value = data.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return max(value, 0)
    return fallback


class JobRunner:
    """Run service calls as tracked background jobs.

    Args:
        jobs: Job state store.
        ws: WebSocket broadcaster.
        cache: Response cache to invalidate after jobs (``None``: no cache).
    """

    def __init__(
        self, jobs: JobManager, ws: WebSocketManager, cache: Any = None
    ) -> None:
        self.jobs = jobs
        self.ws = ws
        self.cache = cache
        self._tasks: dict[str, asyncio.Task[None]] = {}

    # -- public API -----------------------------------------------------------

    def submit(
        self,
        kind: JobKind | str,
        params: Mapping[str, Any],
        coro_factory: CoroFactory,
        *,
        total: int | None = None,
    ) -> str:
        """Create a job and start it in the background.

        Must be called from the running event loop (an ``async`` endpoint).

        Args:
            kind: Job kind (one of :data:`JOB_KINDS`).
            params: Non-sensitive request parameters stored with the job
                (credential-like keys are removed by the job manager).
            coro_factory: ``factory(progress)`` returning the service result.
            total: Expected number of items, if known up front.

        Returns:
            The new job id.

        Raises:
            ValueError: For an unknown job kind.
        """
        if kind not in JOB_KINDS:
            raise ValueError(f"Unknown job kind: {kind!r}")
        loop = asyncio.get_running_loop()
        job_id = self.jobs.create_job(kind, dict(params))
        if total is not None:
            job = self.jobs.get_job(job_id)
            if job is not None:
                job.total = total
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        task = loop.create_task(
            self._run(job_id, coro_factory, queue, loop, threading.get_ident()),
            name=f"job-{kind}-{job_id}",
        )
        self._tasks[job_id] = task
        task.add_done_callback(lambda _t, jid=job_id: self._tasks.pop(jid, None))
        logger.info("Started %s job %s", kind, job_id)
        return job_id

    async def wait(self, job_id: str, timeout: float | None = None) -> None:
        """Wait until a job has finished (no-op for unknown/finished jobs)."""
        task = self._tasks.get(job_id)
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), timeout)

    async def wait_all(self, timeout: float | None = None) -> None:
        """Wait for every running job."""
        tasks = list(self._tasks.values())
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout)

    @property
    def running(self) -> list[str]:
        """Ids of jobs that have not finished yet."""
        return list(self._tasks)

    async def shutdown(self) -> None:
        """Cancel running jobs (worker threads finish their current step)."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # -- internals ------------------------------------------------------------

    def _make_sink(
        self,
        job_id: str,
        queue: asyncio.Queue[dict[str, Any] | None],
        loop: asyncio.AbstractEventLoop,
        loop_thread: int,
    ) -> ProgressSink:
        def post(payload: dict[str, Any]) -> None:
            if threading.get_ident() == loop_thread:
                queue.put_nowait(payload)
            elif not loop.is_closed():
                loop.call_soon_threadsafe(queue.put_nowait, payload)

        def progress(processed: int, total: int | None = None, message: str | None = None) -> None:
            try:
                job = self.jobs.set_progress(job_id, processed, total, message)
                post(job.to_dict())
            except Exception:  # noqa: BLE001 - progress must never break a service run
                logger.exception("Progress update for job %s failed", job_id)

        progress.post = post  # type: ignore[attr-defined]
        return progress

    async def _send_events(
        self, job_id: str, queue: asyncio.Queue[dict[str, Any] | None]
    ) -> None:
        while True:
            payload = await queue.get()
            if payload is None:
                return
            try:
                await self.ws.broadcast_progress(job_id, payload)
            except Exception:  # noqa: BLE001
                logger.exception("WebSocket broadcast for job %s failed", job_id)

    async def _run(
        self,
        job_id: str,
        coro_factory: CoroFactory,
        queue: asyncio.Queue[dict[str, Any] | None],
        loop: asyncio.AbstractEventLoop,
        loop_thread: int,
    ) -> None:
        sink = self._make_sink(job_id, queue, loop, loop_thread)
        post: Callable[[dict[str, Any]], None] = sink.post  # type: ignore[attr-defined]
        sender = loop.create_task(self._send_events(job_id, queue))
        job = self.jobs.get_job(job_id)
        assert job is not None
        self.jobs.update_job_status(job_id, ExtractionStatus.RUNNING, 0, 0)
        post(job.to_dict())
        try:
            result = await coro_factory(sink)
            data = report_to_dict(result)
            processed = _processed(data, job.messages_processed)
            reason = (data or {}).get("stopped_reason")
            if reason in FAILURE_STOP_REASONS:
                message = (data or {}).get("error") or str(reason).replace("_", " ")
                self.jobs.mark_job_failed(
                    job_id, str(message), error_code=str(reason), result=data,
                    messages_processed=processed,
                )
            else:
                self.jobs.mark_job_completed(job_id, processed, result=data)
        except asyncio.CancelledError:
            self.jobs.mark_job_failed(job_id, "Job cancelled", error_code="cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - every failure becomes a failed job
            code = error_code_for(exc)
            if code == "internal_error":
                logger.exception("Job %s failed", job_id)
            else:
                logger.warning("Job %s failed (%s): %s", job_id, code, exc)
            self.jobs.mark_job_failed(job_id, str(exc) or type(exc).__name__, error_code=code)
        finally:
            await self._invalidate_cache()
            post(job.to_dict())
            queue.put_nowait(None)
            with contextlib.suppress(asyncio.CancelledError):
                await sender

    async def _invalidate_cache(self) -> None:
        if self.cache is None:
            return
        try:
            await anyio.to_thread.run_sync(self.cache.invalidate)
        except Exception:  # noqa: BLE001
            logger.exception("Cache invalidation after job failed")
