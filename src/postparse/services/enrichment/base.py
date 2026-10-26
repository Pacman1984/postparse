"""Base enricher interface for the content enhancement pipeline.

This module defines the abstract base class that all concrete enrichers
must implement, as well as the ``EnrichmentResult`` data model.

Future enricher implementations:
- ``YouTubeEnricher``: Watch/transcribe YouTube videos, generate summaries
- ``LinkScraper``: Extract content from web links
- ``Summarizer``: Generate concise summaries of long texts
- ``Translator``: Translate content between languages
- ``EntityExtractor``: Extract named entities (people, places, products)

Example:
    ```python
    class YouTubeEnricher(BaseEnricher):
        def enrich(self, content, source_url=None):
            transcript = download_transcript(source_url)
            summary = self.llm.summarize(transcript)
            return EnrichmentResult(
                enrichment_type="summary",
                enricher_name="youtube_analyzer",
                generated_text=summary,
                source_url=source_url,
                metadata={"duration_seconds": 360},
            )
    ```
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EnrichmentResult(BaseModel):
    """Result model for a single content enrichment.

    Attributes:
        enrichment_type: Type of enrichment produced (e.g. 'summary',
            'description', 'transcript', 'translation', 'entities').
        enricher_name: Name of the enricher that produced this result.
        generated_text: The main enrichment output text.
        source_url: URL that was analyzed, if applicable.
        metadata: Additional structured data (duration, language, etc.).

    Example:
        >>> result = EnrichmentResult(
        ...     enrichment_type="summary",
        ...     enricher_name="youtube_analyzer",
        ...     generated_text="Tutorial on fine-tuning Qwen3 with LoRA...",
        ...     source_url="https://youtube.com/watch?v=abc",
        ...     metadata={"duration_seconds": 600, "language": "en"},
        ... )
    """

    enrichment_type: str = Field(
        ..., description="Type of enrichment (summary, description, etc.)"
    )
    enricher_name: str = Field(
        ..., description="Name of the enricher that produced this"
    )
    generated_text: str = Field(
        ..., description="Main enrichment output text"
    )
    source_url: Optional[str] = Field(
        None, description="URL that was analyzed"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Additional structured data"
    )


class BaseEnricher(ABC):
    """Abstract base class for content enrichers.

    All concrete enrichers (YouTubeEnricher, Summarizer, etc.) must
    implement the ``enrich`` method. The pipeline will call this method
    for each content item and store the result via
    ``SocialMediaDatabase.save_enrichment()``.

    Example:
        ```python
        class MySummarizer(BaseEnricher):
            def enrich(self, content, source_url=None):
                summary = my_llm.summarize(content)
                return EnrichmentResult(
                    enrichment_type="summary",
                    enricher_name="my_summarizer",
                    generated_text=summary,
                )
        ```
    """

    @abstractmethod
    def enrich(
        self,
        content: str,
        source_url: Optional[str] = None,
    ) -> EnrichmentResult:
        """Enrich a single content item.

        Args:
            content: The text content to enrich.
            source_url: Optional URL associated with the content
                (e.g. a YouTube link in a Telegram message).

        Returns:
            EnrichmentResult with generated text and metadata.
        """
        pass
