# Testing

## Run Tests

```bash
# Install with dev dependencies
uv sync --extra dev

# Run all tests
uv run pytest tests/

# Run with coverage
uv run pytest --cov=backend.postparse tests/

# Run specific test file
uv run pytest tests/unit/backend/cli/test_enrich.py -v
```

## Test Structure

```
tests/
├── unit/           # Isolated unit tests (mocked)
├── integration/    # Tests with external services
└── e2e/            # End-to-end tests
```

## Writing Tests

- Use `pytest` with class-based tests
- Full type annotations and docstrings
- Mirror code folder structure in `tests/`
- Use `uv run pytest` for execution

## Database Tests

Use `testcontainers` with PostgreSQL for tests that require a database.
