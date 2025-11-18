from typing import Any, Optional
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_community.chat_models import ChatLiteLLM
from pydantic import BaseModel, Field

from .base import BaseClassifier, ClassificationResult
from postparse.core.utils.config import get_config, get_model_config, get_prompt_config, get_classification_config

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
    
    Examples:
        Basic usage with default config:
        ```python
        from postparse.services.analysis.classifiers import RecipeLLMClassifier
        
        classifier = RecipeLLMClassifier()
        result = classifier.predict("My pasta recipe: boil pasta, add sauce...")
        print(result.label)           # "recipe" or "not_recipe"
        print(result.confidence)      # 0.95
        print(result.details)         # {"cuisine_type": "Italian", ...}
        ```
        
        With specific model:
        ```python
        classifier = RecipeLLMClassifier(model_name="gpt-4o-mini")
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
    
    def __init__(self, model_name: Optional[str] = None, config_path: Optional[str] = None):
        """Initialize the LLM classifier.
        
        Args:
            model_name: Name of the model to use. If None, uses config default.
                For Ollama: "llama2", "qwen3:14b", etc.
                For OpenAI: "gpt-4o-mini", "gpt-4", etc.
                For Anthropic: "claude-3-5-sonnet-20241022", etc.
            config_path: Path to configuration file. If None, uses default locations.
        """
        # Load configuration
        config = get_config(config_path)
        model_config = get_model_config()
        prompt_config = get_prompt_config()
        classification_config = get_classification_config()
        
        # Get model name from config or parameter
        model = model_name or config.get(
            'models.default_llm_model',
            default='llama2',
            env_var='DEFAULT_LLM_MODEL'
        )
        
        # Get provider and optional API base from config
        provider = config.get(
            'models.llm_provider',
            default='ollama',
            env_var='LLM_PROVIDER'
        )
        api_base = config.get(
            'models.llm_api_base',
            default='',
            env_var='LLM_API_BASE'
        )
        
        # LiteLLM adapter configuration
        if api_base:
            # Custom endpoint (LM Studio, etc.) - use model name as-is
            # LM Studio expects: "model": "qwen/qwen3-vl-8b"
            llm_kwargs = {
                "model": model,  # Use model name as-is from config
                "api_base": api_base,
                "custom_llm_provider": "openai"  # OpenAI-compatible format
            }
            self._validate_llm_config(config, provider="openai", is_custom_endpoint=True)
        else:
            # Standard providers - prefix with provider name
            # Examples: "ollama/llama2", "gpt-4", "claude-3-5-sonnet-20241022"
            llm_kwargs = {"model": f"{provider}/{model}"}
            self._validate_llm_config(config, provider=provider)
        
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
    
    def _validate_llm_config(self, config: Any, provider: str, is_custom_endpoint: bool = False) -> None:
        """Validate that necessary configuration for LiteLLM is present.
        
        Args:
            config: Configuration object
            provider: LLM provider name
            is_custom_endpoint: Whether using a custom API base
        """
        # Check for OpenAI API key if using OpenAI provider or custom OpenAI-compatible endpoint
        if provider == 'openai' or (is_custom_endpoint and provider == 'openai'):
            api_key = config.get('models.openai_api_key', env_var='OPENAI_API_KEY')
            if not api_key:
                msg = (
                    "Missing OPENAI_API_KEY environment variable or configuration. "
                    "This is required for OpenAI models and compatible custom endpoints (like LM Studio). "
                    "For local development with LM Studio/Ollama, you can set OPENAI_API_KEY='dummy'."
                )
                raise ValueError(msg)
    
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