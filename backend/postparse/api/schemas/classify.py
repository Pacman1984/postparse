"""
Pydantic schemas for classification endpoints.

This module defines request/response models for recipe classification,
wrapping the existing ClassificationResult from the classifier base module.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator


class ClassifierType(str, Enum):
    """
    Type of classifier to use.

    Values:
        LLM: RecipeLLMClassifier (LLM-based recipe classification).
    """

    LLM = "llm"


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

