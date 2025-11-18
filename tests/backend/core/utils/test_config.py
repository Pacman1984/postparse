"""Tests for configuration management utilities.

This module tests the ConfigManager class and related functions for loading
and managing application configuration from TOML files.
"""
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

from postparse.core.utils.config import (
    ConfigManager, 
    get_config, 
    get_model_config, 
    get_classification_config,
    get_prompt_config,
    get_database_config,
    get_api_config,
    get_paths_config
)


class TestConfigManager:
    """Test cases for ConfigManager class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Clear the LRU cache before each test
        get_config.cache_clear()
    
    def test_init_with_valid_config_path(self):
        """Test ConfigManager initialization with valid config path."""
        # Create a temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write("""
            [models]
            zero_shot_model = "test-model"
            
            [classification]
            min_confidence_threshold = 0.8
            """)
            temp_path = f.name
        
        try:
            config = ConfigManager(temp_path)
            assert config.get('models.zero_shot_model') == "test-model"
            assert config.get('classification.min_confidence_threshold') == 0.8
        finally:
            os.unlink(temp_path)
    
    def test_init_with_invalid_config_path(self):
        """Test ConfigManager initialization with invalid config path."""
        with pytest.raises(FileNotFoundError):
            ConfigManager("/nonexistent/config.toml")
    
    def test_init_without_config_path_finds_default(self):
        """Test ConfigManager initialization without path finds default config."""
        # This test depends on the actual config.toml file existing
        config = ConfigManager()
        # Should not raise an error and should have some config data
        assert isinstance(config._config_data, dict)
    
    def test_get_with_simple_key(self):
        """Test getting configuration value with simple key."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write("""
            [test]
            simple_key = "simple_value"
            """)
            temp_path = f.name
        
        try:
            config = ConfigManager(temp_path)
            assert config.get('test.simple_key') == "simple_value"
        finally:
            os.unlink(temp_path)
    
    def test_get_with_nested_key(self):
        """Test getting configuration value with nested key."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write("""
            [section]
            [section.subsection]
            nested_key = 42
            """)
            temp_path = f.name
        
        try:
            config = ConfigManager(temp_path)
            assert config.get('section.subsection.nested_key') == 42
        finally:
            os.unlink(temp_path)
    
    def test_get_with_default_value(self):
        """Test getting configuration value with default when key doesn't exist."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write("""
            [test]
            existing_key = "exists"
            """)
            temp_path = f.name
        
        try:
            config = ConfigManager(temp_path)
            assert config.get('test.nonexistent_key', default="default_value") == "default_value"
            assert config.get('test.existing_key', default="default_value") == "exists"
        finally:
            os.unlink(temp_path)
    
    def test_get_with_environment_variable_override(self):
        """Test getting configuration value with environment variable override."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write("""
            [test]
            env_key = "config_value"
            """)
            temp_path = f.name
        
        try:
            config = ConfigManager(temp_path)
            
            # Test without environment variable
            assert config.get('test.env_key', env_var='TEST_ENV_VAR') == "config_value"
            
            # Test with environment variable
            with patch.dict(os.environ, {'TEST_ENV_VAR': 'env_value'}):
                assert config.get('test.env_key', env_var='TEST_ENV_VAR') == "env_value"
        finally:
            os.unlink(temp_path)
    
    def test_get_with_environment_variable_type_conversion(self):
        """Test environment variable type conversion based on default value."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write("""
            [test]
            int_key = 10
            float_key = 3.14
            bool_key = true
            """)
            temp_path = f.name
        
        try:
            config = ConfigManager(temp_path)
            
            # Test integer conversion
            with patch.dict(os.environ, {'INT_VAR': '42'}):
                assert config.get('test.int_key', default=10, env_var='INT_VAR') == 42
                assert isinstance(config.get('test.int_key', default=10, env_var='INT_VAR'), int)
            
            # Test float conversion
            with patch.dict(os.environ, {'FLOAT_VAR': '2.718'}):
                assert config.get('test.float_key', default=3.14, env_var='FLOAT_VAR') == 2.718
                assert isinstance(config.get('test.float_key', default=3.14, env_var='FLOAT_VAR'), float)
            
            # Test boolean conversion
            with patch.dict(os.environ, {'BOOL_VAR': 'false'}):
                assert config.get('test.bool_key', default=True, env_var='BOOL_VAR') is False
            
            with patch.dict(os.environ, {'BOOL_VAR': '1'}):
                assert config.get('test.bool_key', default=False, env_var='BOOL_VAR') is True
        finally:
            os.unlink(temp_path)
    
    def test_get_section(self):
        """Test getting entire configuration section."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write("""
            [models]
            zero_shot_model = "test-model"
            default_llm_model = "test-llm"
            
            [classification]
            min_confidence_threshold = 0.8
            """)
            temp_path = f.name
        
        try:
            config = ConfigManager(temp_path)
            models_section = config.get_section('models')
            assert models_section == {
                'zero_shot_model': 'test-model',
                'default_llm_model': 'test-llm'
            }
            
            # Test non-existent section
            empty_section = config.get_section('nonexistent')
            assert empty_section == {}
        finally:
            os.unlink(temp_path)
    
    def test_reload(self):
        """Test configuration reload functionality."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write("""
            [test]
            value = "original"
            """)
            temp_path = f.name
        
        try:
            config = ConfigManager(temp_path)
            assert config.get('test.value') == "original"
            
            # Modify the file
            with open(temp_path, 'w') as f:
                f.write("""
                [test]
                value = "modified"
                """)
            
            # Should still have old value
            assert config.get('test.value') == "original"
            
            # After reload, should have new value
            config.reload()
            assert config.get('test.value') == "modified"
        finally:
            os.unlink(temp_path)
    
    def test_invalid_toml_file(self):
        """Test handling of invalid TOML file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write("invalid toml content [")
            temp_path = f.name
        
        try:
            with pytest.raises(ValueError, match="Invalid TOML configuration file"):
                ConfigManager(temp_path)
        finally:
            os.unlink(temp_path)


