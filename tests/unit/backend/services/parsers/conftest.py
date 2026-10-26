"""Shared fixtures for parser tests.

The Instagram and Telegram parsers deliberately sleep between requests to
avoid rate limits. In unit tests every external call is mocked, so the delays
only slow the suite down. These autouse fixtures replace the ``time`` /
``asyncio`` modules seen by the parser modules with proxies whose ``sleep``
returns immediately; everything else is forwarded to the real modules.
"""

import asyncio
import time

import pytest

from backend.postparse.services.parsers.instagram import instagram_parser
from backend.postparse.services.parsers.telegram import telegram_parser


class _ModuleProxy:
    """Forward attribute access to ``module`` except for overridden names."""

    def __init__(self, module, **overrides):
        self._module = module
        self.__dict__.update(overrides)

    def __getattr__(self, name):
        return getattr(self._module, name)


_real_asyncio_sleep = asyncio.sleep


async def _instant_async_sleep(delay=0, result=None):
    """Yield to the event loop once without actually waiting."""
    return await _real_asyncio_sleep(0, result)


@pytest.fixture(autouse=True)
def no_parser_delays(monkeypatch):
    """Make parser rate-limit delays instantaneous."""
    monkeypatch.setattr(
        instagram_parser, "time", _ModuleProxy(time, sleep=lambda seconds: None)
    )
    monkeypatch.setattr(
        telegram_parser, "asyncio", _ModuleProxy(asyncio, sleep=_instant_async_sleep)
    )
