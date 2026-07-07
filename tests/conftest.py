"""
Root-level pytest configuration for PostParse tests.

This module provides fixtures and configuration for proper async cleanup,
especially for background tasks from Telethon and other async libraries.
"""

import asyncio
import pytest
import warnings


# Configure pytest-asyncio
pytest_plugins = ('pytest_asyncio',)


@pytest.fixture(scope="session")
def event_loop_policy():
    """
    Set event loop policy for the test session.
    
    Returns:
        Event loop policy instance.
    """
    policy = asyncio.get_event_loop_policy()
    return policy


@pytest.fixture(scope="function")
async def cleanup_tasks():
    """
    Ensure all async tasks are properly cleaned up after each test.
    
    This fixture yields control to the test, then ensures all pending
    tasks are properly awaited or cancelled before the event loop closes.
    This prevents RuntimeError: Event loop is closed from background tasks.
    
    Example:
        async def test_something(cleanup_tasks):
            # Test code here
            pass
    """
    yield
    
    # Get all pending tasks
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Get all tasks except current
            pending = [
                task for task in asyncio.all_tasks(loop)
                if not task.done() and task is not asyncio.current_task()
            ]
            
            if pending:
                # Cancel all pending tasks
                for task in pending:
                    task.cancel()
                
                # Wait for all tasks to be cancelled with timeout
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    # Tasks didn't cancel in time, that's okay
                    pass
                except Exception:
                    # Ignore errors during cleanup
                    pass
    except RuntimeError:
        # Event loop already closed or not available
        pass


@pytest.fixture(autouse=True)
def suppress_telethon_warnings():
    """
    Suppress known harmless warnings from Telethon during test cleanup.
    
    These warnings occur when Telethon background tasks are cleaning up
    and the event loop has already been closed. They don't indicate actual
    problems with the code.
    """
    # Suppress ResourceWarnings from Telethon coroutines
    warnings.filterwarnings(
        "ignore",
        category=ResourceWarning,
        message=".*coroutine.*was never awaited.*"
    )
    
    # Suppress RuntimeWarnings from asyncio during Telethon cleanup
    warnings.filterwarnings(
        "ignore",
        category=RuntimeWarning,
        message=".*coroutine.*was never awaited.*"
    )
    
    # Suppress RuntimeWarnings about event loop closure
    warnings.filterwarnings(
        "ignore",
        category=RuntimeWarning,
        message=".*Event loop is closed.*"
    )
    
    yield


def pytest_configure(config):
    """
    Configure pytest with custom settings.
    
    Args:
        config: Pytest configuration object.
    """
    # Set asyncio mode to auto
    config.option.asyncio_mode = "auto"

