"""
CLI utility functions.

This module provides helper functions for console output, config loading,
schema v2 database access (``--db`` / ``Settings.db_path``), progress tracking
and async operation handling.

Example:
    >>> from postparse.cli.utils import get_console, print_success
    >>> console = get_console()
    >>> print_success("Operation completed successfully!")
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from postparse.core.utils.config import ConfigManager

if TYPE_CHECKING:
    from postparse.core.db import Database

# Singleton console instance
_console: Console | None = None

T = TypeVar("T")


def get_console() -> Console:
    """
    Get the singleton Rich Console instance.

    Returns:
        Console: Rich Console instance for styled output

    Example:
        >>> console = get_console()
        >>> console.print("Hello, [bold cyan]World[/]!")
    """
    global _console
    if _console is None:
        _console = Console()
    return _console


def print_success(message: str) -> None:
    """
    Print a success message in green.

    Args:
        message: Success message to display

    Example:
        >>> print_success("Data extracted successfully!")
    """
    console = get_console()
    console.print(f"[bold green]✓[/bold green] {message}", style="green")


def print_error(message: str) -> None:
    """
    Print an error message in red.

    Args:
        message: Error message to display

    Example:
        >>> print_error("Failed to connect to database")
    """
    console = get_console()
    console.print(f"[bold red]✗[/bold red] {message}", style="red")


def print_warning(message: str) -> None:
    """
    Print a warning message in yellow.

    Args:
        message: Warning message to display

    Example:
        >>> print_warning("Rate limit approaching")
    """
    console = get_console()
    console.print(f"[bold yellow]⚠[/bold yellow] {message}", style="yellow")


def print_info(message: str) -> None:
    """
    Print an info message in blue.

    Args:
        message: Info message to display

    Example:
        >>> print_info("Processing 100 items...")
    """
    console = get_console()
    console.print(f"[bold cyan]ℹ[/bold cyan] {message}", style="cyan")


def print_panel(
    content: str, title: str | None = None, style: str = "cyan", expand: bool = False
) -> None:
    """
    Display content in a Rich panel.

    Args:
        content: Content to display in panel
        title: Optional panel title
        style: Panel border style color
        expand: Whether to expand panel to full width

    Example:
        >>> print_panel("Server started successfully", title="Status", style="green")
    """
    console = get_console()
    panel = Panel(content, title=title, border_style=style, expand=expand)
    console.print(panel)


def print_table(
    data: list[dict[str, Any]], title: str | None = None, columns: list[str] | None = None
) -> None:
    """
    Display data in a Rich table.

    Args:
        data: List of dictionaries containing row data
        title: Optional table title
        columns: Optional list of column names (uses dict keys if not provided)

    Example:
        >>> data = [{"id": 1, "name": "Item 1"}, {"id": 2, "name": "Item 2"}]
        >>> print_table(data, title="Results")
    """
    if not data:
        print_warning("No data to display")
        return

    console = get_console()

    # Determine columns
    if columns is None:
        columns = list(data[0].keys())

    # Create table
    table = Table(title=title, show_header=True, header_style="bold cyan")

    # Add columns
    for col in columns:
        table.add_column(col, no_wrap=False)

    # Add rows
    for row in data:
        table.add_row(*[str(row.get(col, "")) for col in columns])

    console.print(table)


def load_config(config_path: str | None = None) -> ConfigManager:
    """
    Load configuration with error handling.

    Args:
        config_path: Optional path to config file (uses default if not provided)

    Returns:
        ConfigManager: Loaded configuration manager

    Raises:
        click.ClickException: If config loading fails

    Example:
        >>> config = load_config("config/config.toml")
        >>> api_port = config.api.port
    """
    import rich_click as click

    try:
        if config_path:
            config = ConfigManager(config_path=Path(config_path))
        else:
            # Try default locations
            default_paths = [
                Path("config/config.toml"),
                Path("config.toml"),
            ]

            for path in default_paths:
                if path.exists():
                    config = ConfigManager(config_path=path)
                    break
            else:
                raise click.ClickException(
                    "Config file not found. Please specify with --config or create "
                    "config/config.toml"
                )

        return config
    except Exception as e:
        raise click.ClickException(f"Failed to load config: {e}") from e


def config_path_from_ctx(ctx: Any) -> str | None:
    """Return the root ``--config`` value stored on the Click context.

    Args:
        ctx: Click context (``None`` is allowed).

    Returns:
        Config file path or ``None``.
    """
    obj = getattr(ctx, "obj", None) or {}
    return obj.get("config")


def resolve_db_path(ctx: Any, db_path: str | None = None) -> Path:
    """Return the schema v2 database path from ``--db`` or ``Settings.db_path``.

    The legacy ``[database] default_db_path`` / ``path`` keys are never used:
    they point at the schema v1 file (see :func:`legacy_db_key_warning`).

    Args:
        ctx: Click context (for the root ``--config`` option).
        db_path: Explicit ``--db`` value.

    Returns:
        Absolute database path.
    """
    if db_path:
        return Path(db_path).expanduser().resolve()
    from postparse.config import get_settings

    settings = get_settings(config_path_from_ctx(ctx))
    assert settings.db_path is not None
    return settings.db_path


def open_database(ctx: Any, db_path: str | None = None) -> Database:
    """Open an existing, up-to-date schema v2 database for reading.

    Nothing is created or migrated: read commands must not change the file.

    Args:
        ctx: Click context.
        db_path: Explicit ``--db`` value.

    Returns:
        Database handle (``migrate=False``).

    Raises:
        click.ClickException: If the file is missing or has pending migrations.
    """
    import rich_click as click

    from postparse.core.db import Database, connect, latest_version

    path = resolve_db_path(ctx, db_path)
    if not path.is_file():
        raise click.ClickException(
            f"Database not found: {path} (run `postparse db migrate` or `postparse db migrate-v1`)"
        )
    conn = connect(path)
    try:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()
    latest = latest_version()
    if version < latest:
        raise click.ClickException(
            f"Database {path} has schema version {version}, expected {latest} "
            "(run `postparse db migrate`)"
        )
    return Database(path, migrate=False)


def legacy_db_key_warning(config_path: str | None = None) -> str | None:
    """Explain an ignored schema v1 database key in the config file.

    Args:
        config_path: Explicit config file (``None``: standard search).

    Returns:
        Warning text when ``[database] default_db_path`` / ``path`` is set but
        ``[database] db_path`` is not; otherwise ``None``.
    """
    try:
        manager = ConfigManager(config_path)
    except FileNotFoundError:
        return None
    section = manager.get_section("database") or {}
    if section.get("db_path"):
        return None
    for key in ("default_db_path", "path"):
        if section.get(key):
            return (
                f"[database] {key} = {section[key]!r} is a schema v1 setting and is ignored; "
                "the schema v2 database comes from [database] db_path / [paths] data_dir "
                "(default data/postparse.db). Convert the old file with "
                "`postparse db migrate-v1 --source <v1.db> --target <v2.db>`."
            )
    return None


def emit_json(data: Any) -> None:
    """Write ``data`` as pretty JSON to stdout (no Rich markup, pipe-safe)."""
    import json

    import rich_click as click

    click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def format_duration(seconds: float) -> str:
    """Format a duration in seconds for CLI display.

    Args:
        seconds: Duration in seconds.

    Returns:
        Human-readable duration string.

    Examples:
        >>> format_duration(12.4)
        '12.4s'
        >>> format_duration(95)
        '1m 35s'
    """
    if seconds < 0:
        seconds = 0.0
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def create_progress(*, show_eta: bool = True) -> Progress:
    """
    Create Rich Progress instance with custom columns.

    Args:
        show_eta: Whether to show estimated time remaining.

    Returns:
        Progress: Configured progress instance

    Example:
        >>> with create_progress() as progress:
        ...     task = progress.add_task("Processing...", total=100)
        ...     for i in range(100):
        ...         progress.update(task, advance=1)
    """
    columns = [
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
    ]
    if show_eta:
        columns.append(TimeRemainingColumn())
    return Progress(*columns, console=get_console())


def run_async(coro: Coroutine[Any, Any, T]) -> T:  # noqa: UP047 - keep pre-PEP 695 syntax
    """
    Run async function in sync context.

    Args:
        coro: Coroutine to run

    Returns:
        Result of the coroutine

    Example:
        >>> async def fetch_data():
        ...     return "data"
        >>> result = run_async(fetch_data())
        >>> print(result)
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(coro)


