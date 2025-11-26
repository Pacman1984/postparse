"""
CLI utility functions.

This module provides helper functions for console output, config loading,
database access, progress tracking, and async operation handling.

Example:
    >>> from backend.postparse.cli.utils import get_console, print_success
    >>> console = get_console()
    >>> print_success("Operation completed successfully!")
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, TypeVar

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from backend.postparse.core.utils.config import ConfigManager

# Singleton console instance
_console: Optional[Console] = None

T = TypeVar('T')


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
    content: str,
    title: Optional[str] = None,
    style: str = "cyan",
    expand: bool = False
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
    data: List[Dict[str, Any]],
    title: Optional[str] = None,
    columns: Optional[List[str]] = None
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


def load_config(config_path: Optional[str] = None) -> ConfigManager:
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
                    "Config file not found. Please specify with --config or create config/config.toml"
                )
        
        return config
    except Exception as e:
        raise click.ClickException(f"Failed to load config: {e}")


def validate_config(config_path: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Validate config file and return issues.
    
    Args:
        config_path: Optional path to config file
    
    Returns:
        List of validation issues (empty if valid)
    
    Example:
        >>> issues = validate_config("config/config.toml")
        >>> if issues:
        ...     print(f"Found {len(issues)} issues")
    """
    issues = []
    
    try:
        config = load_config(config_path)
        
        # Check database
        db_path = config.get('database.path') or config.get('database.default_db_path')
        if not db_path:
            issues.append({
                "check": "Database path",
                "status": "fail",
                "message": "Database path not configured"
            })
        
        # Check LLM providers
        llm_providers = config.get_section('llm').get('providers', [])
        if not llm_providers:
            issues.append({
                "check": "LLM providers",
                "status": "warning",
                "message": "No LLM providers configured"
            })
        
    except Exception as e:
        issues.append({
            "check": "Config loading",
            "status": "fail",
            "message": str(e)
        })
    
    return issues


def get_database(config: ConfigManager):
    """
    Get SocialMediaDatabase instance from config.
    
    Args:
        config: Configuration manager
    
    Returns:
        SocialMediaDatabase: Database instance
    
    Example:
        >>> config = load_config()
        >>> db = get_database(config)
        >>> posts = db.get_instagram_posts(limit=10)
    """
    from backend.postparse.core.data.database import SocialMediaDatabase
    
    # Get database path from config (try both 'path' and 'default_db_path')
    db_path = config.get('database.path') or config.get('database.default_db_path', default='data/postparse.db')
    return SocialMediaDatabase(str(db_path))


def format_post(post: Dict[str, Any]) -> Dict[str, str]:
    """
    Format Instagram post for display.
    
    Args:
        post: Post dictionary from database
    
    Returns:
        Formatted post dictionary
    
    Example:
        >>> post = db.get_instagram_posts(limit=1)[0]
        >>> formatted = format_post(post)
        >>> print(formatted["caption_preview"])
    """
    caption = post.get("caption", "")
    caption_preview = caption[:50] + "..." if len(caption) > 50 else caption
    
    return {
        "id": str(post.get("id", "")),
        "username": post.get("owner_username", ""),
        "caption_preview": caption_preview,
        "type": post.get("content_type", ""),
        "likes": str(post.get("likes", 0)),
        "date": post.get("date", "").split("T")[0] if post.get("date") else "",
    }


def format_message(message: Dict[str, Any]) -> Dict[str, str]:
    """
    Format Telegram message for display.
    
    Args:
        message: Message dictionary from database
    
    Returns:
        Formatted message dictionary
    
    Example:
        >>> message = db.get_telegram_messages(limit=1)[0]
        >>> formatted = format_message(message)
        >>> print(formatted["content_preview"])
    """
    content = message.get("text", "") or message.get("caption", "") or ""
    content_preview = content[:50] + "..." if len(content) > 50 else content
    
    return {
        "id": str(message.get("id", "")),
        "content_preview": content_preview,
        "type": message.get("media_type", "text"),
        "views": str(message.get("views", 0)),
        "date": message.get("date", "").split("T")[0] if message.get("date") else "",
    }


def create_progress() -> Progress:
    """
    Create Rich Progress instance with custom columns.
    
    Returns:
        Progress: Configured progress instance
    
    Example:
        >>> with create_progress() as progress:
        ...     task = progress.add_task("Processing...", total=100)
        ...     for i in range(100):
        ...         progress.update(task, advance=1)
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=get_console(),
    )


def run_async(coro: Coroutine[Any, Any, T]) -> T:
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


def validate_credentials(
    required: List[str],
    provided: Dict[str, Optional[str]]
) -> List[str]:
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
    return text[:max_length - 3] + "..."


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
        raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD")

