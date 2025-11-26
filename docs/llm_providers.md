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

## Multi-Class Classification

The `MultiClassLLMClassifier` provides flexible multi-class classification with custom categories defined via configuration or runtime parameters.

### Features

- **Dynamic Classes**: Define any number of classes (minimum 2) with custom descriptions
- **Config + Runtime**: Load default classes from config.toml and override/extend at runtime
- **Provider Flexibility**: Use any LLM provider (OpenAI, Anthropic, Ollama, LM Studio)
- **Structured Output**: Returns predicted class, confidence score, and reasoning
- **API + CLI**: Available via REST API and command-line interface

### Configuration

Define default classes in `config.toml`:

```toml
[[classification.classes]]
name = "recipe"
description = """A text containing cooking instructions, ingredients, or recipe details.
Examples: 'Boil pasta for 10 minutes', 'Mix flour and eggs'"""

[[classification.classes]]
name = "python_package"
description = """A text about Python packages, libraries, or pip installations.
Examples: 'Install FastAPI with pip', 'This library provides async support'"""

[[classification.classes]]
name = "movie_review"
description = """A text reviewing or discussing movies, films, or TV shows.
Examples: 'Just watched an amazing thriller', 'The acting was superb'"""
```

### Python Usage

**Using classes from config:**

```python
from postparse.services.analysis.classifiers import MultiClassLLMClassifier

classifier = MultiClassLLMClassifier()
result = classifier.predict("Check out this new FastAPI library!")
print(result.label)  # "python_package"
print(result.confidence)  # 0.92
print(result.details['reasoning'])  # "The text mentions FastAPI library..."
```

**Using runtime classes:**

```python
classes = {
    "recipe": "Cooking instructions or ingredients",
    "tech_news": "Technology news or product announcements",
    "sports": "Sports news, scores, or athlete updates"
}

classifier = MultiClassLLMClassifier(classes=classes, provider_name='openai')
result = classifier.predict("Apple announces new iPhone 16")
print(result.label)  # "tech_news"
```

**Batch classification:**

```python
texts = [
    "Boil pasta for 10 minutes",
    "New Python 3.13 released",
    "Great movie last night"
]

results = classifier.predict_batch(texts)
for text, result in zip(texts, results):
    print(f"{text[:30]}... -> {result.label} ({result.confidence:.2f})")
```

### API Usage

**Single classification with runtime classes:**

```bash
curl -X POST "http://localhost:8000/api/v1/classify/multi" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Check out this new FastAPI library!",
    "classes": {
      "recipe": "Cooking instructions",
      "python_package": "Python libraries",
      "movie_review": "Movie discussion"
    },
    "provider_name": "openai"
  }'
```

**Batch classification:**

```bash
curl -X POST "http://localhost:8000/api/v1/classify/multi/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "texts": [
      "Boil pasta for 10 minutes",
      "New Python 3.13 released",
      "Great movie last night"
    ],
    "classes": {
      "recipe": "Cooking instructions",
      "python_package": "Python libraries",
      "movie_review": "Movie discussion"
    }
  }'
```

### CLI Usage

**Ad-hoc classification (doesn't save to database):**

```bash
# Using runtime classes (JSON)
postparse classify text "Apple announces iPhone 16" \
  --classifier multiclass \
  --classes '{"recipe": "Cooking", "tech_news": "Technology news", "sports": "Sports"}'

# Using classes from file
postparse classify text "Some text" --classifier multiclass --classes @classes.json

# With specific provider
postparse classify text "Some text" --classifier multiclass --provider openai
```

**Database classification (saves results):**

```bash
# Classify posts with multiclass
postparse classify db --classifier multiclass \
  --classes '{"recipe": "Cooking", "tech": "Technology"}' \
  --source instagram --limit 100

# Classify messages with multiclass
postparse classify db --classifier multiclass \
  --classes @classes.json \
  --source telegram
```

### Best Practices

1. **Class Descriptions**: Provide clear, detailed descriptions with examples for better accuracy
2. **Number of Classes**: 2-10 classes work best; too many classes reduce accuracy
3. **Provider Selection**: Use GPT-4 or Claude for best accuracy; use Ollama/LM Studio for cost-effective local inference
4. **Confidence Thresholds**: Consider results with confidence < 0.7 as uncertain
5. **Class Overlap**: Avoid overlapping class definitions; make them mutually exclusive

### Troubleshooting

**Low Accuracy:**
- Improve class descriptions with more examples
- Use a more capable model (GPT-4 instead of GPT-3.5)
- Reduce number of classes
- Make class definitions more distinct

**LLM Returns Invalid Class:**
- Check that class descriptions are clear and unambiguous
- Ensure LLM has enough context in the prompt
- Try a different provider/model

**Performance Issues:**
- Use batch endpoints for multiple texts
- Consider caching results for repeated queries
- Use faster models (GPT-3.5, Claude Haiku) for less critical tasks

## See Also

- [Getting Started Guide](getting_started.md) - Initial setup and configuration
- [API Reference](api_reference.md) - Detailed API documentation
- [CLI Reference](cli_reference.md) - Command-line interface documentation
- [LiteLLM Documentation](https://docs.litellm.ai) - LiteLLM provider details

