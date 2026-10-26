"""FetchRouter: routing, per-domain throttle (fake clock), concurrency, retry policy."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import httpx

from postparse.core.db.models import Link
from postparse.enrichment.fetchers.base import FetchResult
from postparse.enrichment.fetchers.router import DomainThrottle, FetchRouter, RetryPolicy
from postparse.enrichment.options import EnrichmentOptions
from tests.unit.enrichment.helpers import NOW


class FakeClock:
    """Monotonic fake clock; ``sleep`` advances it."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)


class RecordingFetcher:
    """Records (domain, clock time) of each fetch start and the max parallelism."""

    def __init__(
        self,
        name: str,
        clock: FakeClock,
        *,
        network: bool = True,
        domains: tuple[str, ...] = (),
        hold: float = 0.0,
    ) -> None:
        self.name = name
        self.uses_network = network
        self.clock = clock
        self.domains = domains
        self.hold = hold
        self.starts: list[tuple[str, float]] = []
        self.active = 0
        self.max_active = 0

    def matches(self, link: Link) -> bool:
        return link.domain in self.domains

    async def fetch(self, link: Link, client: httpx.AsyncClient) -> FetchResult:
        self.starts.append((link.domain, self.clock()))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        for _ in range(3):
            await asyncio.sleep(0)
        self.active -= 1
        return FetchResult("ok", text=link.url)


def links(*specs: tuple[str, int]) -> list[Link]:
    result = []
    counter = 0
    for domain, count in specs:
        for _ in range(count):
            counter += 1
            result.append(Link(counter, f"https://{domain}/{counter}", domain))
    return result


def make_router(fetchers: list[Any], default: Any, clock: FakeClock, **options: Any) -> FetchRouter:
    opts = EnrichmentOptions(**{"min_domain_interval": 1.0, "concurrency": 4, **options})
    return FetchRouter(
        fetchers,
        default,
        opts,
        clock=clock,
        sleep=clock.sleep,
        transport=httpx.MockTransport(lambda r: httpx.Response(599)),
    )


async def test_routing_first_match_then_default() -> None:
    clock = FakeClock()
    special = RecordingFetcher("special", clock, domains=("a.example",))
    default = RecordingFetcher("generic", clock)
    async with make_router([special], default, clock) as router:
        a, b = links(("a.example", 1), ("b.example", 1))
        assert router.route(a) is special and router.route(b) is default
        assert (await router.fetch(a)).fetcher == "special"
        assert (await router.fetch(b)).fetcher == "generic"


async def test_same_domain_requests_are_spaced_by_min_interval() -> None:
    clock = FakeClock()
    default = RecordingFetcher("generic", clock)
    async with make_router([], default, clock, min_domain_interval=1.5) as router:
        await asyncio.gather(
            *(router.fetch(lk) for lk in links(("a.example", 3), ("b.example", 2)))
        )
    by_domain: dict[str, list[float]] = {}
    for domain, at in default.starts:
        by_domain.setdefault(domain, []).append(at)
    for times in by_domain.values():
        gaps = [later - earlier for earlier, later in zip(times, times[1:], strict=False)]
        assert all(gap >= 1.5 - 1e-9 for gap in gaps), gaps
    # The first request of each domain does not wait.
    assert sorted(t[0] for t in by_domain.values())[0] == 1000.0
    # The shared fake clock advances while a.example waits, so b.example may not need to.
    assert router.throttle.waits and all(w <= 1.5 for w in router.throttle.waits)


async def test_offline_fetchers_are_not_throttled() -> None:
    clock = FakeClock()
    offline = RecordingFetcher("instagram", clock, network=False, domains=("instagram.com",))
    async with make_router([offline], RecordingFetcher("generic", clock), clock) as router:
        await asyncio.gather(*(router.fetch(lk) for lk in links(("instagram.com", 5))))
    assert clock.sleeps == [] and router.stats.requests == 0


async def test_global_concurrency_is_bounded() -> None:
    clock = FakeClock()
    default = RecordingFetcher("generic", clock)
    domains = [(f"d{i}.example", 1) for i in range(10)]
    async with make_router([], default, clock, concurrency=3, min_domain_interval=0) as router:
        await asyncio.gather(*(router.fetch(lk) for lk in links(*domains)))
    assert len(default.starts) == 10 and default.max_active == 3


async def test_fetcher_crash_becomes_error_result() -> None:
    class Crashing:
        name = "generic"
        uses_network = True

        def matches(self, link: Link) -> bool:
            return True

        async def fetch(self, link: Link, client: httpx.AsyncClient) -> FetchResult:
            raise KeyError("unexpected")

    clock = FakeClock()
    async with make_router([], Crashing(), clock) as router:
        result = await router.fetch(links(("a.example", 1))[0])
    assert result.status == "error" and "KeyError" in (result.error or "")
    assert result.fetcher == "generic"


async def test_overall_timeout_per_link() -> None:
    class Hanging:
        name = "slow"
        uses_network = False

        def matches(self, link: Link) -> bool:
            return True

        async def fetch(self, link: Link, client: httpx.AsyncClient) -> FetchResult:
            await asyncio.sleep(10)
            raise AssertionError("not reached")

    clock = FakeClock()
    async with make_router([], Hanging(), clock, timeout=0.01) as router:
        result = await router.fetch(links(("a.example", 1))[0])
    assert result.status == "error" and "timeout" in (result.error or "")


def test_retry_policy_exponential_backoff_and_give_up() -> None:
    policy = RetryPolicy(max_attempts=3, backoff=timedelta(hours=1), max_backoff=timedelta(hours=3))
    assert policy.delay(1) == timedelta(hours=1)
    assert policy.delay(2) == timedelta(hours=2)
    assert policy.delay(3) == timedelta(hours=3)  # capped (would be 4 h)
    last = NOW - timedelta(minutes=90)
    assert policy.is_due(1, last, NOW)  # 1 h after the first failure
    assert not policy.is_due(2, last, NOW)  # needs 2 h
    assert policy.next_attempt_at(2, last) == last + timedelta(hours=2)
    assert policy.next_attempt_at(3, last) is None
    assert not policy.is_due(3, last - timedelta(days=9), NOW)


async def test_throttle_disabled() -> None:
    clock = FakeClock()
    throttle = DomainThrottle(0, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        await throttle.wait("a.example")
    assert clock.sleeps == []
