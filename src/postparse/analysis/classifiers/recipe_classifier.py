"""Recipe classifier using scikit-ollama for zero-shot classification."""
import os
from typing import Dict, Any, Optional
from pathlib import Path
from skollama.models.ollama.classification.zero_shot import ZeroShotOllamaClassifier
from dotenv import load_dotenv

from ...utils.config import get_config, get_model_config, get_classification_config


class RecipeClassifier:
    """Classifier for detecting recipe content in text."""
    
    def __init__(self, model_name: Optional[str] = None, config_path: Optional[str] = None):
        """Initialize the recipe classifier.
        
        Args:
            model_name: Name of the model to use. If None, uses config default.
            config_path: Path to configuration file. If None, uses default locations.
        """
        # Load configuration
        config = get_config(config_path)
        model_config = get_model_config()
        classification_config = get_classification_config()
        
        # Find and load .env file
        env_path = Path("config/.env")
        if not env_path.exists():
            # Try relative to the package root
            package_root = Path(__file__).parent.parent.parent.parent
            env_path = package_root / "config" / ".env"
        
        if not env_path.exists():
            raise ValueError("Could not find config/.env file")
            
        load_dotenv(env_path)
        
        # Get Ollama server details from environment
        ollama_ip = os.getenv("OLLAMA_IP")
        ollama_port = os.getenv("OLLAMA_PORT")
        
        if not ollama_ip or not ollama_port:
            raise ValueError("OLLAMA_IP and OLLAMA_PORT must be set in config/.env")
        
        # Construct the full URL
        host = f"http://{ollama_ip}"
        if not host.endswith(ollama_port):
            host = f"{host}:{ollama_port}"
        
        # Get model name from config or parameter
        model = model_name or config.get(
            'models.zero_shot_model', 
            default='qwen2.5:72b-instruct',
            env_var='ZERO_SHOT_MODEL'
        )
        
        # Initialize the classifier with configured model
        self.classifier = ZeroShotOllamaClassifier(
            model=model,
            host=host
        )
        
        # Get classification labels from config
        positive_label = config.get(
            'classification.recipe_positive_label',
            default="this text contains a recipe with ingredients and/or cooking instructions"
        )
        negative_label = config.get(
            'classification.recipe_negative_label',
            default="this text does not contain any recipe or cooking instructions"
        )
        
        # Fit with configured labels
        self.classifier.fit(None, [positive_label, negative_label])
    
    def predict(self, text: str) -> str:
        """Predict if the given text contains a recipe.
        
        Args:
            text (str): Text to classify
            
        Returns:
            str: Classification result ("recipe" or "not recipe")
        """
        # Run classification
        result = self.classifier.predict([text])
        
        # Return simple label - check if result contains recipe indication
        return "recipe" if "contains a recipe" in result[0] else "not recipe" 