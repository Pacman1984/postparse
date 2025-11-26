"""
Classify commands for PostParse CLI.

This module provides commands for classifying content using ML/LLM models.

Commands include:
- Recipe classification (single/batch)
- Multi-class classification with custom categories

Example:
    $ postparse classify single "Mix flour and water..."
    $ postparse classify batch --source posts --limit 100
    $ postparse classify multi "Check out FastAPI!" --classes '{"recipe": "Cooking", "tech": "Technology"}'
    $ postparse classify multi-batch "Text 1" "Text 2" --classes @classes.json
"""

import sys
import json
from pathlib import Path
from typing import Optional, Dict

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
    """🤖 Classify content as recipe/not recipe using ML or LLM."""
    pass


@classify.command()
@click.argument('text', required=False)
@click.option(
    '--provider',
    help='LLM provider to use (default: from config)',
)
@click.option(
    '--detailed',
    is_flag=True,
    help='Show detailed classification information (cuisine type, difficulty, etc.)',
)
@click.option(
    '--output',
    type=click.Choice(['text', 'json']),
    default='text',
    help='Output format (default: text)',
)
@click.pass_context
def single(ctx, text, provider, detailed, output):
    """
    Classify a single text as recipe or not.
    
    The TEXT argument can be provided directly or read from stdin using '-'.
    
    Examples:
        postparse classify single "Mix flour and water..."
        
        echo "Recipe text" | postparse classify single -
        
        postparse classify single --detailed --provider openai "Mix flour..."
    
    Note:
        Uses RecipeLLMClassifier for classification, which requires an LLM provider
        to be configured. Use --detailed flag to show additional information like
        cuisine type, difficulty, and meal type in the output.
    """
    console = get_console()
    
    try:
        # Handle stdin input
        if text == '-' or text is None:
            if sys.stdin.isatty() and text is None:
                print_error("No text provided. Use: postparse classify single TEXT or pipe to stdin")
                raise click.Abort()
            text = sys.stdin.read().strip()
            if not text:
                print_error("No text provided from stdin")
                raise click.Abort()
        
        # Load config
        config_path = ctx.obj.get('config')
        config = load_config(config_path)
        
        # Initialize classifier (always use RecipeLLMClassifier)
        print_info("Initializing LLM classifier...")
        
        from backend.postparse.services.analysis.classifiers.llm import (
            RecipeLLMClassifier
        )
        
        # Determine provider if specified
        if provider:
            llm_providers = config.get_section('llm').get('providers', [])
            
            if not llm_providers:
                print_error("No LLM providers configured in config file")
                raise click.Abort()
            
            provider_found = False
            for p in llm_providers:
                if p.get('name', '').lower() == provider.lower():
                    provider_found = True
                    break
            if not provider_found:
                print_error(f"Provider '{provider}' not found in config")
                raise click.Abort()
        
        classifier = RecipeLLMClassifier(
            provider_name=provider,
            config_path=config_path,
        )
        
        # Classify
        print_info("Classifying text...")
        result = classifier.predict(text)
        
        # Output result
        if output == 'json':
            console.print_json(json.dumps(result.model_dump()))
        else:
            # Display in panel
            label = result.label
            confidence = result.confidence
            
            style = "green" if label.lower() == 'recipe' else "yellow"
            
            content = f"[bold]Label:[/bold] {label}\n"
            content += f"[bold]Confidence:[/bold] {confidence:.2%}\n"
            
            if detailed and result.details:
                content += f"\n[bold]Details:[/bold]\n"
                for key, value in result.details.items():
                    content += f"  • {key}: {value}\n"
            
            print_panel(content, title="Classification Result", style=style)
        
    except click.Abort:
        pass
    except Exception as e:
        print_error(f"Classification failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()


@classify.command()
@click.option(
    '--source',
    type=click.Choice(['posts', 'messages']),
    default='posts',
    help='Source to classify (default: posts)',
)
@click.option(
    '--limit',
    type=int,
    help='Maximum items to classify',
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
    '--detailed',
    is_flag=True,
    help='Show detailed classification information in output',
)
@click.pass_context
def batch(ctx, source, limit, filter_hashtag, provider, detailed):
    """
    Classify multiple items in batch.
    
    This command classifies all posts or messages from the database,
    optionally filtered by hashtags.
    
    Examples:
        postparse classify batch --source posts --limit 100
        
        postparse classify batch --filter-hashtag recipe --detailed
        
        postparse classify batch --source messages --provider openai
    
    Note:
        Uses RecipeLLMClassifier for classification, which requires an LLM provider
        to be configured. Batch classification can take time depending on the number
        of items and LLM provider speed. Progress will be displayed.
    """
    console = get_console()
    
    try:
        # Load config
        config_path = ctx.obj.get('config')
        config = load_config(config_path)
        
        # Get database
        db = get_database(config)
        
        # Initialize classifier (always use RecipeLLMClassifier)
        print_info("Initializing LLM classifier...")
        
        from backend.postparse.services.analysis.classifiers.llm import (
            RecipeLLMClassifier
        )
        
        # Determine provider if specified
        if provider:
            llm_providers = config.get_section('llm').get('providers', [])
            
            if not llm_providers:
                print_error("No LLM providers configured in config file")
                raise click.Abort()
            
            provider_found = False
            for p in llm_providers:
                if p.get('name', '').lower() == provider.lower():
                    provider_found = True
                    break
            if not provider_found:
                print_error(f"Provider '{provider}' not found in config")
                raise click.Abort()
        
        classifier = RecipeLLMClassifier(
            provider_name=provider,
            config_path=config_path,
        )
        
        # Query database
        print_info(f"Querying {source} from database...")
        
        next_cursor = None
        if source == 'posts':
            if filter_hashtag:
                items, next_cursor = db.search_instagram_posts(
                    hashtags=list(filter_hashtag),
                    date_range=None,
                    limit=limit or 1000
                )
            else:
                items = db.get_instagram_posts(limit=limit or 1000)
        else:  # messages
            if filter_hashtag:
                items, next_cursor = db.search_telegram_messages(
                    hashtags=list(filter_hashtag),
                    content_type=None,
                    date_range=None,
                    limit=limit or 1000
                )
            else:
                items = db.get_telegram_messages(limit=limit or 1000)
        
        if not items:
            print_info(f"No {source} found to classify")
            return
        
        print_info(f"Found {len(items)} {source} to classify")
        
        # Classify items
        results = []
        stats = {
            'total': 0,
            'recipe': 0,
            'not_recipe': 0,
            'confidence_sum': 0.0,
        }
        
        with create_progress() as progress:
            task = progress.add_task(
                f"[cyan]Classifying {source}...",
                total=len(items)
            )
            
            for item in items:
                # Extract text
                if source == 'posts':
                    text = item.get('caption', '')
                else:
                    text = item.get('text', '') or item.get('caption', '')
                
                if not text:
                    progress.update(task, advance=1)
                    continue
                
                # Classify
                try:
                    result = classifier.predict(text)
                    
                    label = result.label
                    confidence = result.confidence
                    
                    stats['total'] += 1
                    if label.lower() == 'recipe':
                        stats['recipe'] += 1
                    else:
                        stats['not_recipe'] += 1
                    stats['confidence_sum'] += confidence
                    
                    results.append({
                        'id': item.get('id', ''),
                        'content_preview': truncate_text(text, 40),
                        'label': label,
                        'confidence': f"{confidence:.2%}",
                    })
                    
                except Exception as e:
                    if ctx.obj.get('verbose'):
                        print_error(f"Error classifying item {item.get('id')}: {e}")
                
                progress.update(task, advance=1)
        
        # Display results
        console.print()
        print_success("Classification completed!")
        
        # Results table
        if results:
            table = Table(title=f"Classification Results ({source})", show_header=True)
            table.add_column("ID", style="cyan")
            table.add_column("Content Preview")
            table.add_column("Label", style="green")
            table.add_column("Confidence", justify="right")
            
            for result in results[:20]:  # Show first 20
                table.add_row(
                    str(result['id']),
                    result['content_preview'],
                    result['label'],
                    result['confidence'],
                )
            
            console.print(table)
            
            if len(results) > 20:
                print_info(f"Showing first 20 of {len(results)} results")
        
        # Summary stats
        console.print()
        avg_confidence = stats['confidence_sum'] / stats['total'] if stats['total'] > 0 else 0.0
        
        summary = Table(title="Summary", show_header=True)
        summary.add_column("Metric", style="cyan")
        summary.add_column("Value", style="green", justify="right")
        
        summary.add_row("Total classified", str(stats['total']))
        summary.add_row("Recipe", str(stats['recipe']))
        summary.add_row("Not recipe", str(stats['not_recipe']))
        summary.add_row("Avg confidence", f"{avg_confidence:.2%}")
        
        console.print(summary)
        
        # Show pagination info if there are more results
        if next_cursor:
            print_info(f"More results available. Next cursor: {next_cursor[:20]}...")
        
    except click.Abort:
        pass
    except Exception as e:
        print_error(f"Batch classification failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()


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


@classify.command()
@click.argument('text', required=False)
@click.option(
    '--classes',
    'classes_arg',
    help='Class definitions as JSON string or @filepath. Format: {"class1": "description1", ...}',
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
def multi(ctx, text, classes_arg, provider, output):
    """
    Classify text into custom categories using multi-class LLM.

    Classify a single TEXT into one of your custom categories.

    Classes can be defined via:
    - --classes JSON string: '{"recipe": "Cooking", "tech": "Technology"}'
    - --classes @file.json: Read classes from JSON file
    - Config file: Uses [classification.classes] from config.toml if --classes not provided

    Examples:
        postparse classify multi "Check out this new FastAPI library!"

        postparse classify multi "Apple announces iPhone 16" \\
          --classes '{"recipe": "Cooking", "tech_news": "Tech news", "sports": "Sports"}'

        postparse classify multi "Some text" --classes @my_classes.json

        postparse classify multi "Some text" --provider openai

        echo "Recipe text" | postparse classify multi -
    """
    console = get_console()

    try:
        # Handle stdin input
        if text == '-' or text is None:
            if sys.stdin.isatty() and text is None:
                print_error("No text provided. Use: postparse classify multi TEXT or pipe to stdin")
                raise click.Abort()
            text = sys.stdin.read().strip()
            if not text:
                print_error("No text provided from stdin")
                raise click.Abort()

        # Load config
        config_path = ctx.obj.get('config')
        config = load_config(config_path)

        # Parse classes argument
        classes = _parse_classes_arg(classes_arg)

        # Validate provider if specified
        if provider:
            llm_providers = config.get_section('llm').get('providers', [])

            if not llm_providers:
                print_error("No LLM providers configured in config file")
                raise click.Abort()

            provider_found = False
            for p in llm_providers:
                if p.get('name', '').lower() == provider.lower():
                    provider_found = True
                    break
            if not provider_found:
                print_error(f"Provider '{provider}' not found in config")
                raise click.Abort()

        # Initialize classifier
        print_info("Initializing multi-class LLM classifier...")

        from backend.postparse.services.analysis.classifiers.multi_class import (
            MultiClassLLMClassifier
        )

        classifier = MultiClassLLMClassifier(
            classes=classes,
            provider_name=provider,
            config_path=config_path,
        )

        # Classify
        print_info("Classifying text...")
        result = classifier.predict(text)

        # Output result
        if output == 'json':
            output_data = {
                'label': result.label,
                'confidence': result.confidence,
                'reasoning': result.details.get('reasoning') if result.details else None,
                'available_classes': result.details.get('available_classes', []) if result.details else [],
            }
            console.print_json(json.dumps(output_data))
        else:
            # Display in panel
            label = result.label
            confidence = result.confidence
            reasoning = result.details.get('reasoning', '') if result.details else ''
            available_classes = result.details.get('available_classes', []) if result.details else []

            content = f"[bold]Predicted Class:[/bold] {label}\n"
            content += f"[bold]Confidence:[/bold] {confidence:.2%}\n"
            if reasoning:
                content += f"[bold]Reasoning:[/bold] {reasoning}\n"
            content += f"[bold]Available Classes:[/bold] {', '.join(available_classes)}"

            print_panel(content, title="Classification Result", style="cyan")

    except click.Abort:
        pass
    except click.ClickException:
        raise
    except Exception as e:
        print_error(f"Multi-class classification failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()


@classify.command('multi-batch')
@click.argument('texts', nargs=-1, required=False)
@click.option(
    '--classes',
    'classes_arg',
    help='Class definitions as JSON string or @filepath. Format: {"class1": "description1", ...}',
)
@click.option(
    '--provider',
    help='LLM provider to use (default: from config)',
)
@click.option(
    '--output',
    type=click.Path(),
    help='Save results to JSON file',
)
@click.pass_context
def multi_batch(ctx, texts, classes_arg, provider, output):
    """
    Classify multiple texts into custom categories.

    Provide TEXTS as multiple arguments or use @file to read from a file
    (one text per line).

    Examples:
        postparse classify multi-batch "Text 1" "Text 2" "Text 3" \\
          --classes '{"recipe": "Cooking", "tech": "Tech news"}'

        postparse classify multi-batch @texts.txt \\
          --classes @classes.json \\
          --output results.json

        postparse classify multi-batch "Text 1" "Text 2" --provider openai
    """
    console = get_console()

    try:
        # Handle file input for texts
        texts_list = list(texts)
        if len(texts_list) == 1 and texts_list[0].startswith('@'):
            file_path = Path(texts_list[0][1:])
            if not file_path.exists():
                print_error(f"Texts file not found: {file_path}")
                raise click.Abort()
            with open(file_path, 'r', encoding='utf-8') as f:
                texts_list = [line.strip() for line in f if line.strip()]

        if not texts_list:
            print_error("No texts provided. Use: postparse classify multi-batch TEXT1 TEXT2 ...")
            raise click.Abort()

        # Load config
        config_path = ctx.obj.get('config')
        config = load_config(config_path)

        # Parse classes argument
        classes = _parse_classes_arg(classes_arg)

        # Validate provider if specified
        if provider:
            llm_providers = config.get_section('llm').get('providers', [])

            if not llm_providers:
                print_error("No LLM providers configured in config file")
                raise click.Abort()

            provider_found = False
            for p in llm_providers:
                if p.get('name', '').lower() == provider.lower():
                    provider_found = True
                    break
            if not provider_found:
                print_error(f"Provider '{provider}' not found in config")
                raise click.Abort()

        # Initialize classifier
        print_info("Initializing multi-class LLM classifier...")

        from backend.postparse.services.analysis.classifiers.multi_class import (
            MultiClassLLMClassifier
        )

        classifier = MultiClassLLMClassifier(
            classes=classes,
            provider_name=provider,
            config_path=config_path,
        )

        print_info(f"Classifying {len(texts_list)} texts...")

        # Classify all texts
        results = []
        stats: Dict[str, int] = {}

        with create_progress() as progress:
            task = progress.add_task(
                "[cyan]Classifying texts...",
                total=len(texts_list)
            )

            for text_item in texts_list:
                try:
                    result = classifier.predict(text_item)
                    results.append({
                        'text': text_item,
                        'label': result.label,
                        'confidence': result.confidence,
                        'reasoning': result.details.get('reasoning') if result.details else None,
                    })

                    # Track stats
                    stats[result.label] = stats.get(result.label, 0) + 1

                except Exception as e:
                    if ctx.obj.get('verbose'):
                        print_error(f"Error classifying: {e}")
                    results.append({
                        'text': text_item,
                        'label': 'ERROR',
                        'confidence': 0.0,
                        'reasoning': str(e),
                    })
                    stats['ERROR'] = stats.get('ERROR', 0) + 1

                progress.update(task, advance=1)

        # Save to file if requested
        if output:
            with open(output, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2)
            print_success(f"Results saved to {output}")

        # Display results table
        console.print()

        table = Table(title="Classification Results", show_header=True)
        table.add_column("Text", style="cyan", max_width=40)
        table.add_column("Predicted Class", style="green")
        table.add_column("Confidence", justify="right")

        for result in results[:20]:  # Show first 20
            confidence_str = f"{result['confidence']:.2%}" if result['confidence'] > 0 else "-"
            table.add_row(
                truncate_text(result['text'], 40),
                result['label'],
                confidence_str,
            )

        console.print(table)

        if len(results) > 20:
            print_info(f"Showing first 20 of {len(results)} results")

        # Summary stats
        console.print()
        summary_parts = [f"{label} ({count})" for label, count in sorted(stats.items())]
        print_success(f"Summary: {len(results)} texts classified")
        console.print(f"  Distribution: {', '.join(summary_parts)}")

    except click.Abort:
        pass
    except click.ClickException:
        raise
    except Exception as e:
        print_error(f"Batch multi-class classification failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()

