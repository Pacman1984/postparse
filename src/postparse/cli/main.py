"""Main CLI entry point for PostParse.

Defines the root Click group, loads ``config/.env`` and registers all
subcommands. Set ``POSTPARSE_NO_DOTENV=1`` to skip loading ``.env`` files.

Example:
    $ postparse --help
    $ postparse stats
    $ postparse search items pasta
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import rich_click as click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.traceback import install as install_rich_traceback

from postparse import __version__


def load_env_files() -> Path | None:
    """Load the first ``.env`` file found in the standard locations.

    Searched: ``./config/.env``, ``./.env`` and the same files relative to the
    project root of this installation. Existing environment variables win.
    Skipped entirely when ``POSTPARSE_NO_DOTENV`` is set.

    Returns:
        Path of the loaded file, or ``None``.
    """
    if os.environ.get("POSTPARSE_NO_DOTENV"):
        return None
    cwd = Path.cwd()
    env_paths = [cwd / "config" / ".env", cwd / ".env"]
    script_dir = Path(__file__).parent.parent.parent.parent  # project root
    env_paths.extend([script_dir / "config" / ".env", script_dir / ".env"])

    for env_path in env_paths:
        if env_path.exists():
            abs_path = env_path.resolve()
            load_dotenv(abs_path, override=False)
            os.environ["_POSTPARSE_ENV_FILE"] = str(abs_path)
            return abs_path
    return None


_loaded_env = load_env_files()

# rich-click help styling
click.rich_click.TEXT_MARKUP = "rich"
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.GROUP_ARGUMENTS_OPTIONS = True
# No separate metavar column; the metavar is appended to the help text instead.
click.rich_click.OPTIONS_TABLE_COLUMN_TYPES = ["required", "opt_short", "opt_long", "help"]
click.rich_click.OPTIONS_TABLE_HELP_SECTIONS = [
    "help",
    "deprecated",
    "envvar",
    "default",
    "required",
    "metavar",
]
click.rich_click.STYLE_ERRORS_SUGGESTION = "magenta italic"
click.rich_click.ERRORS_SUGGESTION = "Try running the '--help' flag for more information."
click.rich_click.ERRORS_EPILOGUE = ""
click.rich_click.MAX_WIDTH = 100
click.rich_click.STYLE_OPTION = "bold cyan"
click.rich_click.STYLE_SWITCH = "bold green"
click.rich_click.STYLE_METAVAR = "bold yellow"
click.rich_click.STYLE_METAVAR_APPEND = "dim"
click.rich_click.STYLE_HEADER_TEXT = "bold magenta"
click.rich_click.STYLE_FOOTER_TEXT = "dim"
click.rich_click.STYLE_USAGE = "yellow"
click.rich_click.STYLE_USAGE_COMMAND = "bold cyan"
click.rich_click.STYLE_HELPTEXT_FIRST_LINE = ""
click.rich_click.STYLE_HELPTEXT = "dim"
click.rich_click.STYLE_OPTION_HELP = "dim"
click.rich_click.STYLE_OPTION_DEFAULT = "dim yellow"
click.rich_click.STYLE_REQUIRED_SHORT = "red"
click.rich_click.STYLE_REQUIRED_LONG = "dim red"
click.rich_click.ALIGN_OPTIONS_PANEL = "left"
click.rich_click.ALIGN_COMMANDS_PANEL = "left"

click.rich_click.COMMAND_GROUPS = {
    "postparse": [
        {"name": "Core Commands", "commands": ["stats", "info", "check", "search"]},
        {
            "name": "Data Operations",
            "commands": ["extract", "classify", "transcribe", "summarize", "enrich"],
        },
        {"name": "System", "commands": ["serve", "db", "config"]},
    ]
}

# show_locals must stay False: locals can contain passwords, api_hash and tokens.
install_rich_traceback(show_locals=False)

console = Console()


LOGO = r"""
    ____             __     ____
   / __ \____  _____/ /_   / __ \____ _______________
  / /_/ / __ \/ ___/ __/  / /_/ / __ `/ ___/ ___/ _ \
 / ____/ /_/ (__  ) /_   / ____/ /_/ / /  (__  )  __/
/_/    \____/____/\__/  /_/    \__,_/_/  /____/\___/
"""


def show_welcome() -> None:
    """Display the welcome banner with logo and quick-start examples."""
    logo_text = Text(LOGO, style="bold")
    logo_text.stylize("cyan", 0, 40)
    logo_text.stylize("blue", 40, 80)
    logo_text.stylize("magenta", 80, 120)
    logo_text.stylize("cyan", 120)

    info_text = Text()
    info_text.append("Social Media Content Parser & Analyzer", style="bold yellow")
    info_text.append("\n\n")
    info_text.append("✨ Extract ", style="cyan")
    info_text.append("• ", style="white")
    info_text.append("🤖 Classify ", style="magenta")
    info_text.append("• ", style="white")
    info_text.append("🔍 Search ", style="green")
    info_text.append("• ", style="white")
    info_text.append("🚀 Serve", style="blue")
    info_text.append("\n\n")
    info_text.append("Version: ", style="dim")
    info_text.append(__version__, style="bold cyan")

    examples = Table.grid(padding=(0, 2))
    examples.add_column(style="cyan", justify="right")
    examples.add_column(style="dim")
    examples.add_row("💡 Quick Start:", "postparse --help")
    examples.add_row("ℹ️  System Info:", "postparse info")
    examples.add_row("📊 View Stats:", "postparse stats")
    examples.add_row("🩺 Health Check:", "postparse check")
    examples.add_row("📥 Extract:", "postparse extract all")
    examples.add_row("🏷️  Classify:", "postparse classify run --taxonomy topics")
    examples.add_row("🔎 Search:", "postparse search items pasta --tag recipe")
    examples.add_row("⚡ Serve API:", "postparse serve")

    content = Text()
    content.append(logo_text)
    content.append("\n")
    content.append(info_text)
    content.append("\n\n")
    console.print(
        Panel(
            content,
            border_style="bold cyan",
            padding=(1, 2),
            subtitle="[dim]Use [cyan]postparse COMMAND --help[/cyan] for detailed information[/dim]",
            subtitle_align="center",
        )
    )
    console.print()
    console.print(examples)
    console.print()


@click.group(invoke_without_command=True)
@click.option("--config", type=click.Path(exists=True), help="Path to config file")
@click.option("--verbose", is_flag=True, help="Enable verbose output")
@click.option("--quiet", is_flag=True, help="Suppress non-essential output")
@click.version_option(version=__version__, prog_name="postparse")
@click.pass_context
def cli(ctx: click.Context, config: str | None, verbose: bool, quiet: bool) -> None:
    """PostParse - Social Media Content Parser & Analyzer

    Extract, classify, transcribe and search saved Telegram and Instagram content.
    """
    ctx.ensure_object(dict)
    ctx.obj["config"] = config
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    ctx.obj["console"] = console
    if ctx.invoked_subcommand is None and not quiet:
        show_welcome()


def _package_version(name: str) -> str:
    """Return the installed version of ``name`` or a dim placeholder."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(name)
    except PackageNotFoundError:
        return "[dim]Not installed[/dim]"


def _database_rows(ctx: click.Context) -> list[tuple[str, str]]:
    """Describe the schema v2 database without creating or migrating it."""
    from postparse.cli.utils import resolve_db_path
    from postparse.core.db import connect, latest_version
    from postparse.services.stats import database_size

    try:
        path = resolve_db_path(ctx)
    except Exception as exc:  # noqa: BLE001 - info must never crash on bad config
        return [("💾 Database", f"[red]{exc}[/red]")]
    rows = [("💾 Database", str(path))]
    if not path.is_file():
        rows.append(("   Status", "[yellow]not found (postparse db migrate)[/yellow]"))
        return rows
    try:
        conn = connect(path)
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            items = int(conn.execute("SELECT count(*) FROM items").fetchone()[0]) if version else 0
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        rows.append(("   Status", f"[red]unreadable: {exc}[/red]"))
        return rows
    latest = latest_version()
    schema = f"v{version}" + ("" if version >= latest else f" (v{latest} available)")
    size_mb = database_size(path) / (1024 * 1024)
    rows.append(("   Schema / items", f"{schema} / {items:,}"))
    rows.append(("   Size", f"{size_mb:,.1f} MB"))
    return rows


@cli.command()
@click.pass_context
def info(ctx: click.Context) -> None:
    """ℹ️  Show installation, paths and database info."""
    from postparse.config import get_settings

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold cyan", no_wrap=True, width=20)
    table.add_column("Value", style="green", overflow="fold")
    py = sys.version_info
    table.add_row("📦 Version", __version__)
    table.add_row("🐍 Python", f"{py.major}.{py.minor}.{py.micro}")
    for label, package in (
        ("🖱️  Click", "click"),
        ("✨ Rich", "rich"),
        ("📱 Telethon", "telethon"),
        ("📸 Instaloader", "instaloader"),
        ("⚡ FastAPI", "fastapi"),
        ("🤖 OpenAI SDK", "openai"),
        ("🎙️ faster-whisper", "faster-whisper"),
    ):
        table.add_row(label, _package_version(package))
    try:
        settings = get_settings((ctx.obj or {}).get("config"))
        table.add_row("📁 Data dir", str(settings.data_dir))
        table.add_row("🔑 Sessions dir", str(settings.sessions_dir))
        table.add_row("⬇️  Downloads dir", str(settings.downloads_dir))
    except Exception as exc:  # noqa: BLE001 - info must never crash on bad config
        table.add_row("📁 Paths", f"[red]{exc}[/red]")
    for key, value in _database_rows(ctx):
        table.add_row(key, value)

    console.print()
    console.print(
        Panel(
            table,
            title="[bold cyan]PostParse Installation Info[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print()

    commands = Table(
        title="[bold yellow]Available Commands[/bold yellow]", show_header=False, box=None
    )
    commands.add_column("Command", style="cyan", width=12)
    commands.add_column("Description", style="dim")
    for name, description in (
        ("stats", "Database statistics (counts, queues, coverage)"),
        ("check", "Health checks (db, transcription, sessions, LLM)"),
        ("search", "Full-text search with filters"),
        ("extract", "Collect from Telegram/Instagram"),
        ("classify", "Classify content into taxonomies (LLM)"),
        ("enrich", "Fetch linked pages, videos and posts"),
        ("transcribe", "Transcribe saved videos"),
        ("summarize", "Summarize transcribed items"),
        ("serve", "Start API server"),
        ("db", "Export and database maintenance"),
        ("config", "Show and validate configuration"),
    ):
        commands.add_row(name, description)
    console.print(commands)
    console.print()


# Register subcommands (imported late: they import this module's console indirectly).
from postparse.cli import (  # noqa: E402
    check,
    classify,
    db,
    enrich,
    extract,
    search,
    serve,
    summarize,
    transcribe,
)
from postparse.cli import config as config_cmd  # noqa: E402

cli.add_command(extract.extract)
cli.add_command(classify.classify)
cli.add_command(search.search)
cli.add_command(serve.serve)
cli.add_command(db.db)
cli.add_command(config_cmd.config)
cli.add_command(check.check)
cli.add_command(enrich.enrich)
cli.add_command(transcribe.transcribe)
cli.add_command(summarize.summarize)

# Top-level alias for convenience.
cli.add_command(db.stats, name="stats")


def configure_stdio_utf8(streams: Iterable[Any] | None = None) -> None:
    """Switch non-UTF-8 text streams to UTF-8 with ``errors="replace"``.

    On Windows, piped or redirected output (``postparse --help | more``) uses
    the ANSI code page (e.g. cp1252), which cannot encode the emoji and box
    characters rendered by rich / rich-click and crashes with
    ``UnicodeEncodeError``. Reconfiguring the streams avoids that.

    Args:
        streams: Streams to reconfigure. Defaults to ``(sys.stdout, sys.stderr)``.
    """
    if streams is None:
        streams = (sys.stdout, sys.stderr)
    for stream in streams:
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        reconfigure = getattr(stream, "reconfigure", None)
        if encoding == "utf8" or reconfigure is None:
            continue
        # A stream already in use in a way that forbids reconfiguring is kept.
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    """Console-script entry point: make stdio UTF-8 safe, then run the CLI."""
    configure_stdio_utf8()
    cli()


if __name__ == "__main__":
    main()
