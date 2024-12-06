"""Recipe classifier using scikit-ollama for zero-shot classification."""
import os
from typing import Dict, Any
from pathlib import Path
from skollama.models.ollama.classification.zero_shot import ZeroShotOllamaClassifier
from dotenv import load_dotenv

class RecipeClassifier:
    """Classifier for detecting recipe content in text."""
    
    def __init__(self):
        """Initialize the recipe classifier."""
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
        
        # Initialize the classifier with descriptive labels
        self.classifier = ZeroShotOllamaClassifier(
            model="qwen2.5:72b-instruct",
            host=host
        )
        
        # Fit with descriptive labels
        self.classifier.fit(None, [
            "this text contains a recipe with ingredients and/or cooking instructions",
            "this text does not contain any recipe or cooking instructions"
        ])
    
    def predict(self, text: str) -> str:
        """Predict if the given text contains a recipe.
        
        Args:
            text (str): Text to classify
            
        Returns:
            str: Classification result ("recipe" or "not recipe")
        """
        # Run classification
        result = self.classifier.predict([text])
        
        # Return simple label
        return "recipe" if "contains a recipe" in result[0] else "not recipe" 