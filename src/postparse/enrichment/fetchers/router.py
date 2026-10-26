"""Route links to fetchers, throttle per domain, bound concurrency, retry policy.

:class:`FetchRouter` picks the first fetcher whose ``matches`` accepts a link
(Instagram -> skipped, YouTube videos, X posts, document URLs) and falls back
to the generic fetcher. It owns the shared ``httpx.AsyncClient`` (honest
User-Agent, redirects followed, per-request timeout) and

* limits the number of links in flight (``concurrency``, default 4);
* keeps at least ``min_domain_interval`` seconds (default 1 s) between two
  requests to the same domain (:class:`DomainThrottle`);
* bounds the total time per link (4x the request timeout);
* converts every exception into an ``error`` result.

:class:`RetryPolicy` decides when a link whose last fetch failed is due again:
exponential backoff from the last attempt (``backoff`` x 2^(failures-1), capped
at ``max_backoff``), giving up after ``max_attempts`` failures in a row.

Example:
    >>> async with FetchRouter.default_router(options) as router:
    ...     result = await router.fetch(link)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx

from postparse.core.db.models import Link
from postparse.enrichment.fetchers.base import Fetcher, FetchResult
from postparse.enrichment.fetchers.documents import DocumentFetcher
from postparse.enrichment.fetchers.generic import GenericFetcher
from postparse.enrichment.fetchers.instagram import InstagramFetcher
from postparse.enrichment.fetchers.x import XFetcher
from postparse.enrichment.fetchers.youtube import YouTubeFetcher
from postparse.enrichment.options import EnrichmentOptions

__all__ = ["DomainThrottle", "FetchRouter", "RetryPolicy", "default_fetchers"]

logger = logging.getLogger(__name__)

Clock = Callable[[], float]
AsyncSleep = Callable[[float], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff for failed links.

    Attributes:
        max_attempts: Give up after this many failures in a row.
        backoff: Delay after the first failure.
        max_backoff: Upper bound of the delay.
    """

    max_attempts: int = 4
    backoff: timedelta = timedelta(hours=1)
    max_backoff: timedelta = timedelta(days=7)

    @classmethod
    def from_options(cls, options: EnrichmentOptions) -> RetryPolicy:
        """Build from :class:`EnrichmentOptions`."""
        return cls(options.max_attempts, options.backoff, options.max_backoff)

    def delay(self, failures: int) -> timedelta:
        """Delay after ``failures`` consecutive failures (>= 1)."""
        factor = 2 ** max(failures - 1, 0)
        delay: timedelta = min(self.backoff * factor, self.max_backoff)
        return delay

    def exhausted(self, failures: int) -> bool:
        """True once ``failures`` reached ``max_attempts``."""
        return failures >= self.max_attempts

    def next_attempt_at(self, failures: int, last_attempt: datetime) -> datetime | None:
        """When the link is due again (``None``: gave up)."""
        if self.exhausted(failures):
            return None
        return last_attempt + self.delay(failures)

    def is_due(self, failures: int, last_attempt: datetime, now: datetime) -> bool:
        """True if a link with ``failures`` failures, last at ``last_attempt``, is due."""
        due = self.next_attempt_at(failures, last_attempt)
        return due is not None and due <= now