class TestConvenienceFunctions:
    """Test cases for convenience functions."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Clear the LRU cache before each test
        get_config.cache_clear()
    
    def test_get_config_caching(self):
        """Test that get_config returns the same instance when called multiple times."""
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2
    
    def test_get_model_config(self):
        """Test get_model_config convenience function."""
        models_config = get_model_config()
        assert isinstance(models_config, dict)
        # Should contain expected keys from the actual config file
        expected_keys = ['zero_shot_model', 'default_llm_model']
        for key in expected_keys:
            assert key in models_config
    
    def test_get_classification_config(self):
        """Test get_classification_config convenience function."""
        classification_config = get_classification_config()
        assert isinstance(classification_config, dict)
        expected_keys = ['recipe_positive_label', 'recipe_negative_label', 'min_confidence_threshold']
        for key in expected_keys:
            assert key in classification_config
    
    def test_get_prompt_config(self):
        """Test get_prompt_config convenience function."""
        prompt_config = get_prompt_config()
        assert isinstance(prompt_config, dict)
        assert 'recipe_analysis_prompt' in prompt_config
    
    def test_get_database_config(self):
        """Test get_database_config convenience function."""
        database_config = get_database_config()
        assert isinstance(database_config, dict)
        expected_keys = ['default_db_path', 'analysis_db_path']
        for key in expected_keys:
            assert key in database_config
    
    def test_get_api_config(self):
        """Test get_api_config convenience function."""
        api_config = get_api_config()
        assert isinstance(api_config, dict)
        expected_keys = ['max_requests_per_session', 'request_delay_min', 'max_retries']
        for key in expected_keys:
            assert key in api_config
    
    def test_get_paths_config(self):
        """Test get_paths_config convenience function."""
        paths_config = get_paths_config()
        assert isinstance(paths_config, dict)
        expected_keys = ['cache_dir', 'downloads_dir', 'models_dir']
        for key in expected_keys:
            assert key in paths_config


class TestIntegrationWithRealConfig:
    """Integration tests using the actual configuration file."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Clear the LRU cache before each test
        get_config.cache_clear()
    
    def test_real_config_loads_successfully(self):
        """Test that the real configuration file loads without errors."""
        config = get_config()
        assert isinstance(config._config_data, dict)
        assert len(config._config_data) > 0
    
    def test_real_config_has_expected_sections(self):
        """Test that the real config file has expected sections."""
        config = get_config()
        expected_sections = ['models', 'classification', 'prompts', 'database', 'api', 'paths']
        for section in expected_sections:
            assert section in config._config_data, f"Missing section: {section}"
    
    def test_real_config_model_values(self):
        """Test that model configuration values are accessible."""
        config = get_config()
        
        # Test model configuration
        zero_shot_model = config.get('models.zero_shot_model')
        assert isinstance(zero_shot_model, str)
        assert len(zero_shot_model) > 0
        
        default_llm_model = config.get('models.default_llm_model')
        assert isinstance(default_llm_model, str)
        assert len(default_llm_model) > 0
    
    def test_real_config_classification_values(self):
        """Test that classification configuration values are accessible."""
        config = get_config()
        
        confidence_threshold = config.get('classification.min_confidence_threshold')
        assert isinstance(confidence_threshold, (int, float))
        assert 0 <= confidence_threshold <= 1
    
    def test_real_config_paths_values(self):
        """Test that path configuration values are accessible."""
        config = get_config()
        
        cache_dir = config.get('paths.cache_dir')
        assert isinstance(cache_dir, str)
        assert len(cache_dir) > 0
        
        downloads_dir = config.get('paths.downloads_dir')
        assert isinstance(downloads_dir, str)
        assert len(downloads_dir) > 0 