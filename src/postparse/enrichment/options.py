"""Link enrichment settings (``[enrichment]`` config section).

All keys are optional; the defaults below apply when a key (or the whole
section) is missing::

    [enrichment]
    concurrency = 4                   # links fetched in parallel (all domains)
    min_domain_interval = 1.0         # seconds between two requests to the same domain
    timeout = 15                      # HTTP timeout per request (seconds)
    max_body_mb = 5                   # larger HTML/text responses are skipped
    max_document_mb = 20              # larger PDF/Office documents are skipped
    max_text_chars = 20000            # stored text is cut to this length
    min_text_chars = 200              # shorter trafilatura output -> try readability too
    max_attempts = 4                  # failed links are retried this many times in total
    backoff_minutes = 60              # first retry delay; doubles per failure ...
    max_backoff_hours = 168           # ... up to this cap (7 days)
    transcript_languages = ["de", "en"]  # preferred YouTube transcript languages
    youtube_transcripts = true        # fetch YouTube transcripts (best effort)
    user_agent = ""                   # empty: "postparse/<version> (+project URL)"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from importlib import metadata
from typing import Any

__all__ = ["EnrichmentOptions", "default_user_agent"]

_PROJECT_URL = "https://github.com/sebpachl/postparse"


def default_user_agent() -> str:
    """Return the honest default User-Agent ``postparse/<version> (+<project url>)``."""
    try:
        version = metadata.version("postparse")
    except metadata.PackageNotFoundError:  # pragma: no cover - source checkout without install
        version = "0"
    return f"postparse/{version} (+{_PROJECT_URL})"


def _get(section: Any, key: str, default: Any) -> Any:
    """Read ``key`` from a mapping (``None`` / empty string -> default)."""
    if not isinstance(section, dict):
        return default
    value = section.get(key)
    return default if value is None or value == "" else value


@dataclass(frozen=True, slots=True)
class EnrichmentOptions:
    """Tunables of the link enrichment pipeline (see the module docstring for keys)."""

    concurrency: int = 4
    min_domain_interval: float = 1.0
    timeout: float = 15.0
    max_body_mb: float = 5.0
    max_document_mb: float = 20.0
    max_text_chars: int = 20_000
    min_text_chars: int = 200
    max_attempts: int = 4
    backoff_minutes: float = 60.0
    max_backoff_hours: float = 168.0
    transcript_languages: tuple[str, ...] = ("de", "en")
    youtube_transcripts: bool = True
    user_agent: str = ""

    @property
    def max_body_bytes(self) -> int:
        """HTML/text body cap in bytes."""
        return int(self.max_body_mb * 1024 * 1024)

    @property
    def max_document_bytes(self) -> int:
        """Document body cap in bytes."""
        return int(self.max_document_mb * 1024 * 1024)

    @property
    def backoff(self) -> timedelta:
        """Delay after the first failure."""
        return timedelta(minutes=self.backoff_minutes)

    @property
    def max_backoff(self) -> timedelta:
        """Upper bound of the retry delay."""
        return timedelta(hours=self.max_backoff_hours)

    @property
    def effective_user_agent(self) -> str:
        """Configured User-Agent or :func:`default_user_agent`."""
        return self.user_agent or default_user_agent()

    @classmethod
    def from_config(cls, config: Any) -> EnrichmentOptions:
        """Build options from a ``ConfigManager`` (``None``: defaults).

        Raises:
            ValueError: For non-positive concurrency or attempt counts.
        """
        section: Any = config.get_section("enrichment") if config is not None else {}
        section = section if isinstance(section, dict) else {}
        d = cls()
        languages = _get(section, "transcript_languages", d.transcript_languages)
        if isinstance(languages, str):
            languages = [part.strip() for part in languages.split(",") if part.strip()]
        options = cls(
            concurrency=int(_get(section, "concurrency", d.concurrency)),
            min_domain_interval=float(
                _get(section, "min_domain_interval", d.min_domain_interval)
            ),
            timeout=float(_get(section, "timeout", d.timeout)),
            max_body_mb=float(_get(section, "max_body_mb", d.max_body_mb)),
            max_document_mb=float(_get(section, "max_document_mb", d.max_document_mb)),
            max_text_chars=int(_get(section, "max_text_chars", d.max_text_chars)),
            min_text_chars=int(_get(section, "min_text_chars", d.min_text_chars)),
            max_attempts=int(_get(section, "max_attempts", d.max_attempts)),
            backoff_minutes=float(_get(section, "backoff_minutes", d.backoff_minutes)),
            max_backoff_hours=float(_get(section, "max_backoff_hours", d.max_backoff_hours)),
            transcript_languages=tuple(str(lang) for lang in languages),
            youtube_transcripts=bool(_get(section, "youtube_transcripts", True)),
            user_agent=str(_get(section, "user_agent", "")),
        )
        if options.concurrency < 1:
            raise ValueError("enrichment.concurrency must be at least 1")
        if options.max_attempts < 1:
            raise ValueError("enrichment.max_attempts must be at least 1")
        return options
