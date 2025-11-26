"""
Pydantic schemas for classification endpoints.

This module defines request/response models for recipe classification and
multi-class classification, wrapping the ClassificationResult from classifiers.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator


class ClassifierType(str, Enum):
    """
    Type of classifier to use.

    Values:
        LLM: RecipeLLMClassifier (LLM-based recipe classification).
        MULTI_CLASS: MultiClassLLMClassifier (LLM-based multi-class classification).
    """

    LLM = "llm"
    MULTI_CLASS = "multi_class"


class ClassifyRequest(BaseModel):
    """
    Request schema for single text classification.

    Attributes:
        text: Content to classify (recipe vs non-recipe).
        classifier_type: Which classifier to use ('llm').
        provider_name: LLM provider name (for LLM classifier).

    Example:
        {
            "text": "Boil pasta for 10 minutes, drain, add tomato sauce and basil",
            "classifier_type": "llm",
            "provider_name": "lm_studio"
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "text": "Boil pasta for 10 minutes, drain, add tomato sauce and basil",
                "classifier_type": "llm",
                "provider_name": "lm_studio"
            },
            {
                "text": "Just finished watching a great movie!",
                "classifier_type": "llm",
                "provider_name": "lm_studio"
            }
        ]
    })

    text: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Content to classify",
        examples=["Boil pasta for 10 minutes, drain, add tomato sauce and basil"]
    )
    classifier_type: ClassifierType = Field(
        default=ClassifierType.LLM,
        description="Classifier to use"
    )
    provider_name: Optional[str] = Field(
        default=None,
        description="LLM provider name (for LLM classifier)",
        examples=["ollama", "openai", "anthropic"]
    )

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        """Validate that text is not empty or whitespace only."""
        if not v.strip():
            raise ValueError("Text cannot be empty or whitespace only")
        return v


class ClassifyResponse(BaseModel):
    """
    Response schema for classification results.

    Wraps ClassificationResult with additional metadata.

    Attributes:
        label: Classification label ('recipe' or 'non_recipe').
        confidence: Confidence score (0.0 to 1.0).
        details: Additional classification details (cuisine, difficulty, etc.).
        processing_time: Time taken to classify (seconds).
        classifier_used: Which classifier was used.

    Example:
        {
            "label": "recipe",
            "confidence": 0.95,
            "details": {
                "cuisine_type": "italian",
                "difficulty": "easy",
                "meal_type": "dinner",
                "ingredients_count": 5
            },
            "processing_time": 0.234,
            "classifier_used": "llm"
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "label": "recipe",
                "confidence": 0.95,
                "details": {
                    "cuisine_type": "italian",
                    "difficulty": "easy",
                    "meal_type": "dinner",
                    "ingredients_count": 5
                },
                "processing_time": 0.234,
                "classifier_used": "llm"
            },
            {
                "label": "non_recipe",
                "confidence": 0.88,
                "details": {},
                "processing_time": 0.156,
                "classifier_used": "llm"
            }
        ]
    })

    label: str = Field(
        ...,
        description="Classification label",
        examples=["recipe", "non_recipe"]
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score"
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional classification details"
    )
    processing_time: float = Field(
        ...,
        ge=0.0,
        description="Processing time in seconds"
    )
    classifier_used: str = Field(
        ...,
        description="Which classifier was used",
        examples=["llm"]
    )


class BatchClassifyRequest(BaseModel):
    """
    Request schema for batch text classification.

    Attributes:
        texts: List of texts to classify.
        classifier_type: Which classifier to use ('llm').
        provider_name: LLM provider name (for LLM classifier).

    Example:
        {
            "texts": [
                "Boil pasta for 10 minutes",
                "Just finished watching a great movie",
                "Mix flour, eggs, and milk to make pancakes"
            ],
            "classifier_type": "llm",
            "provider_name": "ollama"
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "texts": [
                    "Boil pasta for 10 minutes",
                    "Just finished watching a great movie",
                    "Mix flour, eggs, and milk to make pancakes"
                ],
                "classifier_type": "llm",
                "provider_name": "lm_studio"
            }
        ]
    })

    texts: List[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of texts to classify"
    )
    classifier_type: ClassifierType = Field(
        default=ClassifierType.LLM,
        description="Classifier to use"
    )
    provider_name: Optional[str] = Field(
        default=None,
        description="LLM provider name (for LLM classifier)",
        examples=["ollama", "openai", "anthropic"]
    )

    @field_validator("texts")
    @classmethod
    def validate_texts(cls, v: List[str]) -> List[str]:
        """Validate that all texts are non-empty and within length limits."""
        for i, text in enumerate(v):
            if not text.strip():
                raise ValueError(f"Text at index {i} is empty or whitespace only")
            if len(text) > 10000:
                raise ValueError(f"Text at index {i} exceeds maximum length of 10000 characters")
        return v


