"""Schema v2 database layer: connections, migrations, models and repositories.

The legacy schema v1 layer lives in :mod:`postparse.core.data.database` and is
unaffected by this package.
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
