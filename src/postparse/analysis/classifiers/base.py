from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union
from pydantic import BaseModel

class ClassificationResult(BaseModel):
    """Base model for classification results."""
    label: str
    confidence: float
    details: Optional[Dict[str, Any]] = None

class BaseClassifier(ABC):
    """Base classifier interface."""
    
    @abstractmethod
    def fit(self, X: Any, y: Optional[Any] = None) -> 'BaseClassifier':
        """Fit the classifier with training data.
        
        Args:
            X: Training data
            y: Target values (optional for some classifiers)
            
        Returns:
            self: The fitted classifier
        """
        pass
    
    @abstractmethod
    def predict(self, X: Any) -> ClassificationResult:
        """Make predictions on input data.
        
        Args:
            X: Input data to classify
            
        Returns:
            ClassificationResult: Classification result with label and confidence
        """
        pass
    
    def predict_batch(self, X: list[Any]) -> list[ClassificationResult]:
        """Make predictions on a batch of inputs.
        
        Args:
            X: List of input data to classify
            
        Returns:
            list[ClassificationResult]: List of classification results
        """
        return [self.predict(x) for x in X] 