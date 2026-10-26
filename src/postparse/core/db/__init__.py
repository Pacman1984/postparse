"""Schema v2 database layer: connections, migrations, models and repositories.

This is the only database layer. Old schema v1 databases are imported with
:func:`postparse.core.db.legacy_v1.migrate_v1` (``postparse db migrate-v1``),
which reads the v1 tables directly.
"""

from postparse.core.db.connection import MIN_SQLITE_VERSION, Database, connect
from postparse.core.db.migrate import MigrationError, latest_version, migrate

__all__ = [
    "MIN_SQLITE_VERSION",
    "Database",
    "MigrationError",
    "connect",
    "latest_version",
    "migrate",
]
