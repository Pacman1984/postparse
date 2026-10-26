"""Schema migration runner for the schema v2 database.

Migrations are SQL files named ``NNNN_name.sql`` shipped as package data in
``postparse/core/db/migrations``. Each pending migration is applied in its own
``BEGIN IMMEDIATE`` transaction together with its ``schema_migrations`` row and
``PRAGMA user_version``. Checksums are computed over the file text with line
endings normalized to ``\\n`` (so a CRLF checkout on Windows does not count as a
change); an applied migration whose checksum differs is refused.

Note:
    The runner executes statements with ``foreign_keys=ON``. A future migration
    that rebuilds a table must not rely on toggling ``foreign_keys`` (it cannot
    change inside a transaction); copy data in dependency order instead.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass
from importlib import resources

from postparse.core.timeutil import utcnow_ts

__all__ = [
    "Migration",
    "MigrationError",
    "applied_migrations",
    "discover_migrations",
    "latest_version",
    "migrate",
    "pending_migrations",
]

logger = logging.getLogger(__name__)

_FILENAME_RE = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")

_BOOKKEEPING_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    applied_at  TEXT NOT NULL
) STRICT
"""


class MigrationError(RuntimeError):
    """Raised when migrations cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One migration file.

    Attributes:
        version: Numeric prefix of the file name.
        name: Descriptive part of the file name.
        sql: File contents with normalized line endings.
        sha256: Hex digest of ``sql``.
    """

    version: int
    name: str
    sql: str
    sha256: str

    @classmethod
    def from_text(cls, filename: str, text: str) -> Migration:
        """Build a migration from a file name and its contents.

        Args:
            filename: ``NNNN_name.sql``.
            text: SQL text.

        Returns:
            The migration.

        Raises:
            MigrationError: If the file name does not follow the convention.
        """
        match = _FILENAME_RE.match(filename)
        if not match:
            raise MigrationError(f"Invalid migration file name: {filename!r}")
        sql = text.replace("\r\n", "\n").replace("\r", "\n")
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        return cls(int(match["version"]), match["name"], sql, digest)


def discover_migrations() -> list[Migration]:
    """Load the migration files shipped with the package, ordered by version.

    Returns:
        Migrations sorted by version.

    Raises:
        MigrationError: On invalid names, duplicate or non-contiguous versions.
    """
    folder = resources.files("postparse.core.db").joinpath("migrations")
    migrations = [
        Migration.from_text(entry.name, entry.read_text(encoding="utf-8"))
        for entry in folder.iterdir()
        if entry.name.endswith(".sql")
    ]
    migrations.sort(key=lambda m: m.version)
    _validate_sequence(migrations)
    return migrations


def _validate_sequence(migrations: list[Migration]) -> None:
    """Ensure versions are unique and contiguous starting at 1."""
    for expected, migration in enumerate(migrations, start=1):
        if migration.version != expected:
            raise MigrationError(
                f"Migration versions must be contiguous from 1; expected {expected}, "
                f"found {migration.version} ({migration.name})"
            )


def latest_version(migrations: list[Migration] | None = None) -> int:
    """Return the highest known migration version (0 if there are none)."""
    migrations = discover_migrations() if migrations is None else migrations
    return max((m.version for m in migrations), default=0)


