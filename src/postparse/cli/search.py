"""
Search commands for PostParse CLI.

This module provides commands for searching stored posts and messages.

Example:
    $ postparse search posts --hashtag recipe
    $ postparse search messages --from 2024-01-01 --limit 100
"""

import json
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
    print_warning,
    truncate_text,
    parse_date,
)


@click.group()
def search():
    """🔍 Search posts and messages with filters."""
    pass


@search.command()
@click.option(
    '--hashtag',
    multiple=True,
    help='Filter by hashtag (can specify multiple)',
)
@click.option(
    '--username',
    help='Filter by owner username',
)
@click.option(
    '--type',
    type=click.Choice(['image', 'video']),
    help='Content type filter',
)
@click.option(
    '--from',
    'from_date',
    help='Start date (YYYY-MM-DD)',
)
@click.option(
    '--to',
    'to_date',
    help='End date (YYYY-MM-DD)',
)
@click.option(
    '--limit',
    type=int,
    default=50,
    help='Maximum results (default: 50)',
)
@click.option(
    '--output',
    type=click.Choice(['table', 'json']),
    default='table',
    help='Output format (default: table)',
)
@click.pass_context
def posts(ctx, hashtag, username, type, from_date, to_date, limit, output):
    """
    Search Instagram posts with filters.
    
    Search through stored Instagram posts using various filters including
    hashtags, username, content type, and date range.
    
    Examples:
        postparse search posts --hashtag recipe
        
        postparse search posts --hashtag recipe --hashtag cooking --type video
        
        postparse search posts --from 2024-01-01 --to 2024-12-31 --limit 100
        
        postparse search posts --username myuser --output json
    
    Note:
        Multiple hashtag filters are combined with AND logic.
        Results are ordered by date (newest first).
    """
    console = get_console()
    
    try:
        # Load config
        config_path = ctx.obj.get('config')
        config = load_config(config_path)
        
        # Get database
        db = get_database(config)
        
        # Parse dates if provided
        date_from = None
        date_to = None
        
        if from_date:
            try:
                date_from = parse_date(from_date)
            except ValueError as e:
                print_error(str(e))
                raise click.Abort()
        
        if to_date:
            try:
                date_to = parse_date(to_date)
            except ValueError as e:
                print_error(str(e))
                raise click.Abort()
        
        # Build date_range tuple
        date_range = None
        if date_from and date_to:
            date_range = (date_from, date_to)
        elif date_from:
            # If only start date, use far future as end
            from datetime import datetime
            date_range = (date_from, datetime(2099, 12, 31))
        elif date_to:
            # If only end date, use far past as start
            from datetime import datetime
            date_range = (datetime(1970, 1, 1), date_to)
        
        # Build filter summary
        filters = []
        if hashtag:
            filters.append(f"hashtags: {', '.join(hashtag)}")
        if username:
            filters.append(f"username: {username}")
        if type:
            filters.append(f"type: {type}")
        if from_date:
            filters.append(f"from: {from_date}")
        if to_date:
            filters.append(f"to: {to_date}")
        
        if filters:
            print_info(f"Searching with filters: {'; '.join(filters)}")
        else:
            print_info("Searching all posts...")
        
        # Search database - always use search method with filters
        next_cursor = None
        if hashtag or username or type or date_range:
            results, next_cursor = db.search_instagram_posts(
                hashtags=list(hashtag) or None,
                date_range=date_range,
                content_type=type,
                owner_username=username,
                limit=limit,
            )
        else:
            # No filters, use simple get method
            results = db.get_instagram_posts(limit=limit)
        
        if not results:
            print_warning("No posts found matching the criteria")
            return
        
        print_success(f"Found {len(results)} post(s)")
        
        # Output results
        if output == 'json':
            output_data = {
                'results': results,
                'next_cursor': next_cursor
            }
            console.print_json(json.dumps(output_data, indent=2, default=str))
        else:
            # Display in table
            table = Table(title=f"Instagram Posts ({len(results)} results)", show_header=True)
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Username", style="green")
            table.add_column("Caption Preview")
            table.add_column("Type", style="yellow")
            table.add_column("Likes", justify="right")
            table.add_column("Date")
            
            for post in results:
                caption = post.get('caption', '')
                caption_preview = truncate_text(caption, 40)
                
                table.add_row(
                    str(post.get('id', '')),
                    post.get('owner_username', ''),
                    caption_preview,
                    post.get('content_type', ''),
                    str(post.get('likes', 0)),
                    post.get('date', '').split('T')[0] if post.get('date') else '',
                )
            
            console.print(table)
            
            # Show pagination info
            if next_cursor:
                print_info(f"More results available. Next cursor: {next_cursor[:20]}...")
            elif len(results) == limit:
                print_info(f"Showing first {limit} results. Use --limit to see more.")
        
    except click.Abort:
        # Re-raise click.Abort so Click can handle it and set exit code to 1
        raise
    except Exception as e:
        print_error(f"Search failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()


@search.command()
@click.option(
    '--hashtag',
    multiple=True,
    help='Filter by hashtag (can specify multiple)',
)
@click.option(
    '--type',
    type=click.Choice(['text', 'photo', 'video']),
    help='Content type filter',
)
@click.option(
    '--from',
    'from_date',
    help='Start date (YYYY-MM-DD)',
)
@click.option(
    '--to',
    'to_date',
    help='End date (YYYY-MM-DD)',
)
@click.option(
    '--limit',
    type=int,
    default=50,
    help='Maximum results (default: 50)',
)
@click.option(
    '--output',
    type=click.Choice(['table', 'json']),
    default='table',
    help='Output format (default: table)',
)
@click.pass_context
def messages(ctx, hashtag, type, from_date, to_date, limit, output):
    """
    Search Telegram messages with filters.
    
    Search through stored Telegram messages using various filters including
    hashtags, content type, and date range.
    
    Examples:
        postparse search messages --hashtag recipe
        
        postparse search messages --hashtag recipe --type photo
        
        postparse search messages --from 2024-01-01 --to 2024-12-31
        
        postparse search messages --output json
    
    Note:
        Multiple hashtag filters are combined with AND logic.
        Results are ordered by date (newest first).
    """
    console = get_console()
    
    try:
        # Load config
        config_path = ctx.obj.get('config')
        config = load_config(config_path)
        
        # Get database
        db = get_database(config)
        
        # Parse dates if provided
        date_from = None
        date_to = None
        
        if from_date:
            try:
                date_from = parse_date(from_date)
            except ValueError as e:
                print_error(str(e))
                raise click.Abort()
        
        if to_date:
            try:
                date_to = parse_date(to_date)
            except ValueError as e:
                print_error(str(e))
                raise click.Abort()
        
        # Build date_range tuple
        date_range = None
        if date_from and date_to:
            date_range = (date_from, date_to)
        elif date_from:
            # If only start date, use far future as end
            from datetime import datetime
            date_range = (date_from, datetime(2099, 12, 31))
        elif date_to:
            # If only end date, use far past as start
            from datetime import datetime
            date_range = (datetime(1970, 1, 1), date_to)
        
        # Build filter summary
        filters = []
        if hashtag:
            filters.append(f"hashtags: {', '.join(hashtag)}")
        if type:
            filters.append(f"type: {type}")
        if from_date:
            filters.append(f"from: {from_date}")
        if to_date:
            filters.append(f"to: {to_date}")
        
        if filters:
            print_info(f"Searching with filters: {'; '.join(filters)}")
        else:
            print_info("Searching all messages...")
        
        # Search database - always use search method with filters
        next_cursor = None
        if hashtag or type or date_range:
            results, next_cursor = db.search_telegram_messages(
                hashtags=list(hashtag) or None,
                date_range=date_range,
                content_type=type,
                limit=limit,
            )
        else:
            # No filters, use simple get method
            results = db.get_telegram_messages(limit=limit)
        
        if not results:
            print_warning("No messages found matching the criteria")
            return
        
        print_success(f"Found {len(results)} message(s)")
        
        # Output results
        if output == 'json':
            output_data = {
                'results': results,
                'next_cursor': next_cursor
            }
            console.print_json(json.dumps(output_data, indent=2, default=str))
        else:
            # Display in table
            table = Table(title=f"Telegram Messages ({len(results)} results)", show_header=True)
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Content Preview")
            table.add_column("Type", style="yellow")
            table.add_column("Views", justify="right")
            table.add_column("Date")
            
            for message in results:
                content = message.get('text', '') or message.get('caption', '') or ''
                content_preview = truncate_text(content, 50)
                
                table.add_row(
                    str(message.get('id', '')),
                    content_preview,
                    message.get('media_type', 'text'),
                    str(message.get('views', 0)),
                    message.get('date', '').split('T')[0] if message.get('date') else '',
                )
            
            console.print(table)
            
            # Show pagination info
            if next_cursor:
                print_info(f"More results available. Next cursor: {next_cursor[:20]}...")
            elif len(results) == limit:
                print_info(f"Showing first {limit} results. Use --limit to see more.")
        
    except click.Abort:
        # Re-raise click.Abort so Click can handle it and set exit code to 1
        raise
    except Exception as e:
        print_error(f"Search failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()

