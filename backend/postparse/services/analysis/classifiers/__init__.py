"""Classification models for recipe detection, multi-class, and multi-label analysis.

This module provides classifiers for detecting and analyzing content
from social media posts and messages using LangChain + LiteLLM.

The classifiers use:
- **LangChain**: For PydanticOutputParser, prompts, and structured outputs
- **LiteLLM**: As universal adapter supporting ANY LLM provider

Available Classifiers:
    - **RecipeLLMClassifier**: Binary recipe classification (recipe / not_recipe)
    - **MultiClassLLMClassifier**: Single-label with dynamic categories (picks 1)
    - **MultiLabelLLMClassifier**: Multi-label with dynamic categories (picks 0..N)

Example:
    Multi-label classification:

    ```python
    from postparse.services.analysis.classifiers import MultiLabelLLMClassifier

    classifier = MultiLabelLLMClassifier()
    result = classifier.predict_multilabel("Mojito recipe at the beach bar!")
    for lbl in result.labels:
        print(f"{lbl.label}: {lbl.confidence:.0%}")
    # cocktail: 95%
    # recipe: 88%
    # bar_cafe: 72%
    ```
"""

from backend.postparse.services.analysis.classifiers.base import (
    BaseClassifier,
    ClassificationResult,
    LabelScore,
    MultiLabelClassificationResult,
)
from backend.postparse.services.analysis.classifiers.llm import (
    RecipeLLMClassifier,
    RecipeDetails,
)
from backend.postparse.services.analysis.classifiers.multi_class import (
    MultiClassLLMClassifier,
    MultiClassResult,
)
from backend.postparse.services.analysis.classifiers.multi_label import (
    MultiLabelLLMClassifier,
    MultiLabelLLMResult,
)

__all__ = [
    "BaseClassifier",
    "ClassificationResult",
    "LabelScore",
    "MultiLabelClassificationResult",
    "RecipeLLMClassifier",
    "RecipeDetails",
    "MultiClassLLMClassifier",
    "MultiClassResult",
    "MultiLabelLLMClassifier",
    "MultiLabelLLMResult",
]

