"""
Main CLI entry point for PostParse.

This module defines the root Click command group and registers all subcommands.

Example:
    $ postparse --help
    $ postparse extract telegram --help
    $ postparse serve
"""

import sys
import os
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.columns import Columns
from rich.traceback import install as install_rich_traceback
import rich_click as click
from dotenv import load_dotenv

# Load environment variables from .env files
# Try multiple locations relative to current working directory and script location
def load_env_files():
    """Load .env files from standard locations."""
    # Get current working directory
    cwd = Path.cwd()
    
    # Try paths relative to current working directory
    env_paths = [
        cwd / 'config' / '.env',
        cwd / '.env',
    ]
    
    # Also try relative to this script's location (for installed package)
    try:
        script_dir = Path(__file__).parent.parent.parent.parent  # Go up to project root
        env_paths.extend([
            script_dir / 'config' / '.env',
            script_dir / '.env',
        ])
    except:
        pass
    
    loaded_path = None
    for env_path in env_paths:
        if env_path.exists():
            # Use absolute path for dotenv
            abs_path = env_path.resolve()
            load_dotenv(abs_path, override=False)  # Don't override existing env vars
            loaded_path = abs_path
            break
    
    # Store for debugging
    if loaded_path:
        os.environ['_POSTPARSE_ENV_FILE'] = str(loaded_path)
    
    return loaded_path

# Load environment variables on module import
_loaded_env = load_env_files()

# Configure rich-click for beautiful help output
click.rich_click.USE_RICH_MARKUP = True
click.rich_click.USE_MARKDOWN = False
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.GROUP_ARGUMENTS_OPTIONS = True
click.rich_click.SHOW_METAVARS_COLUMN = False
click.rich_click.APPEND_METAVARS_HELP = True
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

# Command groups configuration
click.rich_click.COMMAND_GROUPS = {
    "postparse": [
        {
            "name": "Core Commands",
            "commands": ["stats", "info", "check"],
        },
        {
            "name": "Data Operations",
            "commands": ["extract", "classify", "search"],
        },
        {
            "name": "System",
            "commands": ["serve", "db", "config"],
        },
    ]
}

# Install rich traceback handler
install_rich_traceback(show_locals=True)

# Global console instance
console = Console()

# Version
__version__ = "0.1.0"

# ASCII Art Logo
LOGO = r"""
    ____             __     ____                        
   / __ \____  _____/ /_   / __ \____ _______________  
  / /_/ / __ \/ ___/ __/  / /_/ / __ `/ ___/ ___/ _ \ 
 / ____/ /_/ (__  ) /_   / ____/ /_/ / /  (__  )  __/ 
/_/    \____/____/\__/  /_/    \__,_/_/  /____/\___/  
"""


def show_welcome():
    """Display welcome banner with logo and info."""
    # Create gradient logo
    logo_text = Text(LOGO, style="bold")
    logo_text.stylize("cyan", 0, 40)
    logo_text.stylize("blue", 40, 80)
    logo_text.stylize("magenta", 80, 120)
    logo_text.stylize("cyan", 120)
    
    # Create info text
    info = Text()
    info.append("Social Media Content Parser & Analyzer", style="bold yellow")
    info.append("\n\n")
    info.append("✨ Extract ", style="cyan")
    info.append("• ", style="white")
    info.append("🤖 Classify ", style="magenta")
    info.append("• ", style="white")
    info.append("🔍 Search ", style="green")
    info.append("• ", style="white")
    info.append("🚀 Serve", style="blue")
    info.append("\n\n")
    info.append("Version: ", style="dim")
    info.append(__version__, style="bold cyan")
    
    # Create command examples
    examples = Table.grid(padding=(0, 2))
    examples.add_column(style="cyan", justify="right")
    examples.add_column(style="dim")
    
    examples.add_row("💡 Quick Start:", "postparse --help")
    examples.add_row("ℹ️  System Info:", "postparse info")
    examples.add_row("📊 View Stats:", "postparse stats")
    examples.add_row("🔍 Check New:", "postparse check telegram")
    examples.add_row("📥 Extract:", "postparse extract telegram")
    examples.add_row("🏷️  Classify:", "postparse classify single \"Recipe text...\"")
    examples.add_row("🔎 Search:", "postparse search posts --hashtag recipe")
    examples.add_row("⚡ Serve API:", "postparse serve")
    
    # Combine all content
    welcome_content = Text()
    welcome_content.append(logo_text)
    welcome_content.append("\n")
    welcome_content.append(info)
    welcome_content.append("\n\n")
    
    panel = Panel(
        welcome_content,
        border_style="bold cyan",
        padding=(1, 2),
        subtitle="[dim]Use [cyan]postparse COMMAND --help[/cyan] for detailed information[/dim]",
        subtitle_align="center"
    )
    
    console.print(panel)
    console.print()
    console.print(examples)
    console.print()


