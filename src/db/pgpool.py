"""SQLite connection pool for MailKnow MVP."""

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)


class SQLitePool:
    """SQLite connection pool manager.

    SQLite is an embedded database suitable for desktop applications.
    For vector search, we use sqlite-vss extension.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize SQLite pool.

        Args:
            data_dir: Directory to store database files.
                      Defaults to ~/.mailknow/data
        """
        self.data_dir = data_dir or Path.home() / ".mailknow" / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.data_dir / "mailknow.db"
        self._conn: Optional[aiosqlite.Connection] = None
        self._initialized = False

    async def start(self, timeout: float = 30.0) -> None:
        """Open SQLite database.

        Args:
            timeout: Connection timeout (not used for SQLite, kept for API compatibility)
        """
        if self._conn is not None:
            logger.warning("SQLite already connected")
            return

        logger.info(f"Opening SQLite database at {self.db_path}")

        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row

        # Enable foreign keys
        await self._conn.execute("PRAGMA foreign_keys = ON")

        logger.info("SQLite database opened")

    async def stop(self) -> None:
        """Close SQLite database."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("SQLite database closed")

    async def get_connection(self) -> aiosqlite.Connection:
        """Get the database connection.

        Returns:
            aiosqlite.Connection to the database.

        Raises:
            RuntimeError: If database is not opened.
        """
        if not self._conn:
            raise RuntimeError("SQLite not opened. Call start() first.")

        return self._conn

    async def init_schema(self, schema_path: Optional[Path] = None) -> None:
        """Initialize database schema.

        Args:
            schema_path: Path to schema.sql file.
                        Defaults to src/db/schema_sqlite.sql
        """
        if schema_path is None:
            schema_path = Path(__file__).parent / "schema_sqlite.sql"

        schema_sql = schema_path.read_text()

        conn = await self.get_connection()

        # Execute schema (split by semicolon for multiple statements)
        for statement in schema_sql.split(";"):
            statement = statement.strip()
            if statement:
                await conn.execute(statement)

        await conn.commit()
        self._initialized = True
        logger.info("Schema initialized")

    @property
    def is_running(self) -> bool:
        """Check if database is opened."""
        return self._conn is not None

    @property
    def is_initialized(self) -> bool:
        """Check if schema is initialized."""
        return self._initialized


# Alias for compatibility
PGLitePool = SQLitePool


# Global pool instance
_pool: Optional[SQLitePool] = None


async def get_db() -> SQLitePool:
    """Get the global SQLite pool.

    Creates and starts the pool if not already running.
    """
    global _pool

    if _pool is None:
        _pool = SQLitePool()
        await _pool.start()
        await _pool.init_schema()

    return _pool


async def close_db() -> None:
    """Close the global SQLite pool."""
    global _pool

    if _pool:
        await _pool.stop()
        _pool = None
