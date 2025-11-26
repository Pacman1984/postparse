"""
Serve command for PostParse CLI.

This module provides the command to start the FastAPI server.

Example:
    $ postparse serve
    $ postparse serve --port 8080 --reload
"""

import rich_click as click
from rich.panel import Panel

from backend.postparse.cli.utils import (
    get_console,
    load_config,
    print_success,
    print_error,
    print_info,
)


@click.command()
@click.option(
    '--host',
    help='Host to bind',
)
@click.option(
    '--port',
    type=int,
    help='Port to bind',
)
@click.option(
    '--reload',
    is_flag=True,
    help='Enable auto-reload',
)
@click.option(
    '--workers',
    type=int,
    help='Number of workers',
)
@click.option(
    '--log-level',
    type=click.Choice(['debug', 'info', 'warning', 'error']),
    help='Log level',
)
@click.pass_context
def serve(ctx, host, port, reload, workers, log_level):
    """🚀 Start the FastAPI server.
    
    This command starts the FastAPI server using Uvicorn. The server provides
    REST API endpoints for extraction, classification, and search operations.
    
    Examples:
        postparse serve
        
        postparse serve --port 8080 --reload
        
        postparse serve --workers 4 --log-level debug
    
    The API will be available at:
        - Swagger UI: http://localhost:8000/docs
        - ReDoc: http://localhost:8000/redoc
    
    Note:
        Use --reload for development. For production, use multiple workers
        without reload for better performance.
    """
    console = get_console()
    
    try:
        # Load config
        config_path = ctx.obj.get('config')
        config = load_config(config_path)
        
        # Determine server settings
        server_host = host or config.get('api.host', default='0.0.0.0')
        server_port = port or config.get('api.port', default=8000)
        server_reload = reload or config.get('api.reload', default=False)
        server_workers = workers or config.get('api.workers', default=1)
        server_log_level = log_level or config.get('api.log_level', default='info')
        
        # Display startup info
        startup_info = f"""[bold cyan]PostParse API Server[/bold cyan]

[bold]Server URL:[/bold] http://{server_host}:{server_port}
[bold]API Documentation:[/bold] http://{server_host}:{server_port}/docs
[bold]ReDoc:[/bold] http://{server_host}:{server_port}/redoc

[bold]Configuration:[/bold]
  • Workers: {server_workers}
  • Auto-reload: {'Yes' if server_reload else 'No'}
  • Log level: {server_log_level}
  • Auth enabled: {config.get('api.auth_enabled', default=False)}
  • Rate limiting: {config.get('api.rate_limiting', default=False)}

[yellow]Press Ctrl+C to stop the server[/yellow]
"""
        
        console.print(Panel(startup_info, border_style="green"))
        
        # Import uvicorn and start server
        import uvicorn
        
        # Run server
        uvicorn.run(
            "backend.postparse.api.main:app",
            host=server_host,
            port=server_port,
            reload=server_reload,
            workers=server_workers if not server_reload else 1,  # Reload doesn't work with multiple workers
            log_level=server_log_level,
        )
        
    except KeyboardInterrupt:
        console.print()
        print_info("Server stopped by user")
    except click.Abort:
        pass
    except Exception as e:
        print_error(f"Failed to start server: {e}")
        if ctx.obj.get('verbose'):
            console.print_exception()
        raise click.Abort()

