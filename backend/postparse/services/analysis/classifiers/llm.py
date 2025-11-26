from typing import Any, Optional
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_litellm import ChatLiteLLM
from pydantic import BaseModel, Field

from .base import BaseClassifier, ClassificationResult
from backend.postparse.core.utils.config import get_config
from backend.postparse.llm.config import LLMConfig, get_provider_config

class RecipeDetails(BaseModel):
    """Detailed recipe classification output."""
    is_recipe: bool = Field(..., description="Whether the content is a recipe")
    cuisine_type: Optional[str] = Field(None, description="Type of cuisine (e.g., Italian, Mexican)")
    difficulty: Optional[str] = Field(None, description="Recipe difficulty (easy, medium, hard)")
    meal_type: Optional[str] = Field(None, description="Type of meal (breakfast, lunch, dinner, dessert)")
    ingredients_count: Optional[int] = Field(None, description="Estimated number of ingredients")

class RecipeLLMClassifier(BaseClassifier):
    """LLM-based recipe classifier using LangChain + LiteLLM.
    
    This classifier combines:
    - **LangChain**: For PydanticOutputParser, prompts, and structured outputs
    - **LiteLLM**: As universal adapter supporting ANY LLM provider
    
    Configuration is now centralized in config.toml [llm] section. The old [models] 
    section is deprecated.
    
    Supported Providers (via LiteLLM):
    - Ollama (local, free)
    - LM Studio (local, free)
    - OpenAI (GPT-4, GPT-3.5, etc.)
    - Anthropic (Claude models)
    - 100+ other providers supported by LiteLLM
    
    The classifier returns structured Pydantic models with:
    - Binary classification (recipe / not_recipe)
    - Confidence scores
    - Rich metadata (cuisine type, difficulty, meal type, ingredients count)
    
    API keys are loaded from environment variables:
    - OPENAI_API_KEY: For OpenAI and LM Studio (OpenAI-compatible format)
    - ANTHROPIC_API_KEY: For Anthropic Claude models
    - Ollama: No API key needed for local deployment
    
    Examples:
        Basic usage with default provider from config:
        ```python
        from postparse.services.analysis.classifiers import RecipeLLMClassifier
        
        classifier = RecipeLLMClassifier()
        result = classifier.predict("My pasta recipe: boil pasta, add sauce...")
        print(result.label)           # "recipe" or "not_recipe"
        print(result.confidence)      # 0.95
        print(result.details)         # {"cuisine_type": "Italian", ...}
        ```
        
        With specific provider from [llm.providers]:
        ```python
        classifier = RecipeLLMClassifier(provider_name='openai')  # Uses OpenAI
        classifier = RecipeLLMClassifier(provider_name='lm_studio')  # Uses LM Studio
        classifier = RecipeLLMClassifier(provider_name='ollama')  # Uses Ollama
        result = classifier.predict(text)
        ```
        
        Batch classification:
        ```python
        texts = ["recipe 1", "recipe 2", "not recipe"]
        results = classifier.predict_batch(texts)
        for r in results:
            print(f"{r.label}: {r.details}")
        ```
    """
    
    def __init__(self, provider_name: Optional[str] = None, config_path: Optional[str] = None):
        """Initialize the LLM classifier.
        
        Args:
            provider_name: Name of the provider to use from [llm.providers] in config.toml.
                If None, uses the default_provider from config. 
                Examples: 'openai', 'ollama', 'lm_studio', 'anthropic'
            config_path: Path to configuration file. If None, uses default locations.
                
        Examples:
            ```python
            # Use default provider from config
            classifier = RecipeLLMClassifier()
            
            # Use specific provider
            classifier = RecipeLLMClassifier(provider_name='openai')
            classifier = RecipeLLMClassifier(provider_name='lm_studio')
            ```
        """
        # Load configuration
        config = get_config(config_path)
        
        # Load LLM configuration from new [llm] section
        llm_config = LLMConfig.from_config_manager(config)
        
        # Select provider: use specified or default from config
        selected_provider = provider_name or llm_config.default_provider
        
        # Get provider configuration and store for metadata access
        provider_cfg = get_provider_config(llm_config, selected_provider)
        self._provider_config = provider_cfg
        
        # Build llm_kwargs from provider configuration
        llm_kwargs = {
            "model": provider_cfg.model,
            "temperature": provider_cfg.temperature,
        }
        
        # Add optional parameters if present
        if provider_cfg.timeout:
            llm_kwargs["timeout"] = provider_cfg.timeout
        if provider_cfg.max_tokens:
            llm_kwargs["max_tokens"] = provider_cfg.max_tokens
        if provider_cfg.api_key:
            llm_kwargs["api_key"] = provider_cfg.api_key
            
        # Handle custom endpoints (LM Studio, Ollama)
        if provider_cfg.api_base:
            llm_kwargs["api_base"] = provider_cfg.api_base
            
            # For custom endpoints, set custom_llm_provider based on port/provider
            if '11434' in provider_cfg.api_base or provider_cfg.name.lower() == 'ollama':
                llm_kwargs["custom_llm_provider"] = "ollama"
            else:
                # LM Studio and other OpenAI-compatible endpoints
                llm_kwargs["custom_llm_provider"] = "openai"
        else:
            # Standard cloud providers - prefix model with provider name if needed
            if provider_cfg.name.lower() == 'ollama':
                llm_kwargs["model"] = f"ollama/{provider_cfg.model}"
            # OpenAI and Anthropic models don't need prefixing
        
        self.llm = ChatLiteLLM(**llm_kwargs)
        
        # Use PydanticOutputParser for compatibility with all models
        # (with_structured_output requires tool calling which not all models support)
        self.output_parser = PydanticOutputParser(pydantic_object=RecipeDetails)
        
        # Get prompt template from config
        prompt_template = config.get(
            'prompts.recipe_analysis_prompt',
            default="""Analyze if the following content is a recipe and extract key details.

Content: {content}

{format_instructions}

If it's not a recipe, set is_recipe to false and leave other fields as null."""
        )
        
        self.prompt = PromptTemplate(
            template=prompt_template,
            input_variables=["content"],
            partial_variables={
                "format_instructions": self.output_parser.get_format_instructions()
            }
        )
        
        # Store configuration for confidence calculation
        self.min_confidence = config.get(
            'classification.min_confidence_threshold',
            default=0.6
        )
        self.max_confidence = config.get(
            'classification.max_confidence_threshold',
            default=1.0
        )
    
    def fit(self, X: Any, y: Optional[Any] = None) -> 'RecipeLLMClassifier':
        """LLM classifiers don't require training."""
        return self
    
    def predict(self, X: str) -> ClassificationResult:
        """Predict if content is a recipe and extract details.
        
        Args:
            X (str): Content to analyze
            
        Returns:
            ClassificationResult: Classification with recipe details
        """
        # Format prompt with content
        formatted_prompt = self.prompt.format(content=X)
        
        # Get LLM response
        response = self.llm.invoke(formatted_prompt)
        
        # Parse response to RecipeDetails
        details = self.output_parser.parse(response.content)
        
        # Calculate confidence based on completeness of details
        confidence = self._calculate_confidence(details)
        
        return ClassificationResult(
            label="recipe" if details.is_recipe else "not_recipe",
            confidence=confidence,
            details=details.model_dump()
        )
    
    def _calculate_confidence(self, details: RecipeDetails) -> float:
        """Calculate confidence score based on completeness of details."""
        if not details.is_recipe:
            return self.max_confidence if all(v is None for k, v in details.model_dump().items() if k != "is_recipe") else 0.7
        
        # Count how many optional fields are filled
        filled_fields = sum(1 for v in [
            details.cuisine_type,
            details.difficulty,
            details.meal_type,
            details.ingredients_count
        ] if v is not None)
        
        # More filled fields = higher confidence, using configured thresholds
        base_confidence = self.min_confidence
        confidence_increment = (self.max_confidence - self.min_confidence) / 4  # 4 optional fields
        return min(base_confidence + (filled_fields * confidence_increment), self.max_confidence)

    def get_llm_metadata(self) -> dict:
        """Get LLM configuration metadata for storage/tracking.

        Returns:
            Dictionary with provider configuration (excluding sensitive api_key).

        Example:
            >>> classifier = RecipeLLMClassifier(provider_name='lm_studio')
            >>> metadata = classifier.get_llm_metadata()
            >>> print(metadata)
            {
                'provider': 'lm_studio',
                'model': 'qwen/qwen3-vl-8b',
                'temperature': 0.7,
                'max_tokens': 1000,
                'timeout': 60,
                'api_base': 'http://localhost:1234/v1'
            }
        """
        cfg = self._provider_config
        metadata = {
            "provider": cfg.name,
            "model": cfg.model,
            "temperature": cfg.temperature,
        }
        # Add optional fields if present
        if cfg.max_tokens:
            metadata["max_tokens"] = cfg.max_tokens
        if cfg.timeout:
            metadata["timeout"] = cfg.timeout
        if cfg.api_base:
            metadata["api_base"] = cfg.api_base
        return metadata 