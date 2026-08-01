"""
database.py
-----------
PostgreSQL connection pool using psycopg2.
All queries are executed via raw parameterized SQL — no ORM.
"""

import os
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/credit_risk"
)

# Thread-safe connection pool: 2 min, 20 max connections
_pool: pool.ThreadedConnectionPool | None = None


def init_pool() -> None:
    """Initialise the connection pool. Called once at app startup."""
    global _pool
    _pool = pool.ThreadedConnectionPool(
        minconn=2,
        maxconn=20,
        dsn=DATABASE_URL,
        cursor_factory=RealDictCursor,
    )


def get_pool() -> pool.ThreadedConnectionPool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised — call init_pool() first.")
    return _pool


@contextmanager
def get_db():
    """
    Context manager that yields a psycopg2 connection from the pool.
    Commits on clean exit, rolls back on exception, always returns conn to pool.

    Usage::
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    conn = get_pool().getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        get_pool().putconn(conn)


def execute_sql_file(path: str) -> None:
    """Run a .sql file against the database (used for schema bootstrap)."""
    with open(path, "r", encoding="utf-8") as fh:
        sql = fh.read()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
