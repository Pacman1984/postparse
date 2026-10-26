"""Fixtures for schema v2 database tests (always a fresh tmp_path database)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from postparse.core.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """A migrated schema v2 database in ``tmp_path``."""
    return Database.open(tmp_path / "v2.db")


@pytest.fixture
def conn(db: Database) -> Iterator[sqlite3.Connection]:
    """A connection inside an open write transaction (rolled back afterwards)."""
    connection = db.connect()
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()
