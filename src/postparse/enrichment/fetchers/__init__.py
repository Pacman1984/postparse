"""Link fetchers: generic pages, documents, YouTube, X, Instagram (skipped), router."""

from postparse.enrichment.fetchers.base import Fetcher, FetchResult
from postparse.enrichment.fetchers.documents import DocumentFetcher
from postparse.enrichment.fetchers.generic import GenericFetcher
from postparse.enrichment.fetchers.instagram import InstagramFetcher
from postparse.enrichment.fetchers.router import (
    DomainThrottle,
    FetchRouter,
    RetryPolicy,
    default_fetchers,
)
from postparse.enrichment.fetchers.x import XFetcher
from postparse.enrichment.fetchers.youtube import YouTubeFetcher

__all__ = [
    "DocumentFetcher",
    "DomainThrottle",
    "FetchResult",
    "FetchRouter",
    "Fetcher",
    "GenericFetcher",
    "InstagramFetcher",
    "RetryPolicy",
    "XFetcher",
    "YouTubeFetcher",
    "default_fetchers",
]
