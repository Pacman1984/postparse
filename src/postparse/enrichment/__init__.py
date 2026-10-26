"""Per-link enrichment: fetch linked pages, documents, videos and posts.

See :mod:`postparse.enrichment.fetchers` for the fetchers and
:class:`postparse.services.enrichment.EnrichmentService` for the workflow.
"""

from postparse.enrichment.options import EnrichmentOptions, default_user_agent

__all__ = ["EnrichmentOptions", "default_user_agent"]
