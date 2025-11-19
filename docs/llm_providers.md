# LLM Providers Configuration

## Overview

PostParse supports flexible LLM backends via LiteLLM integration through ChatLiteLLM. You can switch providers by editing the `[llm]` section in `config.toml` or by using the `provider_name` parameter in `RecipeLLMClassifier`.

This unified configuration system replaces the old `[models]` section and provides consistent support for:
- **Local providers**: Ollama, LM Studio (no API key, free)
- **Cloud providers**: OpenAI, Anthropic (API key required, pay-per-use)

## Quick Setup

### Local Development (Ollama/LM Studio)
- **No API key required**
- Set `api_base` to localhost endpoint
- Free and private

### Production (OpenAI/Anthropic)
- **API key required** via environment variables
- High-quality models
- Pay-per-use pricing

## Configuration

All LLM providers are configured in the `[llm]` section of `config/config.toml`.

### Configuration Structure

```toml
[llm]
# Default provider to use (must match one of the provider names below)
default_provider = "lm_studio"

# Enable automatic fallback to other providers on failure
enable_fallback = true

# Provider configurations
[[llm.providers]]
name = "lm_studio"
model = "qwen/qwen3-vl-8b"
api_base = "http://localhost:1234/v1"
timeout = 60
temperature = 0.7
```

### Key Fields

- **name**: Provider identifier used in code (`'openai'`, `'ollama'`, `'lm_studio'`, `'anthropic'`)
- **model**: Model name/identifier specific to the provider
- **api_base**: Custom API endpoint (required for local providers)
- **timeout**: Request timeout in seconds
- **temperature**: Sampling temperature (0.0-2.0, higher = more creative)
- **max_tokens**: Maximum tokens in response (optional)

### Example: OpenAI Configuration

```toml
[[llm.providers]]
name = "openai"
model = "gpt-4o-mini"  # Cost-effective model
timeout = 30
temperature = 0.7
max_tokens = 1000
# API key loaded from OPENAI_API_KEY environment variable
```

## Switching Providers

### In Code

Use the `provider_name` parameter to select a specific provider:

```python
from postparse.services.analysis.classifiers import RecipeLLMClassifier

# Use default provider from config
classifier = RecipeLLMClassifier()

# Use specific provider from [llm.providers]
classifier = RecipeLLMClassifier(provider_name='ollama')
classifier = RecipeLLMClassifier(provider_name='openai')
classifier = RecipeLLMClassifier(provider_name='lm_studio')

# Classify content
result = classifier.predict("My pasta recipe: boil pasta, add sauce...")
print(result.label)  # "recipe" or "not_recipe"
```

### In Configuration

Change the `default_provider` value in `config.toml`:

```toml
[llm]
default_provider = "openai"  # Changed from "lm_studio"
```

All code using `RecipeLLMClassifier()` without `provider_name` will now use OpenAI.

## Provider Setup Guides

### Ollama

**Installation:**

```bash
# On macOS and Linux:
curl -fsSL https://ollama.ai/install.sh | sh

# On Windows:
# Download from https://ollama.ai
```

**Pull a model:**

```bash
ollama pull qwen3:14b
# Or: ollama pull llama2, ollama pull mistral, etc.
```

**Start the server:**

```bash
ollama serve
# Runs on http://localhost:11434 by default
```

**Configuration:**

```toml
[[llm.providers]]
name = "ollama"
model = "qwen3:14b"
api_base = "http://localhost:11434"
timeout = 30
temperature = 0.7
# No API key needed
```

**Verify it's running:**

```bash
curl http://localhost:11434/api/tags
```

### LM Studio

**Installation:**

