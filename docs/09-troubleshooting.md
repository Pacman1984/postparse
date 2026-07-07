# Troubleshooting

## Telegram Authentication

- **Wrong credentials**: Ensure API credentials from [my.telegram.org](https://my.telegram.org) are correct
- **Phone format**: Include country code (e.g. `+1234567890`)
- **First run**: Prompts for verification code sent to Telegram app

## Instagram Rate Limiting

- **Increase delays**: Edit `config/config.toml` → `[instagram]` → `default_min_delay`, `default_max_delay`
- **Reduce batch size**: Use `--limit` when extracting
- **Wait**: If blocked, wait several hours before retrying

## LLM Provider Issues

**Configuration:**
- Verify `[llm]` section in `config/config.toml`
- Ensure `default_provider` matches a provider in `[[llm.providers]]`

**Ollama:**
- Check server: `curl http://localhost:11434/api/tags`
- Check `api_base` in provider config
- Pull model: `ollama pull qwen3:14b`

**LM Studio:**
- Verify server at `http://localhost:1234`
- Set `OPENAI_API_KEY=dummy`
- Load model in LM Studio UI

**OpenAI / Anthropic:**
- Set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
- Verify account has credits

**Quick test:**
```python
from backend.postparse.services.analysis.classifiers import RecipeLLMClassifier
classifier = RecipeLLMClassifier()
result = classifier.predict("Test recipe: mix flour and water")
print(result.label)
```

## Database Empty

- Run `postparse extract telegram` or `postparse extract instagram` first
- Check `config/config.toml` → `[database]` → `default_db_path`
