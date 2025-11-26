"""
Classify commands for PostParse CLI.

This module provides commands for classifying content using LLM models.

Commands:
- text: Ad-hoc classification of free-form text (does NOT save to database)
- db: Classify database content and SAVE results with full tracking

Example:
    $ postparse classify text "Mix flour and water..." --classifier recipe
    $ postparse classify text "Check out FastAPI!" --classifier multiclass --classes '{"recipe": "Cooking", "tech": "Technology"}'
    $ postparse classify db --source posts --classifier recipe --limit 100
    $ postparse classify db --classifier multiclass --classes '{"recipe": "Cooking", "tech": "Technology"}'
"""

import sys
import json
from pathlib import Path
from typing import Optional, Dict, Any

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
    print_panel,
    create_progress,
    truncate_text,
)


@click.group()
def classify():
    """🤖 Classify content using LLM classifiers.
    
    Commands:
    - text: Classify free-form text (ad-hoc, doesn't save)
    - db: Classify database content and save results
    
    Classifiers:
    - recipe: Binary classification (recipe vs non-recipe)
    - multiclass: Custom categories (requires --classes)
    """
    pass


def _parse_classes_arg(classes_arg: Optional[str]) -> Optional[Dict[str, str]]:
    """
    Parse the --classes argument.

    Supports JSON string or file path prefixed with @.

    Args:
        classes_arg: JSON string or @filepath

    Returns:
        Dictionary of classes or None

    Raises:
        click.ClickException: If parsing fails
    """
    if not classes_arg:
        return None

    # If starts with @, read from file
    if classes_arg.startswith('@'):
        file_path = Path(classes_arg[1:])
        if not file_path.exists():
            raise click.ClickException(f"Classes file not found: {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                classes = json.load(f)
        except json.JSONDecodeError as e:
            raise click.ClickException(f"Invalid JSON in classes file: {e}")
    else:
        # Parse as JSON string
        try:
            classes = json.loads(classes_arg)
        except json.JSONDecodeError as e:
            raise click.ClickException(f"Invalid JSON in --classes: {e}")

    if not isinstance(classes, dict):
        raise click.ClickException("Classes must be a JSON object (dict)")

    if len(classes) < 2:
        raise click.ClickException("At least 2 classes are required")

    return classes


def _validate_provider(provider: str, config) -> bool:
    """Validate that a provider exists in config."""
    llm_providers = config.get_section('llm').get('providers', [])
    
    if not llm_providers:
        print_error("No LLM providers configured in config file")
        return False
    
    for p in llm_providers:
        if p.get('name', '').lower() == provider.lower():
            return True
    
    print_error(f"Provider '{provider}' not found in config")
    return False


@classify.command()
@click.argument('content', required=False)
@click.option(
    '--classifier',
    type=click.Choice(['recipe', 'multiclass']),
    default='recipe',
    help='Classifier type (default: recipe)',
)
@click.option(
    '--classes',
    'classes_arg',
    help='For multiclass: class definitions as JSON or @filepath',
)
@click.option(
    '--provider',
    help='LLM provider to use (default: from config)',
)
@click.option(
    '--output',
    type=click.Choice(['text', 'json']),
    default='text',
    help='Output format (default: text)',
)
@click.pass_context
def text(ctx, content, classifier, classes_arg, provider, output):
    """
    Classify free-form text (ad-hoc, doesn't save to database).
    
    Use --classifier to choose between recipe detection or custom categories.
    
    Examples:
        # Recipe classification
        postparse classify text "Mix flour and water to make dough"
        
        # Multi-class classification
        postparse classify text "Check out FastAPI!" \\
          --classifier multiclass \\
          --classes '{"recipe": "Cooking", "tech": "Technology"}'
        
        # Pipe from stdin
        echo "Recipe text" | postparse classify text -
        
        # JSON output
        postparse classify text "Some text" --output json
    
    Note:
        Results are NOT saved to database. Use 'classify db' for persistent
        classification of database content.
    """
    console = get_console()
    
    try:
        # Handle stdin input
        if content == '-' or content is None:
            if sys.stdin.isatty() and content is None:
                print_error("No text provided. Use: postparse classify text TEXT or pipe to stdin")
                raise click.Abort()
            content = sys.stdin.read().strip()
            if not content:
                print_error("No text provided from stdin")
                raise click.Abort()
        
        # Validate multiclass requires classes
        if classifier == 'multiclass' and not classes_arg:
            print_error("Multiclass classifier requires --classes option")
            raise click.Abort()
        
        # Load config
        config_path = ctx.obj.get('config')
        config = load_config(config_path)
        
        # Validate provider if specified
        if provider and not _validate_provider(provider, config):
            raise click.Abort()
        
        # Parse classes for multiclass
        classes = _parse_classes_arg(classes_arg) if classes_arg else None
        
        # Initialize classifier
        if classifier == 'recipe':
            print_info("Initializing recipe classifier...")
            from backend.postparse.services.analysis.classifiers.llm import (
                RecipeLLMClassifier
            )
            clf = RecipeLLMClassifier(
                provider_name=provider,
                config_path=config_path,
            )
        else:  # multiclass
            print_info("Initializing multiclass classifier...")
            from backend.postparse.services.analysis.classifiers.multi_class import (
                MultiClassLLMClassifier
            )
            clf = MultiClassLLMClassifier(
                classes=classes,
                provider_name=provider,
                config_path=config_path,
            )
        
        # Classify
        print_info("Classifying text...")
        result = clf.predict(content)
        
        # Output result
        if output == 'json':
            output_data = {
                'label': result.label,
                'confidence': result.confidence,
                'details': result.details,
            }
            if classifier == 'multiclass' and result.details:
                output_data['reasoning'] = result.details.get('reasoning')
            console.print_json(json.dumps(output_data))
        else:
            # Display in panel
            label = result.label
            confidence = result.confidence
            
            style = "green" if label.lower() == 'recipe' else "cyan"
            
            content_str = f"[bold]Label:[/bold] {label}\n"
            content_str += f"[bold]Confidence:[/bold] {confidence:.2%}"
            
            # Show reasoning for multiclass
            if classifier == 'multiclass' and result.details:
                reasoning = result.details.get('reasoning', '')
                if reasoning:
                    content_str += f"\n[bold]Reasoning:[/bold] {reasoning}"
                available = result.details.get('available_classes', [])
                if available:
                    content_str += f"\n[bold]Classes:[/bold] {', '.join(available)}"
            
            # Show details for recipe
            if classifier == 'recipe' and result.details:
                content_str += "\n[bold]Details:[/bold]"
                for key, value in result.details.items():
                    if value is not None:
                        content_str += f"\n  • {key}: {value}"
            
            print_panel(content_str, title="Classification Result", style=style)
        
    except click.Abort:
        raise
    except click.ClickException:
        raise
    except Exception as e:
        print_error(f"Classification failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()


@classify.command()
@click.option(
    '--source',
    type=click.Choice(['all', 'instagram', 'telegram']),
    default='all',
    help='Database source to classify (default: all)',
)
@click.option(
    '--classifier',
    type=click.Choice(['recipe', 'multiclass']),
    default='recipe',
    help='Classifier type (default: recipe)',
)
@click.option(
    '--classes',
    'classes_arg',
    help='For multiclass: class definitions as JSON or @filepath',
)
@click.option(
    '--limit',
    type=int,
    help='Number of NEW items to classify per source (skips already-classified, continues until limit reached)',
)
@click.option(
    '--filter-hashtag',
    multiple=True,
    help='Filter by hashtag before classifying (can specify multiple)',
)
@click.option(
    '--provider',
    help='LLM provider to use (default: from config)',
)
@click.option(
    '--force',
    is_flag=True,
    default=False,
    help='Force reclassification even if already classified (adds new entry)',
)
@click.option(
    '--replace',
    is_flag=True,
    default=False,
    help='Used with --force: replace existing entry instead of adding new one',
)
@click.pass_context
def db(ctx, source, classifier, classes_arg, limit, filter_hashtag, provider,
       force, replace):
    """
    Classify database content and save results.
    
    Classifies Instagram posts and/or Telegram messages from the database
    and saves results with full tracking (LLM metadata, reasoning, confidence).
    
    Limit behavior:
        - --limit N classifies exactly N NEW items per source
        - Already-classified items are SKIPPED (not counted toward limit)
        - Pagination continues until N items are classified or database exhausted
        - Items are processed NEWEST first (ORDER BY created_at DESC)
        - Example: --limit 10 twice in a row = items 1-10, then items 11-20
    
    Examples:
        # Classify 100 new items from each source
        postparse classify db --limit 100
        
        # Classify 100 new Instagram posts only
        postparse classify db --source instagram --limit 100
        
        # Classify only Telegram messages
        postparse classify db --source telegram --provider openai
        
        # Multi-class classification
        postparse classify db --classifier multiclass \\
          --classes '{"recipe": "Cooking", "tech": "Technology", "other": "Other"}'
        
        # Filter by hashtag first
        postparse classify db --filter-hashtag recipe --limit 50
        
        # Force reclassification (adds new entry with new timestamp)
        postparse classify db --force --limit 50
        
        # Force reclassification and replace existing entry
        postparse classify db --force --replace --limit 50
    
    Note:
        - Results are saved to content_analysis table
        - Items already classified by same classifier+model are skipped (unless --force)
        - --force adds a new classification entry (keeps history)
        - --force --replace overwrites the existing entry
        - LLM metadata (provider, model, temperature) is tracked
    """
    console = get_console()
    
    try:
        # Validate --replace requires --force
        if replace and not force:
            print_error("--replace requires --force flag")
            raise click.Abort()
        
        # Validate multiclass requires classes
        if classifier == 'multiclass' and not classes_arg:
            print_error("Multiclass classifier requires --classes option")
            raise click.Abort()
        
        # Load config
        config_path = ctx.obj.get('config')
        config = load_config(config_path)
        
        # Get database
        database = get_database(config)
        
        # Validate provider if specified
        if provider and not _validate_provider(provider, config):
            raise click.Abort()
        
        # Parse classes for multiclass
        classes = _parse_classes_arg(classes_arg) if classes_arg else None
        
        # Initialize classifier
        if classifier == 'recipe':
            print_info("Initializing recipe classifier...")
            from backend.postparse.services.analysis.classifiers.llm import (
                RecipeLLMClassifier
            )
            clf = RecipeLLMClassifier(
                provider_name=provider,
                config_path=config_path,
            )
            classifier_name = 'recipe_llm'
        else:  # multiclass
            print_info("Initializing multiclass classifier...")
            from backend.postparse.services.analysis.classifiers.multi_class import (
                MultiClassLLMClassifier
            )
            clf = MultiClassLLMClassifier(
                classes=classes,
                provider_name=provider,
                config_path=config_path,
            )
            classifier_name = 'multiclass_llm'
        
        # Get the model name from classifier for duplicate checking
        llm_metadata = clf.get_llm_metadata()
        llm_model = llm_metadata.get('model')
        
        # Determine which sources to classify
        sources_to_classify = ['instagram', 'telegram'] if source == 'all' else [source]
        
        # Classify items
        all_results = []
        # Per-source stats: {source: {total, skipped, replaced, empty, confidence_sum, labels}}
        source_stats: Dict[str, Dict[str, Any]] = {}
        
        for current_source in sources_to_classify:
            # Query database
            print_info(f"Querying {current_source} from database...")
            
            content_source_name = current_source
            target_count = limit or 1000  # How many to classify
            batch_size = 50  # Fetch items in batches
            
            # Initialize per-source stats
            source_stats[current_source] = {
                'total': 0,
                'skipped': 0,
                'replaced': 0,
                'empty': 0,
                'confidence_sum': 0.0,
                'labels': {},
            }
            current_stats = source_stats[current_source]
            
            # Track per-source stats for progress display
            source_classified = 0
            source_skipped = 0
            source_empty = 0
            cursor = None
            exhausted = False  # True when no more items in database
            
            print_info(f"Classifying up to {target_count} {current_source} items...")
            
            with create_progress() as progress:
                task = progress.add_task(
                    f"[cyan]{current_source}[/cyan]",
                    total=target_count
                )
                
                def update_progress_desc():
                    """Update progress bar description with current stats."""
                    desc = f"[cyan]{current_source}[/cyan]"
                    if source_classified > 0:
                        desc += f" [green]✓{source_classified}[/green]"
                    if source_skipped > 0:
                        desc += f" [dim]⊘{source_skipped} already done[/dim]"
                    if source_empty > 0:
                        desc += f" [dim]○{source_empty} empty[/dim]"
                    progress.update(task, description=desc)
                
                while source_classified < target_count and not exhausted:
                    # Fetch next batch of items
                    if current_source == 'instagram':
                        if filter_hashtag:
                            items, cursor = database.search_instagram_posts(
                                hashtags=list(filter_hashtag),
                                date_range=None,
                                limit=batch_size,
                                cursor=cursor
                            )
                        else:
                            items, cursor = database.search_instagram_posts(
                                limit=batch_size,
                                cursor=cursor
                            )
                    else:  # telegram
                        if filter_hashtag:
                            items, cursor = database.search_telegram_messages(
                                hashtags=list(filter_hashtag),
                                content_type=None,
                                date_range=None,
                                limit=batch_size,
                                cursor=cursor
                            )
                        else:
                            items, cursor = database.search_telegram_messages(
                                limit=batch_size,
                                cursor=cursor
                            )
                    
                    if not items:
                        exhausted = True
                        break
                    
                    # No more pages after this
                    if cursor is None:
                        exhausted = True
                    
                    for item in items:
                        # Stop if we've reached the target
                        if source_classified >= target_count:
                            break
                        
                        # Extract text
                        if current_source == 'instagram':
                            item_text = item.get('caption', '')
                        else:  # telegram
                            item_text = item.get('content', '')
                        
                        if not item_text:
                            source_empty += 1
                            current_stats['empty'] += 1
                            update_progress_desc()
                            continue
                        
                        # Classify
                        try:
                            item_id = item.get('id')
                            
                            # Check if already classified by this classifier+model
                            existing_id = None
                            if item_id:
                                has_existing = database.has_classification(
                                    item_id, content_source_name, classifier_name, llm_model
                                )
                                
                                if has_existing:
                                    if not force:
                                        # Skip - don't count toward limit
                                        current_stats['skipped'] += 1
                                        source_skipped += 1
                                        update_progress_desc()
                                        continue
                                    elif replace:
                                        # Get existing ID for replacement
                                        existing_id = database.get_classification_id(
                                            item_id, content_source_name,
                                            classifier_name, llm_model
                                        )
                            
                            result = clf.predict(item_text)
                            
                            label = result.label
                            confidence = result.confidence
                            
                            # Save to database with LLM metadata
                            if item_id:
                                # Extract reasoning from details if present
                                reasoning = None
                                details = result.details.copy() if result.details else {}
                                if details and 'reasoning' in details:
                                    reasoning = details.pop('reasoning')
                                
                                if existing_id and replace:
                                    # Update existing record
                                    database.update_classification(
                                        analysis_id=existing_id,
                                        label=label,
                                        confidence=confidence,
                                        reasoning=reasoning,
                                        llm_metadata=clf.get_llm_metadata(),
                                        details=details if details else None
                                    )
                                    current_stats['replaced'] += 1
                                else:
                                    # Insert new record
                                    database.save_classification_result(
                                        content_id=item_id,
                                        content_source=content_source_name,
                                        classifier_name=classifier_name,
                                        label=label,
                                        confidence=confidence,
                                        details=details if details else None,
                                        classification_type='single',
                                        reasoning=reasoning,
                                        llm_metadata=clf.get_llm_metadata()
                                    )
                            
                            current_stats['total'] += 1
                            current_stats['labels'][label] = current_stats['labels'].get(label, 0) + 1
                            current_stats['confidence_sum'] += confidence
                            source_classified += 1
                            
                            all_results.append({
                                'id': item_id or '',
                                'source': current_source,
                                'content_preview': truncate_text(item_text, 40),
                                'label': label,
                                'confidence': f"{confidence:.2%}",
                            })
                            
                            # Update progress bar (tracks classified count)
                            progress.update(task, completed=source_classified)
                            update_progress_desc()
                            
                        except Exception as e:
                            if ctx.obj.get('verbose'):
                                print_error(f"Error classifying item {item.get('id')}: {e}")
                
                # Final update - set to actual classified count
                progress.update(task, completed=source_classified, total=source_classified)
                update_progress_desc()
            
            if source_classified == 0 and source_skipped == 0:
                print_info(f"No {current_source} found to classify")
        
        # Display results
        console.print()
        print_success("Classification completed!")
        
        # Results table
        if all_results:
            title = f"Classification Results ({source})"
            table = Table(title=title, show_header=True)
            table.add_column("ID", style="cyan")
            if source == 'all':
                table.add_column("Source", style="dim")
            table.add_column("Content Preview")
            table.add_column("Label", style="green")
            table.add_column("Confidence", justify="right")
            
            for result in all_results[:20]:  # Show first 20
                if source == 'all':
                    table.add_row(
                        str(result['id']),
                        result['source'],
                        result['content_preview'],
                        result['label'],
                        result['confidence'],
                    )
                else:
                    table.add_row(
                        str(result['id']),
                        result['content_preview'],
                        result['label'],
                        result['confidence'],
                    )
            
            console.print(table)
            
            if len(all_results) > 20:
                print_info(f"Showing first 20 of {len(all_results)} results")
        
        # Summary stats per source
        console.print()
        
        for src_name, src_stats in source_stats.items():
            src_total = src_stats['total']
            src_skipped = src_stats['skipped']
            src_replaced = src_stats['replaced']
            src_empty = src_stats['empty']
            src_confidence = src_stats['confidence_sum']
            src_labels = src_stats['labels']
            
            avg_confidence = src_confidence / src_total if src_total > 0 else 0.0
            
            # Source icon
            icon = "📸" if src_name == "instagram" else "📨"
            summary = Table(title=f"{icon} {src_name.capitalize()} Summary", show_header=True)
            summary.add_column("Metric", style="cyan")
            summary.add_column("Value", style="green", justify="right")
            
            summary.add_row("Classified", str(src_total))
            summary.add_row("Skipped (already done)", str(src_skipped))
            if src_empty > 0:
                summary.add_row("Empty (no text)", str(src_empty))
            if src_replaced > 0:
                summary.add_row("Replaced", str(src_replaced))
                summary.add_row("New entries", str(src_total - src_replaced))
            if src_total > 0:
                summary.add_row("Avg confidence", f"{avg_confidence:.2%}")
            
            # Show label distribution for this source
            if src_labels:
                summary.add_row("", "")  # Empty row separator
                summary.add_row("[bold]Labels[/bold]", "")
                for label, count in sorted(src_labels.items()):
                    summary.add_row(f"  {label}", str(count))
            
            console.print(summary)
            console.print()
        
        # Grand total if multiple sources
        if len(source_stats) > 1:
            grand_total = sum(s['total'] for s in source_stats.values())
            grand_skipped = sum(s['skipped'] for s in source_stats.values())
            grand_confidence = sum(s['confidence_sum'] for s in source_stats.values())
            avg_total_confidence = grand_confidence / grand_total if grand_total > 0 else 0.0
            
            total_table = Table(title="📊 Grand Total", show_header=True)
            total_table.add_column("Metric", style="cyan")
            total_table.add_column("Value", style="green", justify="right")
            total_table.add_row("Total classified", str(grand_total))
            total_table.add_row("Total skipped", str(grand_skipped))
            if grand_total > 0:
                total_table.add_row("Avg confidence", f"{avg_total_confidence:.2%}")
            console.print(total_table)
        
    except click.Abort:
        raise
    except click.ClickException:
        raise
    except Exception as e:
        print_error(f"Database classification failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()
