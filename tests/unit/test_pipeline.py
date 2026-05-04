"""Tests for EmailPipeline: new email → Gate → wiring → store."""

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.gate.classifier import EmailInfo, GateClassifier
from core.gate.models import GateClass, GateResult
from core.pipeline import EmailPipeline, PipelineResult, PipelineStats
from core.wiring.tier1_extractor import Tier1Extractor
from core.wiring.tier2_extractor import Tier2Extractor
from db.pgpool import SQLitePool
from sync.models import Email, EmailAddress, EmailFlag


@pytest.fixture
async def db():
    """Create temporary database for tests."""
    with tempfile.TemporaryDirectory() as d:
        pool = SQLitePool(data_dir=Path(d))
        await pool.start()
        await pool.init_schema()
        yield pool
        await pool.stop()


@pytest.fixture
def pipeline(db):
    """Create pipeline with test database."""
    return EmailPipeline(db=db)


@pytest.fixture
def sample_email():
    """Create a sample email."""
    return Email(
        message_id="<test123@example.com>",
        subject="项目进度讨论",
        from_addr=EmailAddress(name="张三", address="zhangsan@company.com"),
        to_addrs=[EmailAddress(name="我", address="me@company.com")],
        cc_addrs=[],
        text_body="我们讨论一下项目的下一步计划",
        date=datetime.now(timezone.utc),
        flags=[],
        in_reply_to=None,
        references=[],
    )


@pytest.fixture
def urgent_email():
    """Create an urgent email."""
    return Email(
        message_id="<urgent@example.com>",
        subject="紧急：服务器宕机",
        from_addr=EmailAddress(name="运维", address="ops@company.com"),
        to_addrs=[EmailAddress(name="我", address="me@company.com")],
        text_body="服务器紧急告警，请立即处理",
        date=datetime.now(timezone.utc),
        flags=[EmailFlag.FLAGGED],
    )


@pytest.fixture
def spam_email():
    """Create a spam email."""
    return Email(
        message_id="<spam@example.com>",
        subject="恭喜中奖！免费领取",
        from_addr=EmailAddress(name="推广", address="promo@spam.com"),
        to_addrs=[EmailAddress(name="我", address="me@company.com")],
        text_body="点击领取你的大奖 unsub",
        date=datetime.now(timezone.utc),
    )


@pytest.fixture
def reply_email():
    """Create a reply email with references."""
    return Email(
        message_id="<reply456@example.com>",
        subject="Re: 项目进度讨论",
        from_addr=EmailAddress(name="李四", address="lisi@company.com"),
        to_addrs=[EmailAddress(name="我", address="me@company.com")],
        cc_addrs=[EmailAddress(name="王五", address="wangwu@company.com")],
        text_body="同意，我们下周开始执行",
        date=datetime.now(timezone.utc),
        in_reply_to="<test123@example.com>",
        references=["<test123@example.com>", "<parent@example.com>"],
    )


class TestPipelineResult:
    """Tests for PipelineResult."""

    def test_create_result(self):
        result = PipelineResult(
            email_id="email:abc",
            gate_class="important",
            gate_confidence=0.9,
            links_extracted=3,
            entities_created=1,
            processing_time_ms=15.5,
        )
        assert result.gate_class == "important"
        assert result.links_extracted == 3
        assert result.error is None


class TestPipelineStats:
    """Tests for PipelineStats."""

    def test_empty_stats(self):
        stats = PipelineStats()
        assert stats.total_processed == 0
        assert stats.avg_time_ms == 0.0

    def test_avg_time(self):
        stats = PipelineStats(total_processed=2, total_time_ms=200.0)
        assert stats.avg_time_ms == 100.0


