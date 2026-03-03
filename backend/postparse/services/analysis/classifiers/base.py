from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class ClassificationResult(BaseModel):
    """Base model for single-label classification results.

    Attributes:
        label: Classification label (e.g. 'recipe', 'tech_news').
        confidence: Confidence score between 0.0 and 1.0.
        details: Additional classification details (reasoning, metadata, etc.).

    Example:
        >>> result = ClassificationResult(label="recipe", confidence=0.95)
    """

    label: str
    confidence: float
    details: Optional[Dict[str, Any]] = None


class LabelScore(BaseModel):
    """A single label with its confidence score for multi-label classification.

    Attributes:
        label: Classification label name.
        confidence: Confidence score between 0.0 and 1.0.

    Example:
        >>> score = LabelScore(label="recipe", confidence=0.95)
    """

    label: str = Field(..., description="Classification label name")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)"
    )


class MultiLabelClassificationResult(BaseModel):
    """Result model for multi-label classification (multiple labels per item).

    Attributes:
        labels: List of matching labels with individual confidence scores.
        reasoning: LLM's explanation for the assigned labels.
        available_classes: All class names that were available for assignment.

    Example:
        >>> result = MultiLabelClassificationResult(
        ...     labels=[
        ...         LabelScore(label="recipe", confidence=0.95),
        ...         LabelScore(label="cocktail", confidence=0.88),
        ...     ],
        ...     reasoning="Contains cocktail mixing instructions",
        ...     available_classes=["recipe", "cocktail", "restaurant", "other"],
        ... )
    """

    labels: List[LabelScore] = Field(
        default_factory=list,
        description="Matching labels with confidence scores",
    )
    reasoning: Optional[str] = Field(
        None, description="LLM's explanation for the classification"
    )
    available_classes: List[str] = Field(
        default_factory=list,
        description="All class names available for assignment",
    )


class BaseClassifier(ABC):
    """Base classifier interface.

    All classifiers must implement ``fit`` and ``predict``.
    ``predict_batch`` is provided as a default sequential implementation.
    """

    @abstractmethod
    def fit(self, X: Any, y: Optional[Any] = None) -> 'BaseClassifier':
        """Fit the classifier with training data.

        Args:
            X: Training data.
            y: Target values (optional for some classifiers).

        Returns:
            self: The fitted classifier.
        """
        pass

    @abstractmethod
    def predict(self, X: Any) -> ClassificationResult:
        """Make predictions on input data.

        Args:
            X: Input data to classify.

        Returns:
            ClassificationResult with label and confidence.
        """
        pass

    def predict_batch(self, X: list[Any]) -> list[ClassificationResult]:
        """Make predictions on a batch of inputs.

        Args:
            X: List of input data to classify.

        Returns:
            list[ClassificationResult]: List of classification results.
        """
        return [self.predict(x) for x in X]