def validate_credentials(required: list[str], provided: dict[str, str | None]) -> list[str]:
    """
    Check required credentials are provided.

    Args:
        required: List of required credential names
        provided: Dictionary of provided credentials

    Returns:
        List of missing credentials (empty if all provided)

    Example:
        >>> required = ["api_id", "api_hash"]
        >>> provided = {"api_id": "12345", "api_hash": None}
        >>> missing = validate_credentials(required, provided)
        >>> print(missing)  # ["api_hash"]
    """
    missing = []
    for cred in required:
        if not provided.get(cred):
            missing.append(cred)
    return missing


def truncate_text(text: str, max_length: int = 50) -> str:
    """
    Truncate text with ellipsis.

    Args:
        text: Text to truncate
        max_length: Maximum length before truncation

    Returns:
        Truncated text

    Example:
        >>> text = "This is a very long text that needs truncation"
        >>> print(truncate_text(text, 20))
        "This is a very lo..."
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def parse_date(date_str: str) -> datetime:
    """
    Parse date string to datetime.

    Args:
        date_str: Date string in YYYY-MM-DD format

    Returns:
        Datetime object

    Raises:
        ValueError: If date format is invalid

    Example:
        >>> dt = parse_date("2024-01-15")
        >>> print(dt.year, dt.month, dt.day)
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD") from None
