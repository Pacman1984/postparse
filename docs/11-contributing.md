# Contributing

## Development Setup

```bash
git clone https://github.com/sebpachl/postparse.git
cd postparse
uv sync --extra dev
```

## Process

1. Fork the repository
2. Create a feature branch
3. Make changes
4. Run tests: `uv run pytest tests/`
5. Submit a pull request

## Code Style

- **PEP 8**: 4-space indents, ≤88-char lines
- **Naming**: `snake_case` (functions/vars), `PascalCase` (classes), `UPPER_CASE` (constants)
- **Docstrings**: Google-style on modules, classes, functions
- **Imports**: Absolute imports

## Documentation

- Keep examples minimal and complete
- Update docs when adding features
- Use active voice and direct instructions
