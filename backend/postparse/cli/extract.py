"""
Extract commands for PostParse CLI.

This module provides commands for extracting data from social media platforms
including Telegram and Instagram.

Example:
    $ postparse extract telegram --api-id 12345 --api-hash abc123
    $ postparse extract instagram --username myuser --limit 100
"""

import os
from pathlib import Path
from typing import Optional

import rich_click as click
from rich.table import Table

from postparse.cli.utils import (
    get_console,
    load_config,
    get_database,
    print_success,
    print_error,
    print_info,
    print_panel,
    create_progress,
    run_async,
    validate_credentials,
)


@click.group()
def extract():
    """📥 Extract data from Telegram and Instagram."""
    pass


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
        from postparse.services.parsers.telegram.telegram_parser import (
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
        from postparse.services.parsers.instagram.instagram_parser import (
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

