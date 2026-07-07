"""Enrich commands for PostParse CLI.

This module provides commands for enriching stored content with
additional derived data.

Commands:
- urls:   Extract URLs from content into content_expanded column
- scrape: Extract URLs, fetch their content, and save scraped text
          to content_expanded column

Example:
    $ postparse enrich urls
    $ postparse enrich urls --source telegram --limit 500
    $ postparse enrich scrape
    $ postparse enrich scrape --source telegram --limit 100
"""

import re
from typing import Any, Dict, List, Optional

import rich_click as click
from rich.table import Table

from backend.postparse.cli.utils import (
    get_console,
    load_config,
    get_database,
    print_success,
    print_error,
    print_info,
    create_progress,
)

# Regex to extract URLs from text
_URL_PATTERN = re.compile(
    r'https?://[^\s\)\]\}\"\'<>]+',
    re.IGNORECASE,
)


def _is_instagram_url(url: str) -> bool:
    """Return True if url points to Instagram.

    Args:
        url: URL string to test.

    Returns:
        True if the domain is instagram.com or instagr.am.
    """
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower()
        return domain in ("instagram.com", "www.instagram.com", "instagr.am")
    except Exception:
        return False


def extract_urls(text: str) -> List[str]:
    """Extract all URLs from a text string.

    Args:
        text: Input text to search for URLs.

    Returns:
        Deduplicated list of URLs found, preserving order.

    Example:
        >>> extract_urls("Check https://youtube.com/watch?v=abc and https://x.com/user/status/1")
        ['https://youtube.com/watch?v=abc', 'https://x.com/user/status/1']
    """
    seen = set()
    urls = []
    for url in _URL_PATTERN.findall(text or ''):
        url = url.rstrip('.,;:!?)')
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _extract_and_cache_urls(database: Any, item_id: int, source: str, content: str) -> List[str]:
    """Extract URLs from content and cache them in content_expanded.

    Args:
        database: SocialMediaDatabase instance.
        item_id: Row ID of the content item.
        source: 'telegram' or 'instagram'.
        content: Raw text content to scan for URLs.

    Returns:
        List of extracted URLs (empty list if none found).

    Example:
        >>> urls = _extract_and_cache_urls(db, 42, 'telegram', 'Watch https://youtu.be/abc')
        >>> # ['https://youtu.be/abc'] — also saved to content_expanded
    """
    urls = extract_urls(content or '')
    if urls:
        database.save_content_expanded(
            item_id=item_id,
            source=source,
            content_expanded='\n'.join(urls),
        )
    return urls


def _fetch_content_items(database: Any, source: str, limit: Optional[int]) -> List[Dict[str, Any]]:
    """Fetch content items from the database for a given source.

    Args:
        database: SocialMediaDatabase instance.
        source: 'telegram' or 'instagram'.
        limit: Max rows to return.

    Returns:
        List of dicts with 'id', 'content', and 'content_expanded' keys.
    """
    with database as db:
        if source == 'telegram':
            db._cursor.execute(
                """
                SELECT id, content, content_expanded FROM telegram_messages
                WHERE content IS NOT NULL AND content != ''
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit or 100_000,),
            )
        else:
            db._cursor.execute(
                """
                SELECT id, caption, content_expanded FROM instagram_posts
                WHERE caption IS NOT NULL AND caption != ''
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit or 100_000,),
            )
        return [
            {'id': row[0], 'content': row[1], 'content_expanded': row[2] or ''}
            for row in db._cursor.fetchall()
        ]


