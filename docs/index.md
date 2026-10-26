# PostParse documentation

PostParse collects your **saved Telegram messages** and **saved Instagram posts**
into a local SQLite archive (schema v2) and makes them useful: full-text search,
video transcription, link enrichment, LLM summaries and LLM classification into
your own taxonomies. Everything is available through the `postparse` CLI and a
FastAPI REST API that runs on the same services.

Start with the [README](https://github.com/Pacman1984/postparse#readme) for
installation and the quick start, then use these pages:

| Page | Contents |
|---|---|
| [Architecture](architecture.md) | Module map, services, data flow |
| [Database](database.md) | Schema v2: tables, views, timestamps, full-text search, migrations, v1 → v2 mapping |
| [Configuration](configuration.md) | `config.toml` sections, `.env`, `POSTPARSE_*` variables, discovery order |
| [Taxonomies](taxonomies.md) | Defining `[[classification.taxonomies]]`, versioning, scopes, ad-hoc labels |
| [Transcription](transcription.md) | Video transcription backends, CUDA on Windows, throttled backlog |
| [Enrichment](enrichment.md) | Per-link fetching: articles, documents, YouTube, X posts |
| [CLI reference](cli-reference.md) | Every command and option (generated from `--help`) |
| [API reference](api-reference.md) | REST endpoints, jobs, WebSocket, errors, auth, cache |
| [Operations runbook](operations.md) | Backup, migration, daily pipeline, reprocessing, troubleshooting |
| [Testing](testing.md) | Test layout, isolation guards, live tests, fakes, CI |

The project history is in the [changelog](https://github.com/Pacman1984/postparse/blob/master/CHANGELOG.md).
