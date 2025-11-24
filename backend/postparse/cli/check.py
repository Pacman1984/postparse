"""
Check commands for PostParse CLI.

This module provides commands to check for new content without downloading it.

Example:
    $ postparse check telegram
    $ postparse check instagram
"""

import rich_click as click
from rich.table import Table
from rich.panel import Panel
from datetime import datetime, timedelta

from postparse.cli.utils import (
    get_console,
    load_config,
    get_database,
    print_success,
    print_error,
    print_info,
    print_warning,
    run_async,
    validate_credentials,
)


@click.group(invoke_without_command=True)
@click.pass_context
def check(ctx):
    """
    🔍 Check for new content without downloading.
    
    Runs 'check all' by default if no platform specified.
    """
    if ctx.invoked_subcommand is None:
        # Default to checking all platforms
        ctx.invoke(all_platforms)


@check.command()
@click.option(
    '--api-id',
    envvar='TELEGRAM_API_ID',
    help='Telegram API ID',
    required=True,
)
@click.option(
    '--api-hash',
    envvar='TELEGRAM_API_HASH',
    help='Telegram API hash',
    required=True,
)
@click.option(
    '--phone',
    envvar='TELEGRAM_PHONE',
    help='Phone number',
)
@click.option(
    '--session',
    default='telegram_session',
    help='Session file name',
)
@click.pass_context
def telegram(ctx, api_id, api_hash, phone, session):
    """
    Check for new Telegram messages.
    
    Connects to Telegram and checks what new messages are available
    without downloading them. Shows latest message time and estimated
    new message count.
    
    Examples:
        postparse check telegram
        
        postparse check telegram --api-id 12345 --api-hash abc123
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
        
        print_info("Connecting to Telegram...")
        
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
        
        # Define async check function
        async def check_messages():
            stats = {
                'total_available': 0,
                'new': 0,
                'existing': 0,
                'latest_date': None,
            }
            
            # Use async context manager
            async with parser:
                print_success("Connected to Telegram!")
                print_info("Quick check: sampling 20 newest messages...")
                
                # Check only 20 messages for quick estimate (much faster!)
                count = 0
                async for message_dict in parser.get_saved_messages(limit=20, db=None):
                    stats['total_available'] += 1
                    count += 1
                    
                    # Update latest date
                    if message_dict.get('date') and not stats['latest_date']:
                        stats['latest_date'] = message_dict['date']
                    
                    # Check if this message exists in database
                    if db.message_exists(message_dict['message_id']):
                        stats['existing'] += 1
                    else:
                        stats['new'] += 1
                    
                    # Stop at 20 for quick check
                    if count >= 20:
                        break
            
            return stats
        
        # Run check
        stats = run_async(check_messages())
        
        # Get last sync info from database
        messages = db.get_telegram_messages(limit=1)
        last_sync = None
        total_in_db = len(db.get_telegram_messages(limit=10000))
        
        if messages:
            last_msg = messages[0]
            if last_msg.get('date'):
                try:
                    last_sync = datetime.fromisoformat(last_msg['date'].replace('Z', '+00:00'))
                except:
                    pass
        
        # Display results
        console.print()
        
        # Create info table
        info_table = Table(show_header=False, box=None, padding=(0, 2))
        info_table.add_column("Item", style="cyan", width=20)
        info_table.add_column("Value", style="green")
        
        # Latest message info
        if stats['latest_date']:
            try:
                latest_dt = datetime.fromisoformat(stats['latest_date'].replace('Z', '+00:00'))
                time_ago = datetime.now(latest_dt.tzinfo) - latest_dt
                
                if time_ago.days > 0:
                    time_str = f"{time_ago.days} day(s) ago"
                elif time_ago.seconds >= 3600:
                    time_str = f"{time_ago.seconds // 3600} hour(s) ago"
                else:
                    time_str = f"{time_ago.seconds // 60} minute(s) ago"
                
                info_table.add_row("Latest message", time_str)
            except:
                info_table.add_row("Latest message", "Unknown")
        
        # Last sync info
        if last_sync:
            sync_ago = datetime.now(last_sync.tzinfo) - last_sync
            if sync_ago.days > 0:
                sync_str = f"{sync_ago.days} day(s) ago"
            elif sync_ago.seconds >= 3600:
                sync_str = f"{sync_ago.seconds // 3600} hour(s) ago"
            else:
                sync_str = f"{sync_ago.seconds // 60} minute(s) ago"
            info_table.add_row("Last sync", sync_str)
        else:
            info_table.add_row("Last sync", "Never")
        
        # Message counts
        info_table.add_row("In database", f"{total_in_db:,} messages")
        info_table.add_row("Sample size", f"{stats['total_available']} checked")
        
        # Calculate percentages
        skipped = stats['total_available'] - stats['new']
        if stats['total_available'] > 0:
            new_percent = (stats['new'] / stats['total_available']) * 100
            info_table.add_row("Already extracted", f"{skipped} ({100-new_percent:.0f}%)")
        
        # New messages estimate
        if stats['new'] > 0:
            info_table.add_row("New in sample", f"{stats['new']} ({new_percent:.0f}%)", style="bold yellow")
            
            # If all checked messages are new, there are likely more
            if stats['new'] == stats['total_available'] and stats['total_available'] >= 15:
                info_table.add_row("Estimate", "⚠ Likely many more!", style="bold yellow")
                info_table.add_row("", "")
                info_table.add_row("Action needed", "Extract all new messages", style="bold green")
            else:
                info_table.add_row("", "")
                info_table.add_row("Action needed", f"Extract ~{stats['new']} new message(s)", style="bold green")
        else:
            info_table.add_row("New messages", "✓ Up to date", style="green")
        
        panel = Panel(
            info_table,
            title="[bold cyan]📱 Telegram Status[/bold cyan]",
            border_style="cyan",
            padding=(1, 2)
        )
        
        console.print(panel)
        console.print()
        
        # Recommendation
        if stats['new'] > 0:
            console.print()
            if stats['new'] == stats['total_available'] and stats['total_available'] >= 15:
                print_warning(f"All {stats['new']} checked messages are new! There are likely many more.")
                print_info("Run without limit to extract all: [bold cyan]postparse extract telegram[/bold cyan]")
            else:
                print_success(f"Found {stats['new']} new message(s) in sample!")
                print_info("To extract: [bold cyan]postparse extract telegram[/bold cyan]")
        else:
            console.print()
            print_success("✓ All recent messages are already extracted!")
        
    except click.Abort:
        pass
    except Exception as e:
        print_error(f"Check failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()


@check.command()
@click.option(
    '--username',
    envvar='INSTAGRAM_USERNAME',
    help='Instagram username',
    required=True,
)
@click.option(
    '--password',
    envvar='INSTAGRAM_PASSWORD',
    help='Instagram password',
    required=True,
)
@click.option(
    '--session',
    default='instagram_session',
    help='Session file name',
)
@click.pass_context
def instagram(ctx, username, password, session):
    """
    Check for new Instagram posts.
    
    Connects to Instagram and checks what new saved posts are available
    without downloading them. Shows latest post time and estimated
    new post count.
    
    Examples:
        postparse check instagram
        
        postparse check instagram --username myuser --password mypass
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
        
        print_info("Connecting to Instagram...")
        
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
        
        print_success("Connected to Instagram!")
        print_info("Quick check: sampling 20 newest posts...")
        
        stats = {
            'total_available': 0,
            'new': 0,
            'existing': 0,
            'latest_date': None,
        }
        
        # Check first 20 posts to get an estimate (much faster!)
        # Note: get_saved_posts with db parameter only yields NEW posts (skips existing)
        # So we need to count differently
        count = 0
        for post_dict in parser.get_saved_posts(limit=20, db=None):  # Don't pass db to get all
            count += 1
            stats['total_available'] += 1
            
            # Update latest date
            if post_dict.get('date') and not stats['latest_date']:
                stats['latest_date'] = post_dict['date']
            
            # Check if this post exists in database
            if db.post_exists(post_dict['shortcode']):
                stats['existing'] += 1
            else:
                stats['new'] += 1
            
            # Stop at 20 for quick check
            if count >= 20:
                break
        
        # Get last sync info from database
        posts = db.get_instagram_posts(limit=1)
        last_sync = None
        total_in_db = len(db.get_instagram_posts(limit=10000))
        
        if posts:
            last_post = posts[0]
            if last_post.get('date'):
                try:
                    last_sync = datetime.fromisoformat(last_post['date'].replace('Z', '+00:00'))
                except:
                    pass
        
        # Display results
        console.print()
        
        # Create info table
        info_table = Table(show_header=False, box=None, padding=(0, 2))
        info_table.add_column("Item", style="cyan", width=20)
        info_table.add_column("Value", style="green")
        
        # Latest post info
        if stats['latest_date']:
            try:
                latest_dt = datetime.fromisoformat(stats['latest_date'].replace('Z', '+00:00'))
                time_ago = datetime.now(latest_dt.tzinfo) - latest_dt
                
                if time_ago.days > 0:
                    time_str = f"{time_ago.days} day(s) ago"
                elif time_ago.seconds >= 3600:
                    time_str = f"{time_ago.seconds // 3600} hour(s) ago"
                else:
                    time_str = f"{time_ago.seconds // 60} minute(s) ago"
                
                info_table.add_row("Latest post", time_str)
            except:
                info_table.add_row("Latest post", "Unknown")
        
        # Last sync info
        if last_sync:
            sync_ago = datetime.now(last_sync.tzinfo) - last_sync
            if sync_ago.days > 0:
                sync_str = f"{sync_ago.days} day(s) ago"
            elif sync_ago.seconds >= 3600:
                sync_str = f"{sync_ago.seconds // 3600} hour(s) ago"
            else:
                sync_str = f"{sync_ago.seconds // 60} minute(s) ago"
            info_table.add_row("Last sync", sync_str)
        else:
            info_table.add_row("Last sync", "Never")
        
        # Post counts
        info_table.add_row("In database", f"{total_in_db:,} posts")
        info_table.add_row("Sample size", f"{stats['total_available']} checked")
        
        # Calculate percentages
        if stats['total_available'] > 0:
            new_percent = (stats['new'] / stats['total_available']) * 100
            info_table.add_row("Already extracted", f"{stats['existing']} ({100-new_percent:.0f}%)")
        
        # New posts estimate
        if stats['new'] > 0:
            info_table.add_row("New in sample", f"{stats['new']} ({new_percent:.0f}%)", style="bold yellow")
            
            # If all checked posts are new, there are likely more
            if stats['new'] == stats['total_available'] and stats['total_available'] >= 15:
                info_table.add_row("Estimate", "⚠ Likely many more!", style="bold yellow")
                info_table.add_row("", "")
                info_table.add_row("Action needed", "Extract all new posts", style="bold green")
            else:
                info_table.add_row("", "")
                info_table.add_row("Action needed", f"Extract ~{stats['new']} new post(s)", style="bold green")
        else:
            info_table.add_row("New posts", "✓ Up to date", style="green")
        
        panel = Panel(
            info_table,
            title="[bold cyan]📸 Instagram Status[/bold cyan]",
            border_style="cyan",
            padding=(1, 2)
        )
        
        console.print(panel)
        console.print()
        
        # Recommendation
        if stats['new'] > 0:
            console.print()
            if stats['new'] == stats['total_available'] and stats['total_available'] >= 15:
                print_warning(f"All {stats['new']} checked posts are new! There are likely many more.")
                print_info("Run without limit to extract all: [bold cyan]postparse extract instagram[/bold cyan]")
            else:
                print_success(f"Found {stats['new']} new post(s) in sample!")
                print_info("To extract: [bold cyan]postparse extract instagram[/bold cyan]")
        else:
            console.print()
            print_success("✓ All recent posts are already extracted!")
        
    except click.Abort:
        pass
    except Exception as e:
        print_error(f"Instagram check failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()


@check.command(name='all')
@click.pass_context
def all_platforms(ctx):
    """
    Check all platforms for new content.
    
    Checks both Telegram and Instagram. Skips platforms where
    credentials are not provided.
    
    Examples:
        postparse check all
        
        postparse check  # Same as 'check all'
    """
    import os
    console = get_console()
    
    console.print()
    console.print("[bold cyan]🔍 Checking All Platforms[/bold cyan]")
    console.print()
    
    # Get credentials from environment
    telegram_api_id = os.getenv('TELEGRAM_API_ID')
    telegram_api_hash = os.getenv('TELEGRAM_API_HASH')
    telegram_phone = os.getenv('TELEGRAM_PHONE')
    telegram_session = 'telegram_session'
    
    instagram_username = os.getenv('INSTAGRAM_USERNAME')
    instagram_password = os.getenv('INSTAGRAM_PASSWORD')
    instagram_session = 'instagram_session'
    
    # Load config and check database first
    config_path = ctx.obj.get('config')
    config = load_config(config_path)
    db = get_database(config)
    
    # Get database info
    db_path = config.get('database.path') or config.get('database.default_db_path', default='data/postparse.db')
    
    try:
        posts = db.get_instagram_posts(limit=10000)
        messages = db.get_telegram_messages(limit=10000)
        total_posts = len(posts)
        total_messages = len(messages)
        total_items = total_posts + total_messages
        
        # Show database status
        db_table = Table(show_header=False, box=None, padding=(0, 2))
        db_table.add_column("Item", style="cyan", width=20)
        db_table.add_column("Value", style="green")
        
        db_table.add_row("Database location", str(db_path))
        db_table.add_row("Instagram posts", f"{total_posts:,}")
        db_table.add_row("Telegram messages", f"{total_messages:,}")
        db_table.add_row("Total items", f"{total_items:,}")
        
        if total_items == 0:
            db_status = "empty"
            db_style = "yellow"
            db_icon = "⚠"
        else:
            db_status = "has data"
            db_style = "green"
            db_icon = "✓"
        
        db_panel = Panel(
            db_table,
            title=f"[bold {db_style}]{db_icon} Database Status: {db_status.upper()}[/bold {db_style}]",
            border_style=db_style,
            padding=(1, 2)
        )
        
        console.print(db_panel)
        console.print()
        
    except Exception as e:
        print_warning(f"Could not read database: {e}")
        console.print()
    
    results = {
        'telegram': {'checked': False, 'has_new': False, 'error': None},
        'instagram': {'checked': False, 'has_new': False, 'error': None},
    }
    
    # Check Telegram if credentials provided
    if telegram_api_id and telegram_api_hash:
        print_info("Checking Telegram...")
        try:
            ctx.invoke(
                telegram,
                api_id=telegram_api_id,
                api_hash=telegram_api_hash,
                phone=telegram_phone,
                session=telegram_session
            )
            results['telegram']['checked'] = True
            results['telegram']['has_new'] = True  # Assume yes if no error
        except Exception as e:
            results['telegram']['error'] = str(e)
            if ctx.obj.get('verbose'):
                print_error(f"Telegram check failed: {e}")
    else:
        print_warning("Skipping Telegram (no credentials). Set TELEGRAM_API_ID and TELEGRAM_API_HASH.")
    
    console.print()
    
    # Check Instagram if credentials provided
    if instagram_username and instagram_password:
        print_info("Checking Instagram...")
        try:
            ctx.invoke(
                instagram,
                username=instagram_username,
                password=instagram_password,
                session=instagram_session
            )
            results['instagram']['checked'] = True
            results['instagram']['has_new'] = True  # Assume yes if no error
        except Exception as e:
            results['instagram']['error'] = str(e)
            if ctx.obj.get('verbose'):
                print_error(f"Instagram check failed: {e}")
    else:
        print_warning("Skipping Instagram (no credentials). Set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD.")
    
    # Summary
    console.print()
    console.print("[bold cyan]═══════════════════════════════[/bold cyan]")
    
    checked_count = sum(1 for r in results.values() if r['checked'])
    
    if checked_count == 0:
        print_warning("No platforms checked. Please set credentials via environment variables.")
        console.print()
        console.print("  [dim]# Telegram[/dim]")
        console.print("  export TELEGRAM_API_ID=12345678")
        console.print("  export TELEGRAM_API_HASH=abc123def456")
        console.print()
        console.print("  [dim]# Instagram[/dim]")
        console.print("  export INSTAGRAM_USERNAME=myuser")
        console.print("  export INSTAGRAM_PASSWORD=mypass")
    else:
        print_success(f"Checked {checked_count} platform(s)")
        
        # Show next steps
        has_new = any(r['has_new'] for r in results.values() if r['checked'])
        if has_new:
            console.print()
            print_info("To extract new content:")
            if results['telegram']['has_new']:
                console.print("  [cyan]postparse extract telegram[/cyan]")
            if results['instagram']['has_new']:
                console.print("  [cyan]postparse extract instagram[/cyan]")
    
    console.print()