class BatchClassifyResponse(BaseModel):
    """
    Response schema for batch classification results.

    Attributes:
        results: List of classification results.
        total_processed: Total number of texts processed.
        failed_count: Number of texts that failed to classify.
        total_processing_time: Total time taken (seconds).

    Example:
        {
            "results": [
                {
                    "label": "recipe",
                    "confidence": 0.95,
                    "details": {...},
                    "processing_time": 0.234,
                    "classifier_used": "llm"
                },
                ...
            ],
            "total_processed": 3,
            "failed_count": 0,
            "total_processing_time": 0.702
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "results": [
                    {
                        "label": "recipe",
                        "confidence": 0.95,
                        "details": {"cuisine_type": "italian"},
                        "processing_time": 0.234,
                        "classifier_used": "llm"
                    },
                    {
                        "label": "non_recipe",
                        "confidence": 0.88,
                        "details": {},
                        "processing_time": 0.156,
                        "classifier_used": "llm"
                    }
                ],
                "total_processed": 2,
                "failed_count": 0,
                "total_processing_time": 0.390
            }
        ]
    })

    results: List[ClassifyResponse] = Field(
        ...,
        description="List of classification results"
    )
    total_processed: int = Field(
        ...,
        ge=0,
        description="Total texts processed"
    )
    failed_count: int = Field(
        default=0,
        ge=0,
        description="Number of failed classifications"
    )
    total_processing_time: float = Field(
        ...,
        ge=0.0,
        description="Total processing time in seconds"
    )


# ============================================================================
# Multi-class classification schemas
# ============================================================================


class MultiClassifyRequest(BaseModel):
    """
    Request schema for multi-class classification.

    Allows classifying text into custom categories defined either in
    config.toml or via runtime parameters.

    Attributes:
        text: Content to classify.
        classes: Optional runtime class definitions (dict mapping class name
            to description). If None, uses classes from config.toml.
        provider_name: Optional LLM provider name for classification.

    Example:
        {
            "text": "Check out this new FastAPI library for building APIs!",
            "classes": {
                "recipe": "Cooking instructions or ingredients",
                "python_package": "Python libraries or packages",
                "movie_review": "Movie or film discussion"
            },
            "provider_name": "openai"
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "text": "Check out this new FastAPI library for building APIs!",
                "classes": {
                    "recipe": "Cooking instructions or ingredients",
                    "python_package": "Python libraries or packages",
                    "movie_review": "Movie or film discussion"
                },
                "provider_name": "openai"
            },
            {
                "text": "Just watched an amazing thriller last night!",
                "classes": None,
                "provider_name": None
            }
        ]
    })

    text: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Content to classify",
        examples=["Check out this new FastAPI library!"]
    )
    classes: Optional[Dict[str, str]] = Field(
        default=None,
        description="Runtime class definitions (dict mapping class name to description). "
                    "If None, uses classes from config.toml [classification.classes].",
        examples=[{
            "recipe": "Cooking instructions or ingredients",
            "python_package": "Python libraries or packages"
        }]
    )
    provider_name: Optional[str] = Field(
        default=None,
        description="LLM provider name (for classification)",
        examples=["openai", "ollama", "anthropic", "lm_studio"]
    )

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        """Validate that text is not empty or whitespace only."""
        if not v.strip():
            raise ValueError("Text cannot be empty or whitespace only")
        return v

    @field_validator("classes")
    @classmethod
    def validate_classes(cls, v: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Validate that classes dict has at least 2 entries if provided."""
        if v is not None and len(v) < 2:
            raise ValueError("At least 2 classes are required for classification")
        return v


class MultiClassifyResponse(BaseModel):
    """
    Response schema for multi-class classification results.

    Attributes:
        label: Predicted class name.
        confidence: Confidence score (0.0-1.0).
        reasoning: LLM's reasoning for the classification.
        available_classes: List of class names that were available.
        processing_time: Time taken to classify (seconds).
        classifier_used: Always "multi_class_llm".

    Example:
        {
            "label": "python_package",
            "confidence": 0.92,
            "reasoning": "The text mentions FastAPI library and APIs",
            "available_classes": ["recipe", "python_package", "movie_review"],
            "processing_time": 0.345,
            "classifier_used": "multi_class_llm"
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "label": "python_package",
                "confidence": 0.92,
                "reasoning": "The text mentions FastAPI library and building APIs, which is clearly about Python packages.",
                "available_classes": ["recipe", "python_package", "movie_review"],
                "processing_time": 0.345,
                "classifier_used": "multi_class_llm"
            },
            {
                "label": "recipe",
                "confidence": 0.95,
                "reasoning": "The text contains cooking instructions with specific times and ingredients.",
                "available_classes": ["recipe", "tech_news", "other"],
                "processing_time": 0.289,
                "classifier_used": "multi_class_llm"
            }
        ]
    })

    label: str = Field(
        ...,
        description="Predicted class name",
        examples=["python_package", "recipe", "movie_review"]
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0-1.0)"
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="LLM's reasoning for the classification"
    )
    available_classes: List[str] = Field(
        ...,
        description="List of class names that were available for classification"
    )
    processing_time: float = Field(
        ...,
        ge=0.0,
        description="Processing time in seconds"
    )
    classifier_used: str = Field(
        default="multi_class_llm",
        description="Classifier type used",
        examples=["multi_class_llm"]
    )


