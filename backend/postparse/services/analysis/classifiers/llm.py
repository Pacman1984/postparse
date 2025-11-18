from typing import Any, Optional
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from langchain.llms import Ollama
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

from .base import BaseClassifier, ClassificationResult
from ...utils.config import get_config, get_model_config, get_prompt_config, get_classification_config

class RecipeDetails(BaseModel):
    """Detailed recipe classification output."""
    is_recipe: bool = Field(..., description="Whether the content is a recipe")
    cuisine_type: Optional[str] = Field(None, description="Type of cuisine (e.g., Italian, Mexican)")
    difficulty: Optional[str] = Field(None, description="Recipe difficulty (easy, medium, hard)")
    meal_type: Optional[str] = Field(None, description="Type of meal (breakfast, lunch, dinner, dessert)")
    ingredients_count: Optional[int] = Field(None, description="Estimated number of ingredients")

class RecipeLLMClassifier(BaseClassifier):
    """LLM-based recipe classifier using LangChain."""
    
    def __init__(self, model_name: Optional[str] = None, config_path: Optional[str] = None):
        """Initialize the LLM classifier.
        
        Args:
            model_name: Name of the model to use. If None, uses config default.
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
        
        self.llm = Ollama(model=model)
        self.output_parser = PydanticOutputParser(pydantic_object=RecipeDetails)
        
        # Get prompt template from config
        prompt_template = config.get(
            'prompts.recipe_analysis_prompt',
            default="""Analyze if the following content is a recipe and extract key details.
        
Content: {content}

{format_instructions}

Provide a detailed analysis focusing on recipe characteristics.
If it's not a recipe, set is_recipe to false and leave other fields as null."""
        )
        
        self.prompt = PromptTemplate(
            template=prompt_template,
            input_variables=["content"],
            partial_variables={
                "format_instructions": self.output_parser.get_format_instructions()
            }
        )
        
        self.chain = LLMChain(llm=self.llm, prompt=self.prompt)
        
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
        # Get LLM response
        response = self.chain.run(content=X)
        details = self.output_parser.parse(response)
        
        # Calculate confidence based on completeness of details
        confidence = self._calculate_confidence(details)
        
        return ClassificationResult(
            label="recipe" if details.is_recipe else "not_recipe",
            confidence=confidence,
            details=details.dict()
        )
    
    def _calculate_confidence(self, details: RecipeDetails) -> float:
        """Calculate confidence score based on completeness of details."""
        if not details.is_recipe:
            return self.max_confidence if all(v is None for k, v in details.dict().items() if k != "is_recipe") else 0.7
        
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