"""
Database commands for PostParse CLI.

This module provides commands for database operations and statistics.

Example:
    $ postparse db stats
    $ postparse db export data.json
"""

import json
import csv
from pathlib import Path
from typing import List, Dict, Any

import rich_click as click
from rich.table import Table
from rich.panel import Panel

from backend.postparse.cli.utils import (
    get_console,
    load_config,
    get_database,
    print_success,
    print_error,
    print_info,
    print_warning,
    create_progress,
)


@click.group()
def db():
    """💾 Database operations and exports."""
    pass


@db.command()
@click.option(
    '--detailed',
    is_flag=True,
    help='Include hashtag distribution',
)
@click.pass_context
def stats(ctx, detailed):
    """📊 Show database statistics and overview."""
    console = get_console()
    
    try:
        # Load config
        config_path = ctx.obj.get('config')
        config = load_config(config_path)
        
        # Get database
        db = get_database(config)
        
        print_info("Computing database statistics...")
        console.print()
        
        # Get basic counts
        posts = db.get_instagram_posts(limit=100000)
        messages = db.get_telegram_messages(limit=100000)
        
        total_posts = len(posts)
        total_messages = len(messages)
        total_items = total_posts + total_messages
        
        # Create a nice summary box at the top
        summary_table = Table.grid(padding=(0, 3))
        summary_table.add_column(style="bold cyan", justify="center", width=15)
        summary_table.add_column(style="bold cyan", justify="center", width=15)
        summary_table.add_column(style="bold cyan", justify="center", width=15)
        summary_table.add_row("📸 Instagram", "📱 Telegram", "📊 Total")
        summary_table.add_row(
            f"[bold green]{total_posts:,}[/bold green]",
            f"[bold blue]{total_messages:,}[/bold blue]",
            f"[bold yellow]{total_items:,}[/bold yellow]"
        )
        
        summary_panel = Panel(
            summary_table,
            title="[bold cyan]📊 Database Overview[/bold cyan]",
            border_style="cyan",
            padding=(1, 2)
        )
        console.print(summary_panel)
        console.print()
        
        # Show help message if database is empty
        if total_items == 0:
            help_message = """[bold yellow]Database is empty![/bold yellow]

To populate your database with data:

[bold cyan]1. Extract from Telegram:[/bold cyan]
   [dim]$[/dim] postparse extract telegram --api-id YOUR_ID --api-hash YOUR_HASH

[bold cyan]2. Extract from Instagram:[/bold cyan]
   [dim]$[/dim] postparse extract instagram --username YOUR_USER --password YOUR_PASS

[bold]Need help?[/bold]
   [dim]$[/dim] postparse extract --help
   [dim]$[/dim] postparse info
"""
            console.print(Panel(
                help_message,
                title="[bold cyan]💡 Getting Started[/bold cyan]",
                border_style="yellow",
                padding=(1, 2)
            ))
            console.print()
            return
        
        # Instagram statistics
        if posts:
            insta_table = Table(title="📸 Instagram Posts", show_header=True, box=None)
            insta_table.add_column("Metric", style="cyan", width=20)
            insta_table.add_column("Value", style="green", justify="right")
            
            insta_table.add_row("Total Posts", f"{total_posts:,}")
            
            # Date range
            post_dates = [p.get('date', '') for p in posts if p.get('date')]
            if post_dates:
                post_dates.sort()
                insta_table.add_row("Oldest Post", post_dates[0].split('T')[0])
                insta_table.add_row("Newest Post", post_dates[-1].split('T')[0])
            
            # Content types
            content_types = {}
            for post in posts:
                ct = post.get('content_type', 'unknown')
                content_types[ct] = content_types.get(ct, 0) + 1
            
            for ct, count in sorted(content_types.items(), key=lambda x: x[1], reverse=True):
                insta_table.add_row(f"  └─ {ct.title()}", f"{count:,}")
            
            console.print(insta_table)
            console.print()
        else:
            print_warning("No Instagram posts found in database")
            console.print()
        
        # Telegram statistics
        if messages:
            telegram_table = Table(title="📱 Telegram Messages", show_header=True, box=None)
            telegram_table.add_column("Metric", style="cyan", width=20)
            telegram_table.add_column("Value", style="blue", justify="right")
            
            telegram_table.add_row("Total Messages", f"{total_messages:,}")
            
            # Date range
            message_dates = [m.get('date', '') for m in messages if m.get('date')]
            if message_dates:
                message_dates.sort()
                telegram_table.add_row("Oldest Message", message_dates[0].split('T')[0])
                telegram_table.add_row("Newest Message", message_dates[-1].split('T')[0])
            
            # Media types
            media_types = {}
            for message in messages:
                mt = message.get('media_type', 'text')
                media_types[mt] = media_types.get(mt, 0) + 1
            
            for mt, count in sorted(media_types.items(), key=lambda x: x[1], reverse=True):
                telegram_table.add_row(f"  └─ {mt.title()}", f"{count:,}")
            
            console.print(telegram_table)
            console.print()
        else:
            print_warning("No Telegram messages found in database")
            console.print()
        
        # Detailed statistics
        if detailed:
            print_info("Computing detailed statistics...")
            
            # Get all hashtags
            all_hashtags = db.get_all_hashtags()
            
            if all_hashtags:
                console.print()
                hashtag_table = Table(title="Top Hashtags", show_header=True)
                hashtag_table.add_column("Rank", style="cyan", justify="right", width=6)
                hashtag_table.add_column("Hashtag", style="green", width=20)
                hashtag_table.add_column("Count", style="yellow", justify="right")
                
                # Count hashtags
                hashtag_counts: Dict[str, int] = {}
                for tag in all_hashtags:
                    hashtag_counts[tag] = hashtag_counts.get(tag, 0) + 1
                
                # Show top 20
                sorted_hashtags = sorted(
                    hashtag_counts.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:20]
                
                for i, (tag, count) in enumerate(sorted_hashtags, 1):
                    hashtag_table.add_row(str(i), tag, str(count))
                
                console.print(hashtag_table)
            else:
                print_warning("No hashtags found in database")
        
        print_success("Statistics computed successfully!")
        
    except click.Abort:
        pass
    except Exception as e:
        print_error(f"Failed to compute statistics: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()


@db.command()
@click.argument('output', type=click.Path())
@click.option(
    '--format',
    type=click.Choice(['json', 'csv']),
    default='json',
    help='Export format',
)
@click.option(
    '--source',
    type=click.Choice(['posts', 'messages', 'all']),
    default='all',
    help='What to export',
)
@click.option(
    '--limit',
    type=int,
    help='Maximum records',
)
@click.pass_context
def export(ctx, output, format, source, limit):
    """💾 Export database to JSON or CSV file."""
    console = get_console()
    
    try:
        # Load config
        config_path = ctx.obj.get('config')
        config = load_config(config_path)
        
        # Get database
        db = get_database(config)
        
        output_path = Path(output)
        
        print_info(f"Exporting data to {output_path}...")
        
        # Collect data
        data: Dict[str, List[Dict[str, Any]]] = {}
        
        if source in ['posts', 'all']:
            print_info("Fetching Instagram posts...")
            posts = db.get_instagram_posts(limit=limit)
            data['instagram_posts'] = posts
            print_success(f"Fetched {len(posts)} Instagram posts")
        
        if source in ['messages', 'all']:
            print_info("Fetching Telegram messages...")
            messages = db.get_telegram_messages(limit=limit)
            data['telegram_messages'] = messages
            print_success(f"Fetched {len(messages)} Telegram messages")
        
        # Export data
        print_info(f"Writing to {output_path}...")
        
        if format == 'json':
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str, ensure_ascii=False)
        
        elif format == 'csv':
            # Export to CSV (separate files for posts and messages)
            if source == 'all':
                print_warning("CSV format exports to separate files for posts and messages")
            
            if 'instagram_posts' in data:
                posts_path = output_path.with_stem(output_path.stem + '_posts')
                with open(posts_path, 'w', newline='', encoding='utf-8') as f:
                    if data['instagram_posts']:
                        writer = csv.DictWriter(f, fieldnames=data['instagram_posts'][0].keys())
                        writer.writeheader()
                        writer.writerows(data['instagram_posts'])
                print_success(f"Exported posts to {posts_path}")
            
            if 'telegram_messages' in data:
                messages_path = output_path.with_stem(output_path.stem + '_messages')
                with open(messages_path, 'w', newline='', encoding='utf-8') as f:
                    if data['telegram_messages']:
                        writer = csv.DictWriter(f, fieldnames=data['telegram_messages'][0].keys())
                        writer.writeheader()
                        writer.writerows(data['telegram_messages'])
                print_success(f"Exported messages to {messages_path}")
        
        # Summary
        total_records = sum(len(v) for v in data.values())
        print_success(f"Export completed! {total_records} records written to {output_path}")
        
    except click.Abort:
        pass
    except Exception as e:
        print_error(f"Export failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()

