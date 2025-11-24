"""Configuration management utilities for postparse.

This module provides utilities for loading and managing application configuration
from TOML files, with support for environment variable overrides and default values.
"""
import os
import toml
from pathlib import Path
from typing import Any, Dict, Optional, Union
from functools import lru_cache


class ConfigManager:
    """Configuration manager for postparse application.
    
    This class handles loading configuration from TOML files and provides
    convenient access to configuration values with support for environment
    variable overrides and default values.
    """
    
    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        """Initialize configuration manager.
        
        Args:
            config_path: Path to the configuration file. If None, will search
                        for config.toml in standard locations.
        """
        self._config_path = self._find_config_file(config_path)
        self._config_data = self._load_config()
    
    @property
    def config_path(self) -> str:
        """Get the path to the configuration file as a string.
        
        Returns:
            String representation of the configuration file path
        """
        return str(self._config_path)
    
    def _find_config_file(self, config_path: Optional[Union[str, Path]] = None) -> Path:
        """Find the configuration file.
        
        Args:
            config_path: Explicit path to config file
            
        Returns:
            Path to the configuration file
            
        Raises:
            FileNotFoundError: If configuration file cannot be found
        """
        if config_path:
            path = Path(config_path)
            if path.exists():
                return path
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        # Search in standard locations
        search_paths = [
            Path("config/config.toml"),
            Path("config.toml"),
            Path(__file__).parent.parent.parent.parent / "config" / "config.toml"
        ]
        
        for path in search_paths:
            if path.exists():
                return path
        
        raise FileNotFoundError(
            "Configuration file not found. Searched paths: " + 
            ", ".join(str(p) for p in search_paths)
        )
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from TOML file.
        
        Returns:
            Dictionary containing configuration data
            
        Raises:
            ValueError: If configuration file is invalid
        """
        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                return toml.load(f)
        except toml.TomlDecodeError as e:
            raise ValueError(f"Invalid TOML configuration file: {e}")
        except Exception as e:
            raise ValueError(f"Error loading configuration file: {e}")
    
    def get(self, key_path: str, default: Any = None, env_var: Optional[str] = None) -> Any:
        """Get configuration value with support for nested keys and environment overrides.
        
        Args:
            key_path: Dot-separated path to the configuration key (e.g., 'models.zero_shot_model')
            default: Default value if key is not found
            env_var: Environment variable name to check for override
            
        Returns:
            Configuration value or default
            
        Examples:
            >>> config = ConfigManager()
            >>> config.get('models.zero_shot_model')
            'qwen2.5:72b-instruct'
            >>> config.get('models.timeout', default=30)
            30
            >>> config.get('models.custom_model', env_var='CUSTOM_MODEL')
            # Returns value from CUSTOM_MODEL env var if set, otherwise config value
        """
        # Check environment variable first if specified
        if env_var and env_var in os.environ:
            value = os.environ[env_var]
            # Try to convert to appropriate type based on default
            if default is not None:
                try:
                    if isinstance(default, bool):
                        return value.lower() in ('true', '1', 'yes', 'on')
                    elif isinstance(default, int):
                        return int(value)
                    elif isinstance(default, float):
                        return float(value)
                except (ValueError, TypeError):
                    pass
            return value
        
        # Navigate through nested dictionary
        keys = key_path.split('.')
        current = self._config_data
        
        try:
            for key in keys:
                current = current[key]
            return current
        except (KeyError, TypeError):
            return default
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get entire configuration section.
        
        Args:
            section: Name of the configuration section
            
        Returns:
            Dictionary containing section data or empty dict if not found
        """
        return self._config_data.get(section, {})
    
    def reload(self) -> None:
        """Reload configuration from file."""
        self._config_data = self._load_config()


# Global configuration instance with caching
@lru_cache(maxsize=1)
def get_config(config_path: Optional[Union[str, Path]] = None) -> ConfigManager:
    """Get global configuration manager instance.
    
    This function provides a cached global configuration manager instance.
    The cache ensures that the configuration is loaded only once per application run.
    
    Args:
        config_path: Path to configuration file (only used on first call)
        
    Returns:
        ConfigManager instance
    """
    return ConfigManager(config_path)


# Convenience functions for common configuration access patterns
def get_model_config() -> Dict[str, Any]:
    """Get model configuration section."""
    return get_config().get_section('models')


def get_classification_config() -> Dict[str, Any]:
    """Get classification configuration section."""
    return get_config().get_section('classification')


def get_prompt_config() -> Dict[str, Any]:
    """Get prompts configuration section."""
    return get_config().get_section('prompts')


def get_database_config() -> Dict[str, Any]:
    """Get database configuration section."""
    return get_config().get_section('database')


def get_api_config() -> Dict[str, Any]:
    """Get API configuration section."""
    return get_config().get_section('api')


def get_paths_config() -> Dict[str, Any]:
    """Get paths configuration section."""
    return get_config().get_section('paths') 