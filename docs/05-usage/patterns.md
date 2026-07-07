# Usage Patterns

## Do

- **Use `postparse check`** before extracting to preview new content
- **Set `force_update=False`** for incremental extraction (skip existing)
- **Configure `[llm]` in config.toml** for classification providers
- **Use `--limit`** when testing to avoid long runs
- **Store credentials** in `config/.env`, not in code

## Don't

- **Don't run extract without limits** on first run (can take hours)
- **Don't ignore rate limits**—Instagram will block aggressive requests
- **Don't commit** `config/.env` or session files
- **Don't use `post_exists()` in a loop**—use batch checks instead
