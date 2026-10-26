# Testing

```bash
uv sync --group dev --extra migrate --extra youtube   # what CI installs
uv run pytest -q                                      # whole suite
uv run pytest tests/unit -q                           # unit tests only
uv run pytest -m "not slow"                           # skip slow tests
uv run pytest --run-live tests/integration/llm        # live tests (real LLM servers)
uv run ruff check && uv run ruff format --check && uv run mypy src
```

The suite needs no network, no accounts, no GPU and no Redis. The `asr` extra
is not required: transcription tests use fake backends and tiny generated media
files.

## Layout

| Directory | Contents |
|---|---|
| `tests/unit/` | Per package: `api`, `classification`, `cli`, `collectors`, `core` (database, migrations, repositories, v1 migration), `enrichment`, `llm`, `media`, `services`; `test_env_isolation.py` tests the guards below |
| `tests/integration/api/` | FastAPI app with real services on a seeded temporary database: items, jobs, classification, cache, rate limiting, health, legacy routes, OpenAPI path snapshot |
| `tests/integration/llm/` | Live tests against real LLM providers (marked `live`) |
| `tests/e2e/` | Classify and search workflows end to end: a database written through the collector repositories and the full API built by `create_app` (only the LLM is faked) |
| `tests/fixtures/` | Minimal test `config/config.toml`, a v1 schema (`v1_schema.sql`) for migration tests, the pre-port OpenAPI path list (`openapi_paths_v1.json`) |

## Isolation guards

`tests/conftest.py` isolates every run from the developer's real environment:

* **Working directory**: the session runs in a throw-away directory containing a
  copy of `tests/fixtures/config/config.toml`; all relative default paths
  (database, sessions, downloads) resolve there.
* **`.env` files**: `POSTPARSE_NO_DOTENV=1` is set and python-dotenv is patched so
  that no repository `.env` file is located or read; credential variables
  (`TELEGRAM_*`, `INSTAGRAM_*`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `JWT_SECRET_KEY`) are removed from the environment (kept only with
  `--run-live`).
* **Real config**: `ConfigManager` refuses to load `<repo>/config/config.toml`.
* **Real data**: `sqlite3.connect` fails for any path inside `<repo>/data/`.
* **Network**: pytest-socket allows only loopback hosts
  (`--allow-hosts=127.0.0.1,localhost,::1` in `pyproject.toml`).
* **LLM requests**: `pydantic_ai.models.ALLOW_MODEL_REQUESTS` is false unless
  `--run-live`; model discovery is stubbed; real Redis connections are refused
  (the cache falls back to memory).
* Each test gets a restored `os.environ` and fresh config/settings caches.

Any violation is recorded and fails the session in `pytest_sessionfinish`, even
when the test swallowed the exception.

Deprecation warnings raised by `postparse` itself are errors
(`filterwarnings` in `pyproject.toml`).

## Live tests

Tests marked `@pytest.mark.live` talk to real LLM servers or APIs. They are
skipped unless `--run-live` is passed; then sockets are enabled for them and
API keys exported in the shell (never from `config/.env`) are kept.

## Fakes

| Fake | Used for |
|---|---|
| `tests/fake_llm.py` | Deterministic pydantic-ai `FunctionModel`: reads the label enum from the output schema and picks labels by keywords; `fake_classifier_factory()` plugs it into `ClassificationService` / the API; a prompt containing `EXPLODE` raises |
| `tests/unit/collectors/fakes.py` | Fake Telethon client with real TL message objects; real `instaloader.Post` objects on a fake context that fails on any network request |
| `tests/unit/media/helpers.py` | Tiny generated audio/video files (PyAV), DB rows, fake fetchers and ASR backends |
| `fakeredis`, `respx` | Redis cache tests; mocked HTTP for the enrichment fetchers |

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request on Ubuntu and
Windows with Python 3.12 and 3.13: `uv sync --locked --extra migrate --extra
youtube --group dev`, `ruff check`, `ruff format --check`, `mypy src` and
`pytest -q`, with `PYTHONUTF8=1` and `POSTPARSE_NO_DOTENV=1`.