@click.group(invoke_without_command=True)
@click.option('--config', type=click.Path(exists=True), help='Path to config file')
@click.option('--verbose', is_flag=True, help='Enable verbose output')
@click.option('--quiet', is_flag=True, help='Suppress non-essential output')
@click.version_option(version=__version__, prog_name='postparse')
@click.pass_context
def cli(ctx, config, verbose, quiet):
    """
    PostParse - Social Media Content Parser & Analyzer
    
    Extract, classify, and search social media content from Telegram and Instagram.
    """
    # Ensure ctx.obj exists
    ctx.ensure_object(dict)
    
    # Store global options in context
    ctx.obj['config'] = config
    ctx.obj['verbose'] = verbose
    ctx.obj['quiet'] = quiet
    ctx.obj['console'] = console
    
    # Show welcome banner if no command provided
    if ctx.invoked_subcommand is None and not quiet:
        show_welcome()


@cli.command()
def info():
    """ℹ️  Show installation and version info."""
    from rich.table import Table
    from rich.panel import Panel
    from importlib.metadata import version, PackageNotFoundError
    
    def get_version(package_name: str) -> str:
        """Get package version using importlib.metadata."""
        try:
            return version(package_name)
        except PackageNotFoundError:
            return "[dim]Not installed[/dim]"
    
    # Create main info table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold cyan", no_wrap=True, width=18)
    table.add_column("Value", style="green")
    
    table.add_row("📦 Version", __version__)
    table.add_row("🐍 Python", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    table.add_row("🖱️  Click", get_version("click"))
    table.add_row("✨ Rich", get_version("rich"))
    table.add_row("📱 Telethon", get_version("telethon"))
    table.add_row("📸 Instaloader", get_version("instaloader"))
    table.add_row("⚡ FastAPI", get_version("fastapi"))
    
    # Create panel
    panel = Panel(
        table,
        title="[bold cyan]PostParse Installation Info[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )
    
    console.print()
    console.print(panel)
    console.print()
    
    # Show available commands
    commands = Table(title="[bold yellow]Available Commands[/bold yellow]", show_header=False, box=None)
    commands.add_column("Command", style="cyan", width=12)
    commands.add_column("Description", style="dim")
    
    commands.add_row("stats", "View database statistics")
    commands.add_row("check", "Check for new content")
    commands.add_row("extract", "Extract from Telegram/Instagram")
    commands.add_row("classify", "Classify content (ML/LLM)")
    commands.add_row("search", "Search posts and messages")
    commands.add_row("serve", "Start API server")
    commands.add_row("db", "Database operations")
    commands.add_row("config", "Manage configuration")
    
    console.print(commands)
    console.print()


# Register subcommands
from backend.postparse.cli import extract, classify, search, serve, db, config, check

cli.add_command(extract.extract)
cli.add_command(classify.classify)
cli.add_command(search.search)
cli.add_command(serve.serve)
cli.add_command(db.db)
cli.add_command(config.config)
cli.add_command(check.check)

# Add stats as a top-level alias for convenience
cli.add_command(db.stats, name='stats')


if __name__ == '__main__':
    cli()

