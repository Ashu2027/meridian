"""
db/connection.py
Pooled TiDB/MySQL connection with execute/fetch helpers.
Uses mysql-connector-python's built-in connection pool (thread-safe).
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, List, Optional

import mysql.connector
from mysql.connector import pooling, Error as MySQLError
from mysql.connector.pooling import MySQLConnectionPool

from config import AppConfig

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Raised for unrecoverable DB-level problems."""


class Database:
    """
    Thin wrapper around a MySQLConnectionPool.
    One Database instance lives for the entire process lifetime.
    """

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._pool: Optional[MySQLConnectionPool] = None

    # ── Connection Management ──────────────────────────────────────────────────

    def connect(self) -> None:
        """Build the connection pool.  Raises DatabaseError on failure."""
        pool_cfg: dict[str, Any] = {
            "host":     self._cfg.tidb_host,
            "port":     self._cfg.tidb_port,
            "user":     self._cfg.tidb_user,
            "password": self._cfg.tidb_password,
            "database": self._cfg.tidb_database,
            "autocommit": True,
            "connection_timeout": 10,
            "charset": "utf8mb4",
        }

        if self._cfg.tidb_use_tls:
            ssl_args: dict[str, Any] = {"ssl_disabled": False}
            if self._cfg.tidb_ssl_ca:
                ssl_args["ssl_ca"] = self._cfg.tidb_ssl_ca
                ssl_args["ssl_verify_cert"] = True
                ssl_args["ssl_verify_identity"] = True
            pool_cfg.update(ssl_args)

        try:
            self._pool = pooling.MySQLConnectionPool(
                pool_name="meridian_pool",
                pool_size=5,
                pool_reset_session=True,
                **pool_cfg,
            )
            logger.info("TiDB connection pool created (size=5) → %s:%s/%s",
                        self._cfg.tidb_host, self._cfg.tidb_port, self._cfg.tidb_database)
        except MySQLError as exc:
            raise DatabaseError(
                f"Cannot connect to TiDB at {self._cfg.tidb_host}:{self._cfg.tidb_port} — {exc}"
            ) from exc

    def ping(self) -> bool:
        """Return True if the pool can get a live connection."""
        try:
            with self._get_conn() as conn:
                conn.ping(reconnect=True)
            return True
        except Exception:
            return False

    @contextmanager
    def _get_conn(self) -> Generator:
        if self._pool is None:
            raise DatabaseError("Database.connect() has not been called.")
        conn = self._pool.get_connection()
        try:
            yield conn
        finally:
            conn.close()   # returns to pool

    # ── Query Helpers ──────────────────────────────────────────────────────────

    def execute(self, query: str, params: tuple = ()) -> int:
        """
        Execute a write statement (INSERT / UPDATE / DELETE).
        Returns last_insert_id for INSERTs, affected row count otherwise.
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                return cursor.lastrowid or cursor.rowcount
            except MySQLError as exc:
                raise DatabaseError(f"Query failed: {exc}\nSQL: {query}") from exc
            finally:
                cursor.close()

    def executemany(self, query: str, seq_params: list) -> int:
        """Bulk write. Returns affected row count."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.executemany(query, seq_params)
                return cursor.rowcount
            except MySQLError as exc:
                raise DatabaseError(f"Bulk query failed: {exc}") from exc
            finally:
                cursor.close()

    def fetch_all(self, query: str, params: tuple = ()) -> List[dict]:
        """Return all rows as a list of dicts."""
        with self._get_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute(query, params)
                return cursor.fetchall()
            except MySQLError as exc:
                raise DatabaseError(f"Fetch failed: {exc}\nSQL: {query}") from exc
            finally:
                cursor.close()

    def fetch_one(self, query: str, params: tuple = ()) -> Optional[dict]:
        """Return the first row as a dict, or None."""
        with self._get_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute(query, params)
                return cursor.fetchone()
            except MySQLError as exc:
                raise DatabaseError(f"Fetch failed: {exc}\nSQL: {query}") from exc
            finally:
                cursor.close()

    def run_script(self, sql_text: str) -> None:
        """
        Execute a multi-statement SQL script.
        Splits on ';' and executes each non-empty statement individually.
        Ignores blank statements safely.
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                statements = [s.strip() for s in sql_text.split(";") if s.strip()]
                for stmt in statements:
                    cursor.execute(stmt)
            except MySQLError as exc:
                raise DatabaseError(f"Script execution failed: {exc}") from exc
            finally:
                cursor.close()

    def get_config_value(self, key: str, default: str = "") -> str:
        """Convenience: read a value from system_config."""
        row = self.fetch_one(
            "SELECT config_value FROM system_config WHERE config_key = %s", (key,)
        )
        return row["config_value"] if row else default

    def set_config_value(self, key: str, value: str) -> None:
        """Upsert a row in system_config."""
        self.execute(
            "INSERT INTO system_config (config_key, config_value) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)",
            (key, value),
        )


# ── Startup helper ─────────────────────────────────────────────────────────────

def wait_for_connection(db: Database, retries: int = 3, delay: float = 2.0) -> bool:
    """
    Try to reach TiDB up to *retries* times.
    Returns True on success, False after exhausting attempts.
    Used at startup so one dropped packet doesn't crash the app.
    """
    for attempt in range(1, retries + 1):
        try:
            db.connect()
            return True
        except DatabaseError as exc:
            logger.warning("DB connect attempt %d/%d failed: %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(delay)
    return False


# ── Schema bootstrap ────────────────────────────────────────────────────────────

def apply_schema(db: Database) -> None:
    """Run the bundled schema.sql against the connected database."""
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    db.run_script(sql)
    logger.info("Schema applied successfully.")
