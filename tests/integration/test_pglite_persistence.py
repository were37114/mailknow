"""Tests for SQLite data persistence across restarts."""

import tempfile
import uuid
from pathlib import Path

import pytest

from db.pgpool import SQLitePool


@pytest.fixture
def data_dir():
    """Create a persistent temp directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.mark.asyncio
async def test_data_persists_after_restart(data_dir: Path):
    """Test that data persists after SQLite close and reopen."""

    # Generate unique test ID
    test_id = str(uuid.uuid4())

    # First session: insert data
    pool1 = SQLitePool(data_dir=data_dir)
    await pool1.start()
    await pool1.init_schema()

    conn1 = await pool1.get_connection()

    page_id = str(uuid.uuid4())
    await conn1.execute("""
        INSERT INTO pages (id, type, content, external_id, metadata)
        VALUES (?, ?, ?, ?, ?)
    """, (page_id, 'email', 'Persistent test email', test_id, '{"test": true}'))
    await conn1.commit()

    # Verify insert
    async with conn1.execute(
        "SELECT COUNT(*) as cnt FROM pages WHERE external_id = ?",
        (test_id,)
    ) as cur:
        result = await cur.fetchone()

    assert result['cnt'] == 1, "Data should be inserted"

    # Close pool
    await pool1.stop()

    # Second session: verify data persists
    pool2 = SQLitePool(data_dir=data_dir)
    await pool2.start()
    # Don't re-init schema - data should already exist

    conn2 = await pool2.get_connection()
    async with conn2.execute(
        "SELECT COUNT(*) as cnt FROM pages WHERE external_id = ?",
        (test_id,)
    ) as cur:
        result = await cur.fetchone()

    assert result['cnt'] == 1, "Data should persist after restart"

    await pool2.stop()


@pytest.mark.asyncio
async def test_500_emails_persist(data_dir: Path):
    """Test that 500 test emails persist correctly."""

    # First session: insert 500 emails
    pool1 = SQLitePool(data_dir=data_dir)
    await pool1.start()
    await pool1.init_schema()

    conn1 = await pool1.get_connection()

    # Batch insert 500 emails
    for i in range(500):
        page_id = str(uuid.uuid4())
        await conn1.execute("""
            INSERT INTO pages (id, type, content, external_id, metadata)
            VALUES (?, ?, ?, ?, ?)
        """, (page_id, 'email', f'Test email content {i}', f'test-{i}@example.com', f'{{"subject": "Test {i}", "index": {i}}}'))

    await conn1.commit()

    await pool1.stop()

    # Second session: verify all 500 persist
    pool2 = SQLitePool(data_dir=data_dir)
    await pool2.start()

    conn2 = await pool2.get_connection()
    async with conn2.execute("SELECT COUNT(*) as cnt FROM pages WHERE type = 'email'") as cur:
        result = await cur.fetchone()

    assert result['cnt'] == 500, f"Expected 500 emails, got {result['cnt']}"

    # Verify random samples
    async with conn2.execute(
        "SELECT content FROM pages WHERE external_id = ?",
        ('test-250@example.com',)
    ) as cur:
        sample = await cur.fetchone()

    assert sample is not None
    assert 'Test email content 250' in sample['content']

    await pool2.stop()