def applied_migrations(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    """Return ``{version: (name, sha256)}`` of applied migrations.

    Args:
        conn: Open connection.

    Returns:
        Applied migrations; empty if the bookkeeping table does not exist.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if not exists:
        return {}
    rows = conn.execute("SELECT version, name, sha256 FROM schema_migrations").fetchall()
    return {int(row[0]): (str(row[1]), str(row[2])) for row in rows}


def _verify(applied: dict[int, tuple[str, str]], migrations: list[Migration]) -> None:
    """Refuse to continue if applied migrations are unknown or were edited."""
    known = {m.version: m for m in migrations}
    for version, (name, digest) in sorted(applied.items()):
        migration = known.get(version)
        if migration is None:
            raise MigrationError(
                f"Database has migration {version:04d}_{name} which this version of "
                "PostParse does not know; refusing to touch a newer schema"
            )
        if migration.sha256 != digest:
            raise MigrationError(
                f"Checksum mismatch for applied migration {version:04d}_{name}: "
                "the migration file was modified after it was applied"
            )


def pending_migrations(
    conn: sqlite3.Connection, migrations: list[Migration] | None = None
) -> list[Migration]:
    """Return migrations not yet applied, after verifying applied checksums.

    Args:
        conn: Open connection.
        migrations: Migrations to consider (defaults to the packaged ones).

    Returns:
        Pending migrations in version order.

    Raises:
        MigrationError: If an applied migration is unknown or was modified.
    """
    migrations = discover_migrations() if migrations is None else migrations
    applied = applied_migrations(conn)
    _verify(applied, migrations)
    return [m for m in migrations if m.version not in applied]


def _statements(sql: str) -> list[str]:
    """Split a SQL script into complete statements (trigger bodies stay intact)."""
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    leftover = "\n".join(
        part for part in buffer.splitlines() if part.strip() and not part.strip().startswith("--")
    )
    if leftover.strip():
        raise MigrationError(f"Incomplete SQL statement at end of migration: {leftover[:80]!r}")
    return statements


def _refuse_foreign_database(conn: sqlite3.Connection) -> None:
    """Refuse to migrate a non-empty database that this runner never managed.

    Protects against pointing the v2 runner at a legacy (schema v1) file.
    """
    if applied_migrations(conn):
        return
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_schema WHERE type IN ('table', 'view') "
            "AND name NOT LIKE 'sqlite_%' AND name != 'schema_migrations'"
        ).fetchall()
    ]
    if tables:
        raise MigrationError(
            "Refusing to migrate a non-empty database without schema_migrations "
            f"(found tables: {', '.join(sorted(tables)[:5])}); is this a legacy v1 database?"
        )


def _ensure_wal(conn: sqlite3.Connection) -> None:
    """Switch the database to WAL journal mode if it is not already."""
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    if str(mode).lower() != "wal":
        new_mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        logger.debug("journal_mode changed from %s to %s", mode, new_mode)


def migrate(conn: sqlite3.Connection, migrations: list[Migration] | None = None) -> list[Migration]:
    """Apply all pending migrations, each in its own transaction.

    Args:
        conn: Connection in autocommit mode (``isolation_level=None``), as
            returned by :func:`postparse.core.db.connection.connect`.
        migrations: Migrations to apply (defaults to the packaged ones).

    Returns:
        The migrations that were applied by this call.

    Raises:
        MigrationError: If an applied migration is unknown or was modified, or
            a migration fails (its transaction is rolled back).
    """
    if conn.in_transaction:
        raise MigrationError("migrate() must not be called inside an open transaction")
    migrations = discover_migrations() if migrations is None else migrations
    _refuse_foreign_database(conn)
    _ensure_wal(conn)
    conn.execute(_BOOKKEEPING_SQL)

    applied_now: list[Migration] = []
    for migration in pending_migrations(conn, migrations):
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Another process may have applied it while we waited for the lock.
            if migration.version in applied_migrations(conn):
                conn.execute("ROLLBACK")
                continue
            for statement in _statements(migration.sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, sha256, applied_at) "
                "VALUES (?, ?, ?, ?)",
                (migration.version, migration.name, migration.sha256, utcnow_ts()),
            )
            conn.execute(f"PRAGMA user_version = {int(migration.version)}")
            conn.execute("COMMIT")
        except Exception as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise MigrationError(
                f"Migration {migration.version:04d}_{migration.name} failed: {exc}"
            ) from exc
        logger.info("Applied migration %04d_%s", migration.version, migration.name)
        applied_now.append(migration)
    return applied_now
