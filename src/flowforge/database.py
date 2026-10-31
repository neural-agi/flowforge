"""Small psycopg connection and transaction helpers."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .config import Settings


def connect(settings: Settings | None = None) -> psycopg.Connection:
    """Open a PostgreSQL connection using UTC-friendly dictionary rows."""
    active_settings = settings or Settings.from_environment()
    return psycopg.connect(active_settings.database_url, row_factory=dict_row)


@contextmanager
def transaction(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    """Yield a connection and commit or roll back its transaction."""
    connection = connect(settings)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