class TestEmailPipeline:
    """Tests for EmailPipeline."""

    @pytest.mark.asyncio
    async def test_process_routine_email(self, pipeline, sample_email, db):
        """Test processing a routine email."""
        result = await pipeline.process_email(
            email=sample_email,
            account_id="acc1",
            folder="INBOX",
            uid=100,
        )

        assert result.error is None
        assert result.gate_class in ("routine", "important")  # Depends on to_me rule
        assert result.gate_confidence > 0
        assert result.processing_time_ms > 0

    @pytest.mark.asyncio
    async def test_process_urgent_email(self, pipeline, urgent_email, db):
        """Test processing an urgent email."""
        result = await pipeline.process_email(
            email=urgent_email,
            account_id="acc1",
            folder="INBOX",
            uid=101,
        )

        assert result.error is None
        assert result.gate_class == "urgent"
        assert result.gate_confidence > 0.5

    @pytest.mark.asyncio
    async def test_process_spam_email(self, pipeline, spam_email, db):
        """Test processing a spam email - should skip Tier2."""
        result = await pipeline.process_email(
            email=spam_email,
            account_id="acc1",
            folder="INBOX",
            uid=102,
        )

        assert result.error is None
        assert result.gate_class == "spam"

    @pytest.mark.asyncio
    async def test_process_reply_email_with_links(self, pipeline, reply_email, db):
        """Test processing reply email extracts Tier1 links."""
        result = await pipeline.process_email(
            email=reply_email,
            account_id="acc1",
            folder="INBOX",
            uid=103,
        )

        assert result.error is None
        # Should have extracted links from In-Reply-To and References
        assert result.links_extracted >= 2  # reply_to + references + sent_by + sent_to + cc_to

    @pytest.mark.asyncio
    async def test_email_stored_in_pages(self, pipeline, sample_email, db):
        """Test email is stored in pages table."""
        await pipeline.process_email(
            email=sample_email,
            account_id="acc1",
            folder="INBOX",
            uid=200,
        )

        conn = await db.get_connection()
        cursor = await conn.execute("SELECT COUNT(*) FROM pages WHERE type = 'email'")
        count = (await cursor.fetchone())[0]
        assert count >= 1

    @pytest.mark.asyncio
    async def test_links_stored_in_links(self, pipeline, reply_email, db):
        """Test links are stored in links table."""
        await pipeline.process_email(
            email=reply_email,
            account_id="acc1",
            folder="INBOX",
            uid=300,
        )

        conn = await db.get_connection()
        cursor = await conn.execute("SELECT COUNT(*) FROM links")
        count = (await cursor.fetchone())[0]
        assert count >= 2

    @pytest.mark.asyncio
    async def test_entities_stored(self, pipeline, reply_email, db):
        """Test entities are created from links."""
        await pipeline.process_email(
            email=reply_email,
            account_id="acc1",
            folder="INBOX",
            uid=400,
        )

        conn = await db.get_connection()
        cursor = await conn.execute("SELECT COUNT(*) FROM entities")
        count = (await cursor.fetchone())[0]
        assert count >= 1

    @pytest.mark.asyncio
    async def test_dedup_same_email(self, pipeline, sample_email, db):
        """Test deduplication - same email stored only once."""
        r1 = await pipeline.process_email(
            email=sample_email,
            account_id="acc1",
            folder="INBOX",
            uid=500,
        )
        r2 = await pipeline.process_email(
            email=sample_email,
            account_id="acc1",
            folder="INBOX",
            uid=500,
        )

        conn = await db.get_connection()
        cursor = await conn.execute("SELECT COUNT(*) FROM pages WHERE type = 'email'")
        count = (await cursor.fetchone())[0]
        assert count == 1  # Only one copy

    @pytest.mark.asyncio
    async def test_pipeline_stats(self, pipeline, sample_email, db):
        """Test pipeline statistics tracking."""
        await pipeline.process_email(
            email=sample_email,
            account_id="acc1",
            folder="INBOX",
            uid=600,
        )

        stats = pipeline.stats
        assert stats.total_processed == 1
        assert stats.total_time_ms > 0

    @pytest.mark.asyncio
    async def test_process_batch(self, pipeline, db):
        """Test processing a batch of emails."""
        emails = [
            Email(
                message_id=f"<batch{i}@test.com>",
                subject=f"Batch email {i}",
                from_addr=EmailAddress(name=f"Sender {i}", address=f"sender{i}@test.com"),
                to_addrs=[EmailAddress(name="Me", address="me@test.com")],
                text_body=f"Content {i}",
                date=datetime.now(timezone.utc),
            )
            for i in range(5)
        ]

        results = await pipeline.process_batch(
            emails=emails,
            account_id="acc1",
            folder="INBOX",
            start_uid=700,
        )

        assert len(results) == 5
        assert all(r.error is None for r in results)
        assert pipeline.stats.total_processed == 5

    @pytest.mark.asyncio
    async def test_reset_stats(self, pipeline, sample_email, db):
        """Test resetting pipeline statistics."""
        await pipeline.process_email(
            email=sample_email,
            account_id="acc1",
            folder="INBOX",
            uid=800,
        )

        assert pipeline.stats.total_processed == 1
        pipeline.reset_stats()
        assert pipeline.stats.total_processed == 0

    @pytest.mark.asyncio
    async def test_gate_class_stored_correctly(self, pipeline, urgent_email, db):
        """Test gate class is correctly stored in pages."""
        await pipeline.process_email(
            email=urgent_email,
            account_id="acc1",
            folder="INBOX",
            uid=900,
        )

        conn = await db.get_connection()
        cursor = await conn.execute(
            "SELECT gate_class, gate_score FROM pages WHERE type = 'email' LIMIT 1"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "urgent"