@click.group(invoke_without_command=True)
@click.pass_context
def enrich(ctx):
    """🔗 Enrich stored content with derived data.

    Commands:
    - urls:   Extract URLs from content into content_expanded column
    - scrape: Extract URLs, fetch content, save to content_expanded
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(urls)


@enrich.command()
@click.option(
    '--source',
    type=click.Choice(['all', 'telegram', 'instagram']),
    default='all',
    help='Source to enrich (default: all)',
)
@click.option(
    '--limit',
    type=int,
    default=None,
    help='Max items to process per source (default: all pending)',
)
@click.option(
    '--force',
    is_flag=True,
    default=False,
    help='Re-extract URLs even if content_expanded is already set',
)
@click.pass_context
def urls(ctx, source: str, limit: Optional[int], force: bool):
    """Extract URLs from content and store in content_expanded.

    Scans telegram messages and/or instagram posts for URLs in their
    text content, then stores the extracted URLs (newline-separated) in
    the content_expanded column. Items with no URLs are skipped.

    Already-processed items are skipped unless --force is used.

    Examples:
        postparse enrich urls

        postparse enrich urls --source telegram --limit 500

        postparse enrich urls --force
    """
    console = get_console()

    try:
        config_path = ctx.obj.get('config')
        config = load_config(config_path)
        database = get_database(config)

        sources = ['telegram', 'instagram'] if source == 'all' else [source]

        grand_total = 0
        grand_no_urls = 0

        for current_source in sources:
            print_info(f"Processing {current_source}...")
            items = _fetch_content_items(database, current_source, limit)

            if not items:
                print_info(f"No {current_source} items to process")
                continue

            processed = 0
            skipped = 0
            no_urls = 0

            with create_progress() as progress:
                task = progress.add_task(f"[cyan]{current_source}[/cyan]", total=len(items))

                for item in items:
                    if not force and item['content_expanded']:
                        skipped += 1
                        progress.advance(task)
                        continue

                    extracted = _extract_and_cache_urls(database, item['id'], current_source, item['content'])
                    if extracted:
                        processed += 1
                    else:
                        no_urls += 1
                    progress.advance(task)

            grand_total += processed
            grand_no_urls += no_urls

            icon = "📨" if current_source == "telegram" else "📸"
            summary = Table(title=f"{icon} {current_source.capitalize()} URL Extraction", show_header=True)
            summary.add_column("Metric", style="cyan")
            summary.add_column("Count", style="green", justify="right")
            summary.add_row("URLs extracted", str(processed))
            summary.add_row("Already processed (skipped)", str(skipped))
            summary.add_row("No URLs (skipped)", str(no_urls))
            console.print(summary)
            console.print()

        console.print()
        print_success(f"Done. {grand_total} items enriched with URLs, {grand_no_urls} had no URLs.")

    except click.Abort:
        raise
    except Exception as e:
        print_error(f"Enrichment failed: {e}")
        if ctx.obj.get('verbose'):
            get_console().print_exception()
        raise click.Abort()


@enrich.command()
@click.option(
    '--source',
    type=click.Choice(['all', 'telegram', 'instagram']),
    default='all',
    help='Source to scrape (default: all)',
)
@click.option(
    '--limit',
    type=int,
    default=None,
    help='Max items to process per source (default: all pending)',
)
@click.option(
    '--force',
    is_flag=True,
    default=False,
    help='Re-scrape even if content_expanded is already set',
)
@click.option(
    '--timeout',
    type=float,
    default=15.0,
    help='HTTP request timeout in seconds (default: 15)',
)
@click.pass_context
def scrape(ctx, source: str, limit: Optional[int], force: bool, timeout: float):
    """Extract URLs from content, fetch their pages, save to content_expanded.

    For each message/post:
    1. Extracts URLs from the text
    2. Fetches each URL (YouTube via oEmbed, others via httpx)
    3. Combines all scraped text and saves to content_expanded

    Items that already have content_expanded set are skipped unless
    --force is used.

    Examples:
        postparse enrich scrape

        postparse enrich scrape --source telegram --limit 100

        postparse enrich scrape --timeout 30

        postparse enrich scrape --force
    """
    console = get_console()

    try:
        from backend.postparse.services.enrichment.youtube import (
            YouTubeEnricher, is_youtube_url,
        )
        from backend.postparse.services.enrichment.x_twitter import (
            XEnricher, is_x_url,
        )
        from backend.postparse.services.enrichment.link_scraper import LinkScraper

        config_path = ctx.obj.get('config')
        config = load_config(config_path)
        database = get_database(config)

        yt_enricher = YouTubeEnricher(timeout=timeout)
        x_enricher = XEnricher(timeout=timeout)
        link_scraper = LinkScraper(timeout=timeout)

        sources = ['telegram', 'instagram'] if source == 'all' else [source]

        grand_scraped = 0
        grand_skipped = 0
        grand_failed = 0
        grand_no_urls = 0

        for current_source in sources:
            print_info(f"Processing {current_source}...")
            items = _fetch_content_items(database, current_source, limit)

            if not items:
                print_info(f"No {current_source} items to process")
                continue

            scraped = 0
            skipped = 0
            failed = 0
            no_urls = 0

            with create_progress() as progress:
                task = progress.add_task(
                    f"[cyan]{current_source}[/cyan]",
                    total=len(items),
                )

                for item in items:
                    item_id = item['id']

                    if not force and item['content_expanded']:
                        skipped += 1
                        progress.advance(task)
                        continue

                    item_urls = extract_urls(item['content'] or '')
                    if not item_urls:
                        no_urls += 1
                        progress.advance(task)
                        continue

                    scraped_parts: List[str] = []
                    item_failed = False

                    for url in item_urls:
                        if current_source == "telegram" and _is_instagram_url(url):
                            continue
                        try:
                            if is_youtube_url(url):
                                enricher = yt_enricher
                            elif is_x_url(url):
                                enricher = x_enricher
                            else:
                                enricher = link_scraper
                            result = enricher.enrich("", source_url=url)
                            if result.generated_text:
                                scraped_parts.append(result.generated_text)
                        except Exception as e:
                            item_failed = True
                            if ctx.obj.get('verbose'):
                                print_error(f"Failed {url}: {e}")

                    if scraped_parts:
                        database.save_content_expanded(
                            item_id=item_id,
                            source=current_source,
                            content_expanded="\n\n".join(scraped_parts),
                        )
                        scraped += 1
                    elif item_failed:
                        failed += 1
                    else:
                        no_urls += 1

                    progress.advance(task)

            grand_scraped += scraped
            grand_skipped += skipped
            grand_failed += failed
            grand_no_urls += no_urls

            icon = "📨" if current_source == "telegram" else "📸"
            summary = Table(
                title=f"{icon} {current_source.capitalize()} Scrape Summary",
                show_header=True,
            )
            summary.add_column("Metric", style="cyan")
            summary.add_column("Count", style="green", justify="right")
            summary.add_row("Scraped", str(scraped))
            summary.add_row("Skipped (already done)", str(skipped))
            summary.add_row("No URLs", str(no_urls))
            if failed:
                summary.add_row("Failed", str(failed))
            console.print(summary)
            console.print()

        console.print()
        msg = f"Done. {grand_scraped} items scraped"
        if grand_skipped:
            msg += f", {grand_skipped} skipped"
        if grand_failed:
            msg += f", {grand_failed} failed"
        print_success(msg)

    except click.Abort:
        raise
    except Exception as e:
        print_error(f"Scrape failed: {e}")
        if ctx.obj.get('verbose'):
            get_console().print_exception()
        raise click.Abort()
