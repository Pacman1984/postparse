"""
Extract commands for PostParse CLI.

This module provides commands for extracting data from social media platforms
including Telegram and Instagram.

Example:
    $ postparse extract telegram --api-id 12345 --api-hash abc123
    $ postparse extract instagram --username myuser --limit 100
    $ postparse extract all
"""

import os
from pathlib import Path
from typing import Optional

import rich_click as click
from rich.panel import Panel
from rich.table import Table

from backend.postparse.cli.utils import (
    get_console,
    load_config,
    get_database,
    print_success,
    print_error,
    print_info,
    print_warning,
    print_panel,
    create_progress,
    run_async,
    validate_credentials,
)


@click.group(invoke_without_command=True)
@click.pass_context
def extract(ctx):
    """📥 Extract data from Telegram and Instagram.
    
    Runs 'extract all' by default if no platform specified.
    """
    if ctx.invoked_subcommand is None:
        # Default to extracting from all platforms
        ctx.invoke(all_platforms)


@extract.command()
@click.option(
    '--api-id',
    envvar='TELEGRAM_API_ID',
    help='Telegram API ID (or set TELEGRAM_API_ID env var)',
    required=True,
)
@click.option(
    '--api-hash',
    envvar='TELEGRAM_API_HASH',
    help='Telegram API hash (or set TELEGRAM_API_HASH env var)',
    required=True,
)
@click.option(
    '--phone',
    envvar='TELEGRAM_PHONE',
    help='Phone number (will prompt if not provided)',
)
@click.option(
    '--session',
    default='telegram_session',
    help='Session file name (default: telegram_session)',
)
@click.option(
    '--limit',
    type=int,
    help='Maximum messages to extract',
)
@click.option(
    '--force',
    is_flag=True,
    help='Force re-fetch existing messages',
)
@click.pass_context
def telegram(ctx, api_id, api_hash, phone, session, limit, force):
    """
    Extract Telegram messages from your saved messages.
    
    This command connects to Telegram using the Telethon library and extracts
    messages from your Saved Messages folder. Messages are stored in the database
    for later classification and search.
    
    Examples:
        postparse extract telegram --api-id 12345 --api-hash abc123
        
        postparse extract telegram --limit 100 --force
        
        TELEGRAM_API_ID=12345 TELEGRAM_API_HASH=abc123 postparse extract telegram
    
    Note:
        On first run, you'll be prompted to enter your phone number and
        verification code to authenticate with Telegram.
    """
    console = get_console()
    
    try:
        # Load config
        config_path = ctx.obj.get('config')
        config = load_config(config_path)
        
        # Get database
        db = get_database(config)
        
        # Validate credentials
        missing = validate_credentials(
            ['api_id', 'api_hash'],
            {'api_id': api_id, 'api_hash': api_hash}
        )
        if missing:
            print_error(f"Missing required credentials: {', '.join(missing)}")
            raise click.Abort()
        
        print_info("Initializing Telegram parser...")
        
        # Import parser
        from backend.postparse.services.parsers.telegram.telegram_parser import (
            TelegramParser
        )
        
        # Create parser instance
        parser = TelegramParser(
            api_id=int(api_id),
            api_hash=api_hash,
            session_file=session,
            phone=phone,
        )
        
        # Define async extraction function
        async def extract_messages():
            print_info("Connecting to Telegram...")
            
            # Use context manager
            async with parser:
                print_success("Connected to Telegram!")
                print_info("Extracting messages from Saved Messages...")
                
                # Use save_messages_to_db which handles progress internally
                saved_count = await parser.save_messages_to_db(db, limit=limit, force_update=force)
                
                return saved_count
        
        # Run extraction
        saved_count = run_async(extract_messages())
        
        # Display summary
        console.print()
        print_success("Extraction completed!")
        
        table = Table(title="Extraction Summary", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Count", style="green", justify="right")
        
        table.add_row("Messages saved", str(saved_count))
        
        console.print(table)
        
    except click.Abort:
        pass
    except Exception as e:
        print_error(f"Extraction failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()


@extract.command()
@click.option(
    '--username',
    envvar='INSTAGRAM_USERNAME',
    help='Instagram username (or set INSTAGRAM_USERNAME env var)',
    required=True,
)
@click.option(
    '--password',
    envvar='INSTAGRAM_PASSWORD',
    help='Instagram password (or set INSTAGRAM_PASSWORD env var)',
    required=True,
)
@click.option(
    '--session',
    default='instagram_session',
    help='Session file name (default: instagram_session)',
)
@click.option(
    '--limit',
    type=int,
    help='Maximum posts to extract',
)
@click.option(
    '--force',
    is_flag=True,
    help='Force re-fetch existing posts',
)
@click.pass_context
def instagram(ctx, username, password, session, limit, force):
    """
    Extract Instagram posts from your saved posts.
    
    This command uses Instaloader to extract posts from your Instagram
    saved collection. Posts are stored in the database for later
    classification and search.
    
    Examples:
        postparse extract instagram --username myuser --password mypass
        
        postparse extract instagram --limit 50 --force
        
        INSTAGRAM_USERNAME=myuser INSTAGRAM_PASSWORD=mypass postparse extract instagram
    
    Note:
        Instagram may rate limit requests. The extractor will handle
        this gracefully, but extraction may take time for large collections.
    """
    console = get_console()
    
    try:
        # Load config
        config_path = ctx.obj.get('config')
        config = load_config(config_path)
        
        # Get database
        db = get_database(config)
        
        # Validate credentials
        missing = validate_credentials(
            ['username', 'password'],
            {'username': username, 'password': password}
        )
        if missing:
            print_error(f"Missing required credentials: {', '.join(missing)}")
            raise click.Abort()
        
        print_info("Initializing Instagram parser...")
        
        # Import parser
        from backend.postparse.services.parsers.instagram.instagram_parser import (
            InstaloaderParser
        )
        
        # Create parser instance
        parser = InstaloaderParser(
            username=username,
            password=password,
            session_file=session,
        )
        
        print_info("Extracting saved posts...")
        
        # Use save_posts_to_db which handles progress internally
        saved_count = parser.save_posts_to_db(db, limit=limit, force_update=force)
        
        # Display summary
        console.print()
        print_success("Extraction completed!")
        
        table = Table(title="Extraction Summary", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Count", style="green", justify="right")
        
        table.add_row("Posts saved", str(saved_count))
        
        console.print(table)
        
    except click.Abort:
        pass
    except Exception as e:
        print_error(f"Extraction failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()


@extract.command(name='all')
@click.option(
    '--limit',
    type=int,
    help='Maximum items to extract per platform',
)
@click.option(
    '--force',
    is_flag=True,
    help='Force re-fetch existing items',
)
@click.pass_context
def all_platforms(ctx, limit: Optional[int] = None, force: bool = False):
    """
    Extract from all platforms (Telegram and Instagram).

    Extracts data from both Telegram and Instagram. Skips platforms where
    credentials are not provided via environment variables.

    Examples:
        postparse extract all

        postparse extract all --limit 100

        postparse extract all --force

        postparse extract  # Same as 'extract all'
    """
    console = get_console()

    console.print()
    console.print("[bold cyan]📥 Extracting From All Platforms[/bold cyan]")
    console.print()

    # Get credentials from environment
    telegram_api_id = os.getenv('TELEGRAM_API_ID')
    telegram_api_hash = os.getenv('TELEGRAM_API_HASH')
    telegram_phone = os.getenv('TELEGRAM_PHONE')
    telegram_session = 'telegram_session'

    instagram_username = os.getenv('INSTAGRAM_USERNAME')
    instagram_password = os.getenv('INSTAGRAM_PASSWORD')
    instagram_session = 'instagram_session'

    results = {
        'telegram': {'extracted': False, 'count': 0, 'error': None},
        'instagram': {'extracted': False, 'count': 0, 'error': None},
    }

    # Extract from Telegram if credentials provided
    if telegram_api_id and telegram_api_hash:
        print_info("Extracting from Telegram...")
        try:
            ctx.invoke(
                telegram,
                api_id=telegram_api_id,
                api_hash=telegram_api_hash,
                phone=telegram_phone,
                session=telegram_session,
                limit=limit,
                force=force,
            )
            results['telegram']['extracted'] = True
        except click.Abort:
            results['telegram']['error'] = "Aborted"
        except Exception as e:
            results['telegram']['error'] = str(e)
            if ctx.obj and ctx.obj.get('verbose'):
                print_error(f"Telegram extraction failed: {e}")
    else:
        print_warning(
            "Skipping Telegram (no credentials). "
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH."
        )

    console.print()

    # Extract from Instagram if credentials provided
    if instagram_username and instagram_password:
        print_info("Extracting from Instagram...")
        try:
            ctx.invoke(
                instagram,
                username=instagram_username,
                password=instagram_password,
                session=instagram_session,
                limit=limit,
                force=force,
            )
            results['instagram']['extracted'] = True
        except click.Abort:
            results['instagram']['error'] = "Aborted"
        except Exception as e:
            results['instagram']['error'] = str(e)
            if ctx.obj and ctx.obj.get('verbose'):
                print_error(f"Instagram extraction failed: {e}")
    else:
        print_warning(
            "Skipping Instagram (no credentials). "
            "Set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD."
        )

    # Summary
    console.print()
    console.print("[bold cyan]═══════════════════════════════[/bold cyan]")

    extracted_count = sum(1 for r in results.values() if r['extracted'])
    error_count = sum(1 for r in results.values() if r['error'])

    if extracted_count == 0 and error_count == 0:
        print_warning(
            "No platforms extracted. Please set credentials via environment variables."
        )
        console.print()
        console.print("  [dim]# Telegram[/dim]")
        console.print("  export TELEGRAM_API_ID=12345678")
        console.print("  export TELEGRAM_API_HASH=abc123def456")
        console.print()
        console.print("  [dim]# Instagram[/dim]")
        console.print("  export INSTAGRAM_USERNAME=myuser")
        console.print("  export INSTAGRAM_PASSWORD=mypass")
    elif extracted_count > 0:
        print_success(f"Extraction completed for {extracted_count} platform(s)")
        if error_count > 0:
            print_warning(f"{error_count} platform(s) had errors")
    else:
        print_error(f"All {error_count} platform(s) failed")

    console.print()

