# Configuration

All config files go in `config/` at project root.

## config.toml

```toml
[database]
default_db_path = "data/social_media.db"

[paths]
cache_dir = "data/cache"
telegram_downloads_dir = "data/downloads/telegram"
instagram_downloads_dir = "data/downloads/instagram"

[telegram]
connection_retries = 3
retry_delay = 1
auto_reconnect = true

[instagram]
default_min_delay = 5.0
default_max_delay = 30.0

[llm]
default_provider = "lm_studio"
enable_fallback = true

[[llm.providers]]
name = "ollama"
model = "qwen3:14b"
api_base = "http://localhost:11434"
timeout = 30

[[llm.providers]]
name = "openai"
model = "gpt-4o-mini"
timeout = 30
# API key from OPENAI_API_KEY env var
```

## Environment Variables

Create `config/.env`:

```bash
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
```

## LLM Providers

PostParse uses LiteLLM. Switch providers via `[llm]` in config or `provider_name` in code.

| Provider | API Key | Setup |
|----------|---------|-------|
| Ollama | No | `ollama pull qwen3:14b`, `ollama serve`, set `api_base` |
| LM Studio | Dummy | Start server, `OPENAI_API_KEY=dummy` |
| OpenAI | Yes | `OPENAI_API_KEY=sk-...` |
| Anthropic | Yes | `ANTHROPIC_API_KEY=sk-ant-...` |

### Provider Setup

**Ollama:**
```bash
ollama pull qwen3:14b
ollama serve  # http://localhost:11434
curl http://localhost:11434/api/tags  # verify
```

**LM Studio:**
1. Download from [lmstudio.ai](https://lmstudio.ai)
2. Load model, start Local Server (port 1234)
3. Set `OPENAI_API_KEY=dummy`
4. Config: `api_base = "http://localhost:1234/v1"`

**OpenAI:** Get key at [platform.openai.com](https://platform.openai.com). Set `OPENAI_API_KEY`.

**Anthropic:** Get key at [console.anthropic.com](https://console.anthropic.com). Set `ANTHROPIC_API_KEY`.

### Key Fields

- **name**: Provider ID (`ollama`, `openai`, `lm_studio`, `anthropic`)
- **model**: Model name for that provider
- **api_base**: Custom endpoint (required for local)
- **timeout**, **temperature**, **max_tokens**: Optional

## Switching Providers

```python
classifier = RecipeLLMClassifier()  # default from config
classifier = RecipeLLMClassifier(provider_name='openai')
```

Or change `default_provider` in config.toml.

## Fallback

```toml
[llm]
enable_fallback = true
```

Tries next provider on connection/timeout errors. Does not trigger on auth or config errors.

## Multi-Class / Multi-Label Classes

Define default classes in config (`MultiClassLLMClassifier` and
`MultiLabelLLMClassifier` both use this):

```toml
[[classification.classes]]
name = "recipe"
description = "Cooking instructions, ingredients, recipe details"

[[classification.classes]]
name = "video_content"
description = "Video links/reels/shorts when topical domain is unclear"

[[classification.classes]]
name = "quant_trading"
description = "Market making, microstructure, order flow, execution models"

[[classification.classes]]
name = "crypto_web3"
description = "Blockchain, DeFi, tokenomics, on-chain analytics"

[[classification.classes]]
name = "business_marketing"
description = "Business strategy, ads, funnels, GTM, conversion"
```

Override at runtime via `--classes` or `classes=` in Python.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Connection refused | Ollama: `ollama ps`. LM Studio: start server. |
| API key not found | Set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`. LM Studio: use `dummy`. |
| Model not found | Ollama: `ollama pull <model>`. LM Studio: load model in UI. |
| Provider not found | Match `provider_name` to `name` in `[[llm.providers]]`. |

## Security

- Do not commit `config/.env` or session files
- Store API keys in env vars, not in config.toml

### Session file policy

Session files (Telegram, Instagram) contain credentials and must never be committed:

- **Location**: All session artifacts are written to `data/sessions/` (gitignored via `/data/`)
- **Patterns**: `telegram_session*`, `instagram_session*` (covers dynamic names and SQLite sidecars)
- **API extraction**: Uses `data/sessions/`; CLI may use config `paths.sessions_dir` or `paths.cache_dir`
