"""SQLite connections and the :class:`Database` unit-of-work entry point.

Connections are cheap; open one per unit of work (request, job step, CLI
command) and close it afterwards. Every connection gets the same PRAGMAs, so
foreign keys and busy handling behave identically everywhere.

Example:
    >>> db = Database.open("data/postparse.db")
    >>> with db.transaction() as conn:
    ...     ItemsRepo(conn).upsert(item)
    >>> with db.read() as conn:
    ...     ItemsRepo(conn).get(1)
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from postparse.core.db.migrate import migrate as run_migrations

__all__ = ["MIN_SQLITE_VERSION", "Database", "connect"]

logger = logging.getLogger(__name__)

#: Oldest SQLite library supported (STRICT tables, concat_ws, JSON functions).
MIN_SQLITE_VERSION: tuple[int, int, int] = (3, 45, 0)

_PRAGMAS = (
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA temp_store = MEMORY",
)


def _check_sqlite_version() -> None:
    """Raise if the linked SQLite library is too old."""
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        required = ".".join(map(str, MIN_SQLITE_VERSION))
        raise RuntimeError(f"SQLite {required}+ is required, found {sqlite3.sqlite_version}")


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a configured connection to the database at ``path``.

    The connection is in autocommit mode (``isolation_level=None``); use
    :meth:`Database.transaction` or explicit ``BEGIN``/``COMMIT`` for writes.

    Args:
        path: Database file.

    Returns:
        Connection with ``sqlite3.Row`` row factory and PRAGMAs applied.

    Raises:
        RuntimeError: If the SQLite library is older than 3.45.
    """
    _check_sqlite_version()
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    return conn


class Database:
    """Handle on a schema v2 database file.

    The first use creates parent directories and (unless ``migrate=False``)
    applies pending migrations. Each :meth:`transaction` / :meth:`read` call
    opens and closes its own connection.

    Attributes:
        path: Absolute database file path.
    """

    def __init__(self, path: str | Path, *, migrate: bool = True) -> None:
        """Create a handle without touching the file yet.

        Args:
            path: Database file (``:memory:`` is not supported because every
                unit of work opens a new connection).
            migrate: Apply pending migrations on first use.

        Raises:
            ValueError: If ``path`` is ``:memory:``.
        """
        if str(path) == ":memory:":
            raise ValueError("Database requires a file path; ':memory:' is not supported")
        self.path = Path(path).expanduser().resolve()
        self._migrate = migrate
        self._ready = False
        self._lock = threading.Lock()

    @classmethod
    def open(cls, path: str | Path, *, migrate: bool = True) -> Database:
        """Create a handle and initialize it immediately.

        Args:
            path: Database file.
            migrate: Apply pending migrations.

        Returns:
            Ready-to-use database handle.
        """
        db = cls(path, migrate=migrate)
        db.ensure_ready()
        return db

    def ensure_ready(self) -> None:
        """Create parent directories and run pending migrations (once)."""
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self._migrate:
                conn = connect(self.path)
                try:
                    applied = run_migrations(conn)
                finally:
                    conn.close()
                if applied:
                    logger.info(
                        "Database %s migrated to version %d", self.path, applied[-1].version
                    )
            self._ready = True

    def connect(self) -> sqlite3.Connection:
        """Return a new configured connection (caller closes it)."""
        self.ensure_ready()
        return connect(self.path)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a write unit of work in a ``BEGIN IMMEDIATE`` transaction.

        Commits on success, rolls back on any exception, always closes.

        Yields:
            Connection inside an open write transaction.
        """
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            if conn.in_transaction:
                conn.execute("COMMIT")
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Run a read-only unit of work on a consistent snapshot.

        Yields:
            Connection inside a deferred transaction that is rolled back on exit.
        """
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            yield conn
        finally:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            conn.close()
