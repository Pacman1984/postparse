"""Shared helpers for LLM-based classifiers.

This module provides a small mixin with common initialization and helper methods
used by both multi-class and multi-label LLM classifiers to avoid duplication.
"""

from typing import Any, Dict, List, Optional

from backend.postparse.llm.config import get_provider_config
from backend.postparse.llm.model_discovery import resolve_provider_model


class LLMClassifierCommon:
    """Common helper mixin for LLM classifiers.

    Provides:
    - Loading and merging classes from config and runtime.
    - Building a ChatLiteLLM instance from provider configuration.
    - Convenience getters for classes and provider metadata.
    """

    def _load_classes_from_config(self, config: Any) -> Dict[str, str]:
        """Load class definitions from config.toml [classification.classes].

        Args:
            config: ConfigManager instance.

        Returns:
            Dict[str, str]: Mapping of class names to descriptions.
        """
        classes: Dict[str, str] = {}
        classification_section = config.get_section("classification")
        for class_def in classification_section.get("classes", []):
            name = class_def.get("name")
            description = class_def.get("description", "")
            if name:
                classes[name] = description
        return classes

    def _initialize_classes(
        self, classes: Optional[Dict[str, str]], config: Any
    ) -> Dict[str, str]:
        """Merge config classes with runtime classes and validate count.

        Args:
            classes: Runtime class definitions (overrides duplicates).
            config: ConfigManager instance.

        Returns:
            Dict[str, str]: Final merged classes.

        Raises:
            ValueError: If fewer than 2 classes are defined.
        """
        config_classes = self._load_classes_from_config(config)
        merged: Dict[str, str] = {**config_classes, **(classes or {})}
        if len(merged) < 2:
            raise ValueError(
                "At least 2 classes are required for classification, "
                f"got {len(merged)}. "
                "Define classes in config.toml [classification.classes] "
                "or pass them to the constructor."
            )
        # Store on instance for consumers
        self.classes = merged
        return merged

    def _initialize_llm(self, provider_name: Optional[str], config: Any):
        """Create ChatLiteLLM from provider config and store provider metadata.

        Args:
            provider_name: Optional explicit provider to select.
            config: ConfigManager instance.

        Returns:
            Any: Configured chat model instance (ChatLiteLLM).

        Raises:
            ValueError: If specified provider is not found.
        """
        # Expect caller to set these for testability (allows module-level patching)
        llm_config = self._LLMConfig.from_config_manager(config)
        selected_provider = provider_name or llm_config.default_provider

        available_providers: List[str] = [p.name for p in llm_config.providers]
        if selected_provider not in available_providers:
            raise ValueError(
                f"Provider '{selected_provider}' not found. "
                f"Available: {', '.join(available_providers)}"
            )

        provider_cfg = resolve_provider_model(
            get_provider_config(llm_config, selected_provider)
        )
        # Expose for metadata accessors
        self._provider_config = provider_cfg

        llm_kwargs: Dict[str, Any] = {
            "model": provider_cfg.model,
            "temperature": provider_cfg.temperature,
        }
        if provider_cfg.timeout:
            llm_kwargs["timeout"] = provider_cfg.timeout
        if provider_cfg.max_tokens:
            llm_kwargs["max_tokens"] = provider_cfg.max_tokens
        if provider_cfg.api_key:
            llm_kwargs["api_key"] = provider_cfg.api_key

        # Handle custom endpoints (LM Studio, Ollama) vs cloud providers
        if provider_cfg.api_base:
            llm_kwargs["api_base"] = provider_cfg.api_base
            if "11434" in provider_cfg.api_base or provider_cfg.name.lower() == "ollama":
                llm_kwargs["custom_llm_provider"] = "ollama"
            else:
                llm_kwargs["custom_llm_provider"] = "openai"
        else:
            if provider_cfg.name.lower() == "ollama":
                llm_kwargs["model"] = f"ollama/{provider_cfg.model}"

        return self._ChatLiteLLM(**llm_kwargs)

    # ----------------------
    # Convenience getters
    # ----------------------
    def get_classes(self) -> Dict[str, str]:
        """Return current class definitions."""
        return self.classes.copy()

    def get_class_names(self) -> List[str]:
        """Return list of available class names."""
        return list(self.classes.keys())

    def get_llm_metadata(self) -> Dict[str, Any]:
        """Return LLM provider configuration metadata (non-sensitive)."""
        cfg = self._provider_config
        metadata: Dict[str, Any] = {
            "provider": cfg.name,
            "model": cfg.model,
            "temperature": cfg.temperature,
        }
        if cfg.max_tokens:
            metadata["max_tokens"] = cfg.max_tokens
        if cfg.timeout:
            metadata["timeout"] = cfg.timeout
        if cfg.api_base:
            metadata["api_base"] = cfg.api_base
        return metadata