class DomainThrottle:
    """Keep ``min_interval`` seconds between request starts per domain.

    Args:
        min_interval: Seconds between two requests to one domain (``<= 0``: off).
        clock: Monotonic clock (tests pass a fake).
        sleep: Async sleep (tests pass one that advances the fake clock).
    """

    def __init__(
        self,
        min_interval: float,
        *,
        clock: Clock = time.monotonic,
        sleep: AsyncSleep = asyncio.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._next: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        #: Delays waited so far (for statistics and tests).
        self.waits: list[float] = []

    async def wait(self, domain: str) -> None:
        """Wait until a request to ``domain`` may start and reserve that slot."""
        if self.min_interval <= 0:
            return
        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            now = self._clock()
            ready = self._next.get(domain, now)
            if ready > now:
                delay = ready - now
                self.waits.append(delay)
                await self._sleep(delay)
            self._next[domain] = max(self._clock(), ready) + self.min_interval


def default_fetchers(options: EnrichmentOptions | None = None) -> list[Fetcher]:
    """Specialized fetchers in routing order (the generic fetcher is the fallback)."""
    options = options or EnrichmentOptions()
    return [
        InstagramFetcher(),
        YouTubeFetcher(options),
        XFetcher(),
        DocumentFetcher(options),
    ]


@dataclass(slots=True)
class _Stats:
    requests: int = 0
    by_fetcher: dict[str, int] = field(default_factory=dict)


class FetchRouter:
    """Dispatch links to fetchers with throttling and bounded concurrency.

    Args:
        fetchers: Specialized fetchers, first match wins.
        default: Fallback fetcher (generic).
        options: Concurrency, domain interval, timeout, User-Agent.
        client: Shared HTTP client (default: created on ``__aenter__``).
        transport: Transport for the created client (tests).
        clock: Monotonic clock for the throttle.
        sleep: Async sleep for the throttle.
    """

    def __init__(
        self,
        fetchers: Sequence[Fetcher],
        default: Fetcher,
        options: EnrichmentOptions | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Clock = time.monotonic,
        sleep: AsyncSleep = asyncio.sleep,
    ) -> None:
        self.fetchers = list(fetchers)
        self.default = default
        self.options = options or EnrichmentOptions()
        self._client = client
        self._owns_client = client is None
        self._transport = transport
        self.throttle = DomainThrottle(self.options.min_domain_interval, clock=clock, sleep=sleep)
        self._semaphore = asyncio.Semaphore(self.options.concurrency)
        self.stats = _Stats()

    @classmethod
    def default_router(cls, options: EnrichmentOptions | None = None, **kwargs: Any) -> FetchRouter:
        """Router with :func:`default_fetchers` and the generic fallback."""
        options = options or EnrichmentOptions()
        return cls(default_fetchers(options), GenericFetcher(options), options, **kwargs)

    async def __aenter__(self) -> FetchRouter:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.options.timeout,
                follow_redirects=True,
                max_redirects=10,
                headers={
                    "User-Agent": self.options.effective_user_agent,
                    "Accept-Language": "de,en;q=0.8,*;q=0.5",
                },
                transport=self._transport,
            )
            self._owns_client = True
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """The shared HTTP client (inside ``async with``)."""
        if self._client is None:
            raise RuntimeError("FetchRouter must be used as 'async with'")
        return self._client

    def route(self, link: Link) -> Fetcher:
        """Return the fetcher for ``link``."""
        for fetcher in self.fetchers:
            if fetcher.matches(link):
                return fetcher
        return self.default

    async def fetch(self, link: Link) -> FetchResult:
        """Fetch one link; never raises (errors become ``error`` results)."""
        fetcher = self.route(link)
        async with self._semaphore:
            if fetcher.uses_network:
                await self.throttle.wait(link.domain)
                self.stats.requests += 1
            self.stats.by_fetcher[fetcher.name] = self.stats.by_fetcher.get(fetcher.name, 0) + 1
            try:
                result = await asyncio.wait_for(
                    fetcher.fetch(link, self.client), timeout=self.options.timeout * 4
                )
            except (httpx.TimeoutException, TimeoutError) as exc:
                result = FetchResult.failed(f"timeout ({type(exc).__name__})")
            except httpx.TooManyRedirects:
                result = FetchResult.failed("too many redirects")
            except httpx.HTTPError as exc:
                result = FetchResult.failed(f"{type(exc).__name__}: {exc}"[:500])
            except Exception as exc:
                logger.warning("Fetcher %s crashed on %s", fetcher.name, link.url, exc_info=True)
                result = FetchResult.failed(f"{type(exc).__name__}: {exc}"[:500])
        if not result.fetcher:
            result.fetcher = fetcher.name
        return result