1. Download from [https://lmstudio.ai](https://lmstudio.ai)
2. Install and open LM Studio

**Load a model:**

1. Browse models in LM Studio's interface
2. Download a model (e.g., `qwen/qwen3-vl-8b`)
3. Load the model

**Start local server:**

1. Go to "Local Server" tab in LM Studio
2. Click "Start Server" (default port: 1234)

**Set API key:**

LM Studio uses OpenAI-compatible format, so you need to set a dummy API key:

```bash
# On Unix/macOS:
export OPENAI_API_KEY='dummy'

# On Windows:
set OPENAI_API_KEY=dummy
```

**Configuration:**

```toml
[[llm.providers]]
name = "lm_studio"
model = "qwen/qwen3-vl-8b"  # Model name from LM Studio
api_base = "http://localhost:1234/v1"
timeout = 60
temperature = 0.7
```

### OpenAI

**Get API key:**

1. Sign up at [https://platform.openai.com](https://platform.openai.com)
2. Go to API Keys section
3. Create new API key

**Set API key:**

```bash
# On Unix/macOS:
export OPENAI_API_KEY='sk-...'

# On Windows:
set OPENAI_API_KEY=sk-...

# Or in config/.env:
OPENAI_API_KEY=sk-...
```

**Configuration:**

```toml
[[llm.providers]]
name = "openai"
model = "gpt-4o-mini"  # Cost-effective model
# Or: "gpt-4o", "gpt-4", "gpt-3.5-turbo"
timeout = 30
temperature = 0.7
max_tokens = 1000
```

**Model Recommendations:**
- **Development**: `gpt-4o-mini` (fast, cheap, good quality)
- **Production**: `gpt-4o` (highest quality, more expensive)
- **Legacy**: `gpt-3.5-turbo` (cheapest, lower quality)

### Anthropic

**Get API key:**

1. Sign up at [https://console.anthropic.com](https://console.anthropic.com)
2. Go to API Keys section
3. Create new API key

**Set API key:**

```bash
# On Unix/macOS:
export ANTHROPIC_API_KEY='sk-ant-...'

# On Windows:
set ANTHROPIC_API_KEY=sk-ant-...

# Or in config/.env:
ANTHROPIC_API_KEY=sk-ant-...
```

**Configuration:**

```toml
[[llm.providers]]
name = "anthropic"
model = "claude-3-5-sonnet-20241022"
timeout = 30
temperature = 0.7
max_tokens = 1000
```

**Model Recommendations:**
- **Production**: `claude-3-5-sonnet-20241022` (high quality, balanced)
- **Fast tasks**: `claude-3-haiku-20240307` (fastest, cheaper)
- **Complex tasks**: `claude-3-opus-20240229` (highest quality, most expensive)

## Troubleshooting

### Connection Errors

**Symptom**: `Connection refused` or `Failed to connect`

**Solutions**:
- **Ollama**: Verify it's running with `ollama ps` or `curl http://localhost:11434/api/tags`
- **LM Studio**: Check the local server is started in LM Studio's interface
- **OpenAI/Anthropic**: Check your internet connection

### Authentication Errors

**Symptom**: `API key not found` or `Invalid authentication`

**Solutions**:
- **OpenAI**: Verify `OPENAI_API_KEY` is set: `echo $OPENAI_API_KEY` (Unix) or `echo %OPENAI_API_KEY%` (Windows)
- **Anthropic**: Verify `ANTHROPIC_API_KEY` is set
- **LM Studio**: Set `OPENAI_API_KEY` to any value (e.g., `'dummy'`)
- Restart your terminal/IDE after setting environment variables

### Model Not Found

**Symptom**: `Model not found` or `Model does not exist`

**Solutions**:
- **Ollama**: Pull the model first: `ollama pull qwen3:14b`
- **LM Studio**: Load the model in LM Studio's interface before starting the server
- **OpenAI/Anthropic**: Check model name spelling in config.toml

### Configuration Errors

**Symptom**: `Provider not found in configuration`

**Solutions**:
1. Check that `provider_name` matches a `name` field in `[[llm.providers]]`
2. Verify `default_provider` value exists in providers list
3. Ensure `config/config.toml` has `[llm]` section (not just `[models]`)

### Slow Response Times

**Solutions**:
- **Local models**: Use smaller models or upgrade hardware
- **Cloud providers**: Check your internet connection
- Increase `timeout` value in config.toml
- Consider using faster models (e.g., `gpt-4o-mini` instead of `gpt-4o`)

## Fallback Behavior

Enable automatic fallback to try multiple providers on errors:

```toml
[llm]
enable_fallback = true

# Providers are tried in order if previous ones fail
[[llm.providers]]
name = "lm_studio"  # Try first
# ...

[[llm.providers]]
name = "openai"     # Fallback if LM Studio fails
# ...
```

Fallback triggers on:
- Connection errors (service not running)
- Timeout errors
- Transient API errors (rate limits, temporary outages)

Fallback does **not** trigger on:
- Authentication errors (wrong API key)
- Invalid model names
- Configuration errors

## Migration from Old [models] Section

The old `[models]` section is deprecated. Migrate to `[llm]`:

### Old Configuration (deprecated)

```toml
[models]
default_llm_model = "qwen/qwen3-vl-8b"
llm_provider = "openai"
llm_api_base = "http://localhost:1234/v1"
```

### New Configuration

```toml
[llm]
default_provider = "lm_studio"

[[llm.providers]]
name = "lm_studio"
model = "qwen/qwen3-vl-8b"
api_base = "http://localhost:1234/v1"
```

### Migration Steps

1. Copy model settings from `[models]` to appropriate `[[llm.providers]]` entry
2. Set `default_provider` to your primary provider
3. Update code: change `model_name=` to `provider_name=`
4. Test with: `RecipeLLMClassifier(provider_name='your_provider')`
5. Remove `[models]` section after migration

## Best Practices

1. **Use local models for development**: Faster iteration, no API costs
2. **Use cloud models for production**: Higher quality, no infrastructure needed
3. **Set up fallback providers**: Ensures reliability if primary fails
4. **Keep API keys in environment variables**: Never commit keys to git
5. **Test provider switching**: Verify all providers work before deploying
6. **Monitor costs**: Track OpenAI/Anthropic usage in their dashboards
7. **Use appropriate models**: Balance quality, speed, and cost for your use case

## See Also

- [Getting Started Guide](getting_started.md) - Initial setup and configuration
- [API Reference](api_reference.md) - Detailed API documentation
- [LiteLLM Documentation](https://docs.litellm.ai) - LiteLLM provider details

