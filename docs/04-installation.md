# Installation

## Supported Versions

- **Python**: 3.10 or higher
- **SQLite**: Included with Python
- **UV**: Recommended for package management

## Install with UV

```bash
# Install UV (macOS/Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install UV (Windows)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Install PostParse
uv pip install postparse
```

## Install from Source

```bash
git clone https://github.com/sebpachl/postparse.git
cd postparse
uv venv
uv sync

# With dev dependencies
uv sync --extra dev
```

## Dependencies

- **Telegram**: API credentials from [my.telegram.org](https://my.telegram.org)
- **Instagram**: Valid account credentials
- **LLM classification**: Ollama, LM Studio, or cloud provider (optional)
- **API auth**: `JWT_SECRET_KEY` env var when authentication enabled

## Environment Variables

Place in `config/.env`:

```bash
OPENAI_API_KEY=your_key_here      # OpenAI / LM Studio
ANTHROPIC_API_KEY=your_key_here   # Anthropic Claude
```

## Common Issues

**UV not found**: Install from [astral.sh/uv](https://docs.astral.sh/uv/).

**Telegram auth fails**: Ensure API credentials and phone (with country code) are correct. First run prompts for verification code.

**Instagram rate limits**: Increase delays in `config/config.toml`; reduce posts per session.
