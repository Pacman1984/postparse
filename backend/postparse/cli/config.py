"""
Config commands for PostParse CLI.

This module provides commands for configuration management.

Example:
    $ postparse config show
    $ postparse config validate --fix
"""

import json
from pathlib import Path

import rich_click as click
from rich.table import Table
from rich.syntax import Syntax
from rich.panel import Panel

from backend.postparse.cli.utils import (
    get_console,
    load_config,
    print_success,
    print_error,
    print_info,
    print_warning,
)


@click.group()
def config():
    """⚙️  View and validate configuration."""
    pass


@config.command()
@click.pass_context
def env(ctx):
    """📋 Show loaded environment variables."""
    console = get_console()
    import os
    from pathlib import Path
    
    # Check which .env file was loaded
    loaded_file = os.getenv('_POSTPARSE_ENV_FILE')
    
    if loaded_file:
        print_success(f"Loaded environment from: [cyan]{loaded_file}[/cyan]")
    else:
        print_warning("No .env file found. Searched:")
        console.print("  • config/.env")
        console.print("  • .env")
    
    console.print()
    
    # Relevant env vars
    env_vars = {
        'Telegram': ['TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'TELEGRAM_PHONE'],
        'Instagram': ['INSTAGRAM_USERNAME', 'INSTAGRAM_PASSWORD'],
        'LLM': ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY'],
    }
    
    for category, vars in env_vars.items():
        table = Table(title=f"{category} Environment Variables", show_header=True, box=None)
        table.add_column("Variable", style="cyan", width=25)
        table.add_column("Status", style="green")
        
        for var in vars:
            value = os.getenv(var)
            if value:
                # Mask sensitive values
                if 'PASSWORD' in var or 'KEY' in var or 'HASH' in var:
                    display = f"✓ Set (***{value[-4:]})" if len(value) >= 4 else "✓ Set (***)"
                else:
                    display = f"✓ Set ({value})"
                table.add_row(var, display, style="green")
            else:
                table.add_row(var, "✗ Not set", style="dim")
        
        console.print(table)
        console.print()
    
    console.print("[dim]Current working directory:[/dim]")
    console.print(f"  {Path.cwd()}")
    console.print()


@config.command()
@click.option(
    '--section',
    type=click.Choice(['llm', 'api', 'database', 'telegram', 'instagram']),
    help='Show specific section',
)
@click.option(
    '--format',
    type=click.Choice(['text', 'json']),
    default='text',
    help='Output format',
)
@click.pass_context
def show(ctx, section, format):
    """📄 Display current configuration."""
    console = get_console()
    
    try:
        # Load config
        config_path = ctx.obj.get('config')
        cfg = load_config(config_path)
        
        # Get config file path
        config_file = cfg.config_path
        
        # Build config dictionary
        config_dict = {}
        
        if not section or section == 'llm':
            llm_section = cfg.get_section('llm')
            providers = llm_section.get('providers', [])
            config_dict['llm'] = {
                'providers': [
                    {
                        'name': p.get('name'),
                        'base_url': p.get('base_url'),
                        'api_key': '***' if p.get('api_key') else None,
                        'model_name': p.get('model_name'),
                    }
                    for p in providers
                ] if providers else []
            }
        
        if not section or section == 'api':
            api_section = cfg.get_section('api')
            config_dict['api'] = {
                'host': api_section.get('host', '0.0.0.0'),
                'port': api_section.get('port', 8000),
                'reload': api_section.get('reload', False),
                'workers': api_section.get('workers', 1),
                'log_level': api_section.get('log_level', 'info'),
                'auth_enabled': api_section.get('auth_enabled', False),
                'rate_limiting': api_section.get('rate_limiting', False),
            }
        
        if not section or section == 'database':
            db_section = cfg.get_section('database')
            db_path = db_section.get('path') or db_section.get('default_db_path', 'data/postparse.db')
            config_dict['database'] = {
                'path': str(db_path),
                'backup_enabled': db_section.get('backup_enabled', False),
            }
        
        if not section or section == 'telegram':
            telegram_section = cfg.get_section('telegram')
            if telegram_section:
                config_dict['telegram'] = {
                    'api_id': '***' if telegram_section.get('api_id') else None,
                    'api_hash': '***' if telegram_section.get('api_hash') else None,
                    'session_name': telegram_section.get('session_name', 'telegram_session'),
                }
        
        if not section or section == 'instagram':
            instagram_section = cfg.get_section('instagram')
            if instagram_section:
                config_dict['instagram'] = {
                    'username': instagram_section.get('username'),
                    'password': '***' if instagram_section.get('password') else None,
                    'session_file': instagram_section.get('session_file', 'instagram_session'),
                }
        
        # Output
        if format == 'json':
            console.print_json(json.dumps(config_dict, indent=2))
        else:
            # Show config file path
            print_info(f"Configuration file: {config_file}")
            console.print()
            
            # Display as formatted JSON with syntax highlighting
            json_str = json.dumps(config_dict, indent=2)
            syntax = Syntax(json_str, "json", theme="monokai", line_numbers=False)
            console.print(Panel(syntax, title="Configuration", border_style="cyan"))
        
    except click.Abort:
        pass
    except Exception as e:
        print_error(f"Failed to show config: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()


@config.command()
@click.option(
    '--fix',
    is_flag=True,
    help='Auto-fix common issues',
)
@click.pass_context
def validate(ctx, fix):
    """✅ Validate configuration and check for issues."""
    console = get_console()
    
    try:
        validation_results = []
        
        # Check 1: Config file exists
        config_path = ctx.obj.get('config')
        
        try:
            cfg = load_config(config_path)
            config_file = cfg.config_path
            
            validation_results.append({
                'check': 'Config file exists',
                'status': 'pass',
                'message': f'Found at {config_file}',
            })
        except Exception as e:
            validation_results.append({
                'check': 'Config file exists',
                'status': 'fail',
                'message': str(e),
            })
            # Can't continue without config
            display_validation_results(console, validation_results)
            raise click.Abort()
        
        # Check 2: Database path
        db_path_str = cfg.get('database.path') or cfg.get('database.default_db_path', default='data/postparse.db')
        db_path = Path(db_path_str)
        db_dir = db_path.parent
        
        if db_dir.exists():
            validation_results.append({
                'check': 'Database directory',
                'status': 'pass',
                'message': f'{db_dir} exists',
            })
        else:
            if fix:
                try:
                    db_dir.mkdir(parents=True, exist_ok=True)
                    validation_results.append({
                        'check': 'Database directory',
                        'status': 'pass',
                        'message': f'Created {db_dir}',
                    })
                except Exception as e:
                    validation_results.append({
                        'check': 'Database directory',
                        'status': 'fail',
                        'message': f'Failed to create {db_dir}: {e}',
                    })
            else:
                validation_results.append({
                    'check': 'Database directory',
                    'status': 'fail',
                    'message': f'{db_dir} does not exist. Use --fix to create.',
                })
        
        # Check 3: LLM providers
        llm_providers = cfg.get_section('llm').get('providers', [])
        if llm_providers:
            validation_results.append({
                'check': 'LLM providers',
                'status': 'pass',
                'message': f'{len(llm_providers)} provider(s) configured',
            })
            
            # Validate each provider
            for provider in llm_providers:
                provider_name = provider.get('name')
                provider_base_url = provider.get('base_url')
                
                if not provider_name:
                    validation_results.append({
                        'check': f'Provider configuration',
                        'status': 'fail',
                        'message': 'Provider missing name',
                    })
                elif not provider_base_url:
                    validation_results.append({
                        'check': f'Provider {provider_name}',
                        'status': 'warning',
                        'message': 'Missing base_url',
                    })
                else:
                    validation_results.append({
                        'check': f'Provider {provider_name}',
                        'status': 'pass',
                        'message': f'Configured at {provider_base_url}',
                    })
        else:
            validation_results.append({
                'check': 'LLM providers',
                'status': 'warning',
                'message': 'No LLM providers configured. Classification features will be limited.',
            })
        
        # Check 4: API configuration
        api_port = cfg.get('api.port', default=8000)
        if 1024 <= api_port <= 65535:
            validation_results.append({
                'check': 'API port',
                'status': 'pass',
                'message': f'Port {api_port} is valid',
            })
        else:
            validation_results.append({
                'check': 'API port',
                'status': 'fail',
                'message': f'Port {api_port} is invalid. Use 1024-65535.',
            })
        
        # Check 5: Session directories
        session_dirs = ['sessions', 'data', 'logs']
        for dir_name in session_dirs:
            dir_path = Path(dir_name)
            if dir_path.exists():
                validation_results.append({
                    'check': f'Directory {dir_name}',
                    'status': 'pass',
                    'message': 'Exists',
                })
            else:
                if fix:
                    try:
                        dir_path.mkdir(parents=True, exist_ok=True)
                        validation_results.append({
                            'check': f'Directory {dir_name}',
                            'status': 'pass',
                            'message': 'Created',
                        })
                    except Exception as e:
                        validation_results.append({
                            'check': f'Directory {dir_name}',
                            'status': 'warning',
                            'message': f'Failed to create: {e}',
                        })
                else:
                    validation_results.append({
                        'check': f'Directory {dir_name}',
                        'status': 'warning',
                        'message': 'Does not exist. Use --fix to create.',
                    })
        
        # Display results
        display_validation_results(console, validation_results)
        
        # Summary
        passed = sum(1 for r in validation_results if r['status'] == 'pass')
        warnings = sum(1 for r in validation_results if r['status'] == 'warning')
        failed = sum(1 for r in validation_results if r['status'] == 'fail')
        
        console.print()
        if failed > 0:
            print_error(f"Validation failed: {passed} passed, {warnings} warnings, {failed} failed")
            raise click.Abort()
        elif warnings > 0:
            print_warning(f"Validation completed with warnings: {passed} passed, {warnings} warnings")
        else:
            print_success(f"Validation passed: {passed} checks passed")
        
    except click.Abort:
        # Re-raise click.Abort so Click can handle it and set exit code to 1
        raise
    except Exception as e:
        print_error(f"Validation failed: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()


def display_validation_results(console, results):
    """
    Display validation results in a table.
    
    Args:
        console: Rich Console instance
        results: List of validation result dictionaries
    """
    table = Table(title="Validation Results", show_header=True)
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details")
    
    for result in results:
        status = result['status']
        
        # Format status
        if status == 'pass':
            status_text = "[green]✓ Pass[/green]"
        elif status == 'warning':
            status_text = "[yellow]⚠ Warning[/yellow]"
        else:  # fail
            status_text = "[red]✗ Fail[/red]"
        
        table.add_row(
            result['check'],
            status_text,
            result['message'],
        )
    
    console.print(table)

