"""
db_manager.py — DatabaseConnection, a thread-safe Singleton over a MySQL connection pool.

Why a singleton: Streamlit re-runs the whole script on every widget interaction.
Without one, each rerun would open fresh connections and exhaust MySQL's
max_connections within minutes. With it, the pool is created once per process and
every manager borrows from it.

Subclasses (the managers in managers.py) inherit the query helpers. Each subclass
is itself a singleton, and they all share the one pool held on DatabaseConnection.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Iterator, Sequence

import mysql.connector
import pandas as pd
from mysql.connector import errors as mysql_errors
from mysql.connector.pooling import MySQLConnectionPool

from hr_analytics.config import DBSettings, load_settings

log = logging.getLogger(__name__)


def to_numeric_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Convert DECIMAL columns (decimal.Decimal objects, dtype=object) to floats so
    pandas maths and Plotly treat them as numbers, not categories."""
    for col in df.columns:
        if df[col].dtype == object and df[col].map(lambda v: isinstance(v, Decimal)).any():
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


class DatabaseError(RuntimeError):
    """Raised for any database failure, with a message safe to show in the UI."""


class DatabaseConnection:
    _instances: dict[type, "DatabaseConnection"] = {}
    _pool: MySQLConnectionPool | None = None
    _settings: DBSettings | None = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "DatabaseConnection":
        with DatabaseConnection._lock:
            if cls not in DatabaseConnection._instances:
                DatabaseConnection._instances[cls] = super().__new__(cls)
            return DatabaseConnection._instances[cls]

    def __init__(self, settings: DBSettings | None = None) -> None:
        with DatabaseConnection._lock:
            if DatabaseConnection._pool is None:
                DatabaseConnection._settings = settings or load_settings()
                DatabaseConnection._pool = self._create_pool(DatabaseConnection._settings)

    # ------------------------------------------------------------------ pool
    @staticmethod
    def _create_pool(s: DBSettings) -> MySQLConnectionPool:
        try:
            pool = MySQLConnectionPool(
                pool_name="hr_analytics_pool",
                pool_size=s.pool_size,
                pool_reset_session=True,
                host=s.host,
                port=s.port,
                user=s.user,
                password=s.password,
                autocommit=False,
                charset="utf8mb4",
                collation="utf8mb4_0900_ai_ci",
                connection_timeout=10,
                ssl_disabled=not s.ssl,
            )
            log.info("MySQL pool created (%s@%s:%s, size=%s)", s.user, s.host, s.port, s.pool_size)
            return pool
        except mysql_errors.Error as exc:
            raise DatabaseError(f"Could not connect to MySQL at {s.host}:{s.port} — {exc.msg}") from exc

    @classmethod
    def reset(cls) -> None:
        """Drop the pool and all singletons (tests, or after changing credentials)."""
        with DatabaseConnection._lock:
            DatabaseConnection._pool = None
            DatabaseConnection._instances.clear()

    @contextmanager
    def connection(self) -> Iterator[mysql.connector.MySQLConnection]:
        """Borrow a connection; commit on success, roll back on error, always return it."""
        assert DatabaseConnection._pool is not None
        try:
            conn = DatabaseConnection._pool.get_connection()
        except mysql_errors.PoolError as exc:
            raise DatabaseError("All database connections are busy; try again.") from exc
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()  # returns it to the pool

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """A dictionary cursor whose statements commit or roll back together."""
        with self.connection() as conn:
            cur = conn.cursor(dictionary=True)
            try:
                yield cur
            finally:
                cur.close()

    # ------------------------------------------------------------------ helpers
    def execute(self, sql: str, params: Sequence[Any] | dict | None = None) -> int:
        """Run one write statement. Returns lastrowid for INSERTs, else rowcount."""
        try:
            with self.transaction() as cur:
                cur.execute(sql, params)
                return cur.lastrowid or cur.rowcount
        except mysql_errors.Error as exc:
            raise self._wrap(exc) from exc

    def fetch_all(self, sql: str, params: Sequence[Any] | dict | None = None) -> list[dict]:
        try:
            with self.transaction() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        except mysql_errors.Error as exc:
            raise self._wrap(exc) from exc

    def fetch_one(self, sql: str, params: Sequence[Any] | dict | None = None) -> dict | None:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def fetch_df(self, sql: str, params: Sequence[Any] | dict | None = None) -> pd.DataFrame:
        """DECIMAL columns arrive as decimal.Decimal objects (dtype=object). Plotly and pandas
        maths treat those as categories/strings, so convert them to float here, once."""
        return to_numeric_frame(pd.DataFrame(self.fetch_all(sql, params)))

    def call_procedure(self, name: str, args: Sequence[Any] = ()) -> list[list[dict]]:
        """CALL a stored procedure; returns every result set it produced."""
        try:
            with self.transaction() as cur:
                cur.callproc(name, tuple(args))
                return [rs.fetchall() for rs in cur.stored_results()]
        except mysql_errors.Error as exc:
            raise self._wrap(exc) from exc

    def health_check(self) -> dict:
        row = self.fetch_one("SELECT VERSION() AS version, NOW() AS server_time")
        return row or {}

    @staticmethod
    def _wrap(exc: mysql_errors.Error) -> DatabaseError:
        """Translate driver errors into messages a user can act on."""
        log.exception("Database error")
        code = getattr(exc, "errno", None)
        friendly = {
            1062: "That record already exists (duplicate value).",
            1451: "This record is still referenced by other records.",
            1452: "A referenced record does not exist.",
            3819: "A value is outside its allowed range.",
            1146: "A required table is missing — has the database been set up? (scripts/setup_database.py)",
            1305: "A stored procedure is missing — run scripts/setup_database.py.",
        }.get(code)
        return DatabaseError(friendly or f"Database error {code}: {getattr(exc, 'msg', exc)}")
