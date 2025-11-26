"""
FastAPI router for classification endpoints.

This module provides HTTP endpoints for recipe classification and
multi-class classification using LLM-based classifiers.
"""

import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status

from backend.postparse.services.analysis.classifiers.llm import RecipeLLMClassifier
from backend.postparse.services.analysis.classifiers.multi_class import MultiClassLLMClassifier
from backend.postparse.api.dependencies import (
    get_recipe_llm_classifier,
    get_optional_auth,
    get_config,
)
from backend.postparse.api.schemas import (
    ClassifyRequest,
    ClassifyResponse,
    BatchClassifyRequest,
    BatchClassifyResponse,
    ClassifierType,
)
from backend.postparse.api.schemas.classify import (
    MultiClassifyRequest,
    MultiClassifyResponse,
    BatchMultiClassifyRequest,
    BatchMultiClassifyResponse,
)
from backend.postparse.core.utils.config import ConfigManager

router = APIRouter(
    prefix="/api/v1/classify",
    tags=["classify"],
    responses={
        400: {"description": "Invalid request"},
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
        503: {"description": "LLM service unavailable"},
    },
)


@router.post(
    "/recipe",
    response_model=ClassifyResponse,
    summary="Classify text as recipe or non-recipe",
    description="""
    Classify a single text to determine if it contains a recipe.
    
    Currently supports:
    - **llm**: RecipeLLMClassifier (pure LLM-based classification)
    
    Note: A basic rule-based classifier is planned for a future phase.
    
    Returns classification label, confidence score, and additional details
    like cuisine type, difficulty, and meal type.
    
    Provider switching is supported: specify `provider_name` in the request
    to use a different LLM provider (e.g., "openai", "anthropic", "lm_studio").
    If not specified, uses the default provider from configuration.
    """,
)
async def classify_recipe(
    request: ClassifyRequest,
    llm_classifier: RecipeLLMClassifier = Depends(get_recipe_llm_classifier),
    user: Optional[dict] = Depends(get_optional_auth),
) -> ClassifyResponse:
    """
    Classify single text as recipe or non-recipe.
    
    Args:
        request: Classification request with text and classifier type.
        llm_classifier: RecipeLLMClassifier instance (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        ClassifyResponse with label, confidence, and details.
        
    Raises:
        HTTPException: 400 if provider_name is invalid.
        HTTPException: 503 if LLM service is unavailable.
        
    Example:
        POST /api/v1/classify/recipe
        {
            "text": "Boil pasta for 10 minutes, drain, add tomato sauce and basil",
            "classifier_type": "llm",
            "provider_name": "lm_studio"
        }
        
        Response:
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
    start_time = time.time()
    
    try:
        # Use provider-specific classifier if provider_name is provided
        if request.provider_name:
            try:
                classifier = RecipeLLMClassifier(provider_name=request.provider_name)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid provider_name '{request.provider_name}': {str(e)}",
                )
        else:
            # Use default injected classifier
            classifier = llm_classifier
        
        classifier_name = "llm"
        
        # Perform classification
        result = classifier.predict(request.text)
        
        processing_time = time.time() - start_time
        
        return ClassifyResponse(
            label=result.label,
            confidence=result.confidence,
            details=result.details or {},
            processing_time=processing_time,
            classifier_used=classifier_name,
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        # Handle LLM provider errors
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Classification failed: {str(e)}",
        )


@router.post(
    "/batch",
    response_model=BatchClassifyResponse,
    summary="Classify multiple texts in batch",
    description="""
    Classify multiple texts in a single request for efficiency.
    
    Supports up to 100 texts per request. Uses the same classifier types
    as the single classification endpoint.
    
    Provider switching is supported: specify `provider_name` in the request
    to use a different LLM provider for all texts in the batch.
    """,
)
async def classify_batch(
    request: BatchClassifyRequest,
    llm_classifier: RecipeLLMClassifier = Depends(get_recipe_llm_classifier),
    user: Optional[dict] = Depends(get_optional_auth),
) -> BatchClassifyResponse:
    """
    Classify multiple texts in batch.
    
    Args:
        request: Batch classification request with list of texts.
        llm_classifier: RecipeLLMClassifier instance (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        BatchClassifyResponse with results for all texts.
        
    Raises:
        HTTPException: 400 if provider_name is invalid.
        
    Example:
        POST /api/v1/classify/batch
        {
            "texts": [
                "Boil pasta for 10 minutes",
                "Just finished watching a great movie",
                "Mix flour, eggs, and milk to make pancakes"
            ],
            "classifier_type": "llm",
            "provider_name": "openai"
        }
        
        Response:
        {
            "results": [...],
            "total_processed": 3,
            "failed_count": 0,
            "total_processing_time": 0.702
        }
    """
    start_time = time.time()
    
    # Use provider-specific classifier if provider_name is provided
    if request.provider_name:
        try:
            classifier = RecipeLLMClassifier(provider_name=request.provider_name)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid provider_name '{request.provider_name}': {str(e)}",
            )
    else:
        # Use default injected classifier
        classifier = llm_classifier
    
    classifier_name = "llm"
    
    results = []
    failed_count = 0
    
    # Process each text
    for text in request.texts:
        try:
            text_start_time = time.time()
            result = classifier.predict(text)
            text_processing_time = time.time() - text_start_time
            
            results.append(ClassifyResponse(
                label=result.label,
                confidence=result.confidence,
                details=result.details or {},
                processing_time=text_processing_time,
                classifier_used=classifier_name,
            ))
        except Exception:
            # Count failures but continue processing
            failed_count += 1
    
    total_processing_time = time.time() - start_time
    
    return BatchClassifyResponse(
        results=results,
        total_processed=len(request.texts),
        failed_count=failed_count,
        total_processing_time=total_processing_time,
    )


@router.post(
    "/multi",
    response_model=MultiClassifyResponse,
    summary="Classify text into custom categories",
    description="""
    Classify a single text into one of the custom categories using LLM-based multi-class classification.
    
    ## Features
    
    - **Dynamic Classes**: Define any number of classes (minimum 2)
    - **Config + Runtime**: Use default classes from config.toml or override with runtime classes
    - **Provider Flexibility**: Specify which LLM provider to use
    - **Structured Output**: Returns predicted class, confidence score, and reasoning
    
    ## Class Definitions
    
    Classes can be defined in two ways:
    
    1. **Config-based**: Default classes defined in `config.toml` under `[classification.classes]`
    2. **Runtime-based**: Pass a `classes` dict in the request to override/extend config classes
    
    Each class definition is a dictionary mapping class name to description. The description
    should explain what content belongs to that class, ideally with examples.
    
    ## Provider Switching
    
    Specify `provider_name` in the request to use a different LLM provider
    (e.g., "openai", "anthropic", "ollama", "lm_studio"). If not specified,
    uses the default provider from configuration.
    
    ## Response
    
    Returns the predicted class label, confidence score (0.0-1.0), reasoning for the
    classification, list of available classes, and processing time.
    """,
)
async def classify_multi(
    request: MultiClassifyRequest,
    config: ConfigManager = Depends(get_config),
    user: Optional[dict] = Depends(get_optional_auth),
) -> MultiClassifyResponse:
    """
    Classify single text into custom categories.
    
    Args:
        request: Multi-class classification request with text and optional classes.
        config: ConfigManager instance (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        MultiClassifyResponse with label, confidence, reasoning, and available classes.
        
    Raises:
        HTTPException: 400 if classes are invalid or provider_name is invalid.
        HTTPException: 503 if LLM service is unavailable.
        
    Example:
        POST /api/v1/classify/multi
        {
            "text": "Check out this new FastAPI library for building APIs!",
            "classes": {
                "recipe": "Cooking instructions or ingredients",
                "python_package": "Python libraries or packages",
                "movie_review": "Movie or film discussion"
            },
            "provider_name": "openai"
        }
        
        Response:
        {
            "label": "python_package",
            "confidence": 0.92,
            "reasoning": "The text mentions FastAPI library and building APIs",
            "available_classes": ["recipe", "python_package", "movie_review"],
            "processing_time": 0.345,
            "classifier_used": "multi_class_llm"
        }
    """
    start_time = time.time()
    
    try:
        # Create classifier with runtime classes and/or provider
        classifier = MultiClassLLMClassifier(
            classes=request.classes,
            provider_name=request.provider_name,
            config_path=config.config_path if hasattr(config, 'config_path') else None,
        )
        
        # Perform classification
        result = classifier.predict(request.text)
        
        processing_time = time.time() - start_time
        
        return MultiClassifyResponse(
            label=result.label,
            confidence=result.confidence,
            reasoning=result.details.get('reasoning') if result.details else None,
            available_classes=result.details.get('available_classes', []) if result.details else [],
            processing_time=processing_time,
            classifier_used="multi_class_llm",
        )
        
    except ValueError as e:
        # Handle validation errors (invalid classes, provider not found)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        # Handle LLM provider errors
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Multi-class classification failed: {str(e)}",
        )


@router.post(
    "/multi/batch",
    response_model=BatchMultiClassifyResponse,
    summary="Classify multiple texts into custom categories",
    description="""
    Classify multiple texts into custom categories in a single request.
    
    This batch endpoint is more efficient than calling the single endpoint multiple times,
    as it reuses the same classifier instance for all texts.
    
    ## Features
    
    - **Batch Processing**: Classify up to 100 texts in a single request
    - **Shared Classifier**: Uses the same classifier instance for efficiency
    - **Partial Failure Handling**: Continues processing even if individual texts fail
    - **Aggregate Statistics**: Returns total processed, failed count, and total time
    
    ## Usage
    
    Same class definition and provider switching options as the single endpoint.
    Individual failures are counted but don't stop the batch from completing.
    """,
)
async def classify_multi_batch(
    request: BatchMultiClassifyRequest,
    config: ConfigManager = Depends(get_config),
    user: Optional[dict] = Depends(get_optional_auth),
) -> BatchMultiClassifyResponse:
    """
    Classify multiple texts into custom categories in batch.
    
    Args:
        request: Batch multi-class classification request with texts and optional classes.
        config: ConfigManager instance (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        BatchMultiClassifyResponse with results for all texts.
        
    Raises:
        HTTPException: 400 if classes are invalid or provider_name is invalid.
        
    Example:
        POST /api/v1/classify/multi/batch
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
            }
        }
        
        Response:
        {
            "results": [...],
            "total_processed": 3,
            "failed_count": 0,
            "total_processing_time": 1.234
        }
    """
    start_time = time.time()
    
    try:
        # Create classifier once for the batch
        classifier = MultiClassLLMClassifier(
            classes=request.classes,
            provider_name=request.provider_name,
            config_path=config.config_path if hasattr(config, 'config_path') else None,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    results = []
    failed_count = 0
    available_classes = classifier.get_class_names()
    
    # Process each text
    for text in request.texts:
        try:
            text_start_time = time.time()
            result = classifier.predict(text)
            text_processing_time = time.time() - text_start_time
            
            results.append(MultiClassifyResponse(
                label=result.label,
                confidence=result.confidence,
                reasoning=result.details.get('reasoning') if result.details else None,
                available_classes=result.details.get('available_classes', available_classes) if result.details else available_classes,
                processing_time=text_processing_time,
                classifier_used="multi_class_llm",
            ))
        except Exception:
            # Count failures but continue processing
            failed_count += 1
    
    total_processing_time = time.time() - start_time
    
    return BatchMultiClassifyResponse(
        results=results,
        total_processed=len(request.texts),
        failed_count=failed_count,
        total_processing_time=total_processing_time,
    )


@router.get(
    "/classifiers",
    response_model=Dict[str, List[Dict[str, Any]]],
    summary="List available classifiers",
    description="""
    List all available classifiers and their configurations.
    
    Returns information about:
    - Classifier types (llm for recipes, multi_class_llm for custom categories)
    - Available LLM providers
    - Provider configurations
    """,
)
async def list_classifiers(
    config: ConfigManager = Depends(get_config),
    user: Optional[dict] = Depends(get_optional_auth),
) -> Dict[str, List[Dict[str, Any]]]:
    """
    List available classifiers and their configurations.
    
    Args:
        config: ConfigManager instance (injected dependency).
        user: Optional authenticated user info.
        
    Returns:
        Dictionary with classifier types and available providers.
        
    Example:
        GET /api/v1/classify/classifiers
        
        Response:
        {
            "classifiers": [
                {"type": "llm", "name": "RecipeLLMClassifier"},
                {"type": "multi_class_llm", "name": "MultiClassLLMClassifier"}
            ],
            "providers": [
                {"name": "ollama", "status": "available"},
                {"name": "openai", "status": "available"},
                {"name": "anthropic", "status": "available"}
            ]
        }
    """
    # Get available LLM providers from config
    default_provider = config.get("llm.default_provider", "ollama")
    
    return {
        "classifiers": [
            {
                "type": "llm",
                "name": "RecipeLLMClassifier",
                "description": "LLM-based recipe classification (recipe/not_recipe)"
            },
            {
                "type": "multi_class_llm",
                "name": "MultiClassLLMClassifier",
                "description": "LLM-based multi-class classification with custom categories"
            },
        ],
        "providers": [
            {"name": "ollama", "status": "available", "default": default_provider == "ollama"},
            {"name": "openai", "status": "available", "default": default_provider == "openai"},
            {"name": "anthropic", "status": "available", "default": default_provider == "anthropic"},
            {"name": "lm_studio", "status": "available", "default": default_provider == "lm_studio"},
        ],
    }

