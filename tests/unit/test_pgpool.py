"""Tests for SQLite connection pool."""

import pytest
from pathlib import Path
import tempfile
import uuid

from db.pgpool import SQLitePool


@pytest.fixture
async def pool():
    """Create a test SQLite pool."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool = SQLitePool(data_dir=Path(tmpdir))
        await pool.start()
        await pool.init_schema()
        
        yield pool
        
        await pool.stop()


@pytest.mark.asyncio
async def test_pool_starts(pool: SQLitePool):
    """Test that SQLite pool starts successfully."""
    assert pool.is_running
    assert pool.is_initialized


@pytest.mark.asyncio
async def test_pool_get_connection(pool: SQLitePool):
    """Test getting a connection."""
    conn = await pool.get_connection()
    
    assert conn is not None


@pytest.mark.asyncio
async def test_schema_tables_exist(pool: SQLitePool):
    """Test that schema tables are created."""
    conn = await pool.get_connection()
    
    async with conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
    """) as cur:
        tables = {row['name'] for row in await cur.fetchall()}
    
    assert 'pages' in tables
    assert 'links' in tables
    assert 'entities' in tables


@pytest.mark.asyncio
async def test_insert_page(pool: SQLitePool):
    """Test inserting a page."""
    conn = await pool.get_connection()
    
    page_id = str(uuid.uuid4())
    await conn.execute("""
        INSERT INTO pages (id, type, content, metadata, gate_class)
        VALUES (?, ?, ?, ?, ?)
    """, (page_id, 'email', 'Test email content', '{"subject": "Test"}', 'routine'))
    
    await conn.commit()
    
    assert page_id is not None


@pytest.mark.asyncio
async def test_insert_link(pool: SQLitePool):
    """Test inserting a link."""
    conn = await pool.get_connection()
    
    # Create two pages first
    page1_id = str(uuid.uuid4())
    page2_id = str(uuid.uuid4())
    
    await conn.execute("""
        INSERT INTO pages (id, type, content)
        VALUES (?, ?, ?)
    """, (page1_id, 'email', 'Email 1'))
    
    await conn.execute("""
        INSERT INTO pages (id, type, content)
        VALUES (?, ?, ?)
    """, (page2_id, 'email', 'Email 2'))
    
    # Create link
    link_id = str(uuid.uuid4())
    await conn.execute("""
        INSERT INTO links (id, source_id, target_id, relation)
        VALUES (?, ?, ?, ?)
    """, (link_id, page1_id, page2_id, 'replied_to'))
    
    await conn.commit()
    
    assert link_id is not None


@pytest.mark.asyncio
async def test_insert_entity(pool: SQLitePool):
    """Test inserting an entity."""
    conn = await pool.get_connection()
    
    entity_id = str(uuid.uuid4())
    await conn.execute("""
        INSERT INTO entities (id, type, name)
        VALUES (?, ?, ?)
    """, (entity_id, 'person', '张三'))
    
    await conn.commit()
    
    assert entity_id is not None
