"""Generic LLM classification into configurable taxonomies.

* :mod:`.taxonomy` — :class:`TaxonomySpec` / :class:`LabelSpec`, config loading
* :mod:`.schemas` — runtime pydantic output models (``Literal`` labels)
* :mod:`.prompts` — system instructions and the prompt hash
* :mod:`.classifier` — :class:`TaxonomyClassifier` (pydantic-ai ``Agent``)

Persistence (runs, results, pending selection) lives in
:mod:`postparse.services.classification`.
"""

from postparse.classification.classifier import (
    ClassificationError,
    ClassificationOutcome,
    TaxonomyClassifier,
)
from postparse.classification.prompts import build_instructions, prompt_sha256
from postparse.classification.schemas import build_output_model
from postparse.classification.taxonomy import (
    DEFAULT_TAXONOMY,
    LabelSpec,
    TaxonomySpec,
    load_taxonomies,
    spec_from_db,
)

__all__ = [
    "DEFAULT_TAXONOMY",
    "ClassificationError",
    "ClassificationOutcome",
    "LabelSpec",
    "TaxonomyClassifier",
    "TaxonomySpec",
    "build_instructions",
    "build_output_model",
    "load_taxonomies",
    "prompt_sha256",
    "spec_from_db",
]
