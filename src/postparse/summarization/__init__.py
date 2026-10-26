"""Short LLM summaries of transcribed items (pydantic-ai).

* :class:`~postparse.summarization.summarizer.Summarizer` -- agent producing
  :class:`~postparse.summarization.schemas.SummaryOutput` (2-5 sentence summary
  in the content's language plus up to five key points).
* :func:`format_summary_text` / :func:`parse_summary_text` -- the stored text
  format (summary paragraph, blank line, ``- `` bullet per key point).

The workflow over the database lives in :mod:`postparse.services.summarization`.
"""

from postparse.summarization.schemas import (
    MAX_KEY_POINTS,
    SummaryOutput,
    format_summary_text,
    parse_summary_text,
)
from postparse.summarization.summarizer import (
    SummarizationError,
    Summarizer,
    SummaryOutcome,
)

__all__ = [
    "MAX_KEY_POINTS",
    "SummarizationError",
    "Summarizer",
    "SummaryOutcome",
    "SummaryOutput",
    "format_summary_text",
    "parse_summary_text",
]