class BatchMultiClassifyRequest(BaseModel):
    """
    Request schema for batch multi-class classification.

    Allows classifying multiple texts into custom categories.

    Attributes:
        texts: List of texts to classify.
        classes: Optional runtime class definitions.
        provider_name: Optional LLM provider name.

    Example:
        {
            "texts": [
                "Boil pasta for 10 minutes",
                "Check out FastAPI library",
                "Great movie last night"
            ],
            "classes": {
                "recipe": "Cooking instructions",
                "python_package": "Python libraries",
                "movie_review": "Movie discussion"
            },
            "provider_name": "openai"
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "texts": [
                    "Boil pasta for 10 minutes",
                    "Check out this new FastAPI library",
                    "Great movie last night"
                ],
                "classes": {
                    "recipe": "Cooking instructions or ingredients",
                    "python_package": "Python libraries or packages",
                    "movie_review": "Movie or film discussion"
                },
                "provider_name": "openai"
            }
        ]
    })

    texts: List[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of texts to classify"
    )
    classes: Optional[Dict[str, str]] = Field(
        default=None,
        description="Runtime class definitions (dict mapping class name to description). "
                    "If None, uses classes from config.toml [classification.classes].",
        examples=[{
            "recipe": "Cooking instructions or ingredients",
            "python_package": "Python libraries or packages"
        }]
    )
    provider_name: Optional[str] = Field(
        default=None,
        description="LLM provider name (for classification)",
        examples=["openai", "ollama", "anthropic", "lm_studio"]
    )

    @field_validator("texts")
    @classmethod
    def validate_texts(cls, v: List[str]) -> List[str]:
        """Validate that all texts are non-empty and within length limits."""
        for i, text in enumerate(v):
            if not text.strip():
                raise ValueError(f"Text at index {i} is empty or whitespace only")
            if len(text) > 10000:
                raise ValueError(f"Text at index {i} exceeds maximum length of 10000 characters")
        return v

    @field_validator("classes")
    @classmethod
    def validate_classes(cls, v: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Validate that classes dict has at least 2 entries if provided."""
        if v is not None and len(v) < 2:
            raise ValueError("At least 2 classes are required for classification")
        return v


class BatchMultiClassifyResponse(BaseModel):
    """
    Response schema for batch multi-class classification results.

    Attributes:
        results: List of classification results.
        total_processed: Total number of texts processed.
        failed_count: Number of failed classifications.
        total_processing_time: Total time taken (seconds).

    Example:
        {
            "results": [
                {"label": "recipe", "confidence": 0.95, ...},
                {"label": "python_package", "confidence": 0.88, ...}
            ],
            "total_processed": 3,
            "failed_count": 0,
            "total_processing_time": 1.234
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "results": [
                    {
                        "label": "recipe",
                        "confidence": 0.95,
                        "reasoning": "Contains cooking instructions",
                        "available_classes": ["recipe", "python_package", "movie_review"],
                        "processing_time": 0.234,
                        "classifier_used": "multi_class_llm"
                    },
                    {
                        "label": "python_package",
                        "confidence": 0.88,
                        "reasoning": "Mentions FastAPI library",
                        "available_classes": ["recipe", "python_package", "movie_review"],
                        "processing_time": 0.312,
                        "classifier_used": "multi_class_llm"
                    }
                ],
                "total_processed": 2,
                "failed_count": 0,
                "total_processing_time": 0.546
            }
        ]
    })

    results: List[MultiClassifyResponse] = Field(
        ...,
        description="List of multi-class classification results"
    )
    total_processed: int = Field(
        ...,
        ge=0,
        description="Total texts processed"
    )
    failed_count: int = Field(
        default=0,
        ge=0,
        description="Number of failed classifications"
    )
    total_processing_time: float = Field(
        ...,
        ge=0.0,
        description="Total processing time in seconds"
    )

