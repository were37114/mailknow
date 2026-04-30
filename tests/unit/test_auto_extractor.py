"""Tests for AutoExtractor: automatic entity creation from links."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from core.wiring.auto_extractor import AutoExtractor, EntityCandidate, ExtractionResult
from core.wiring.models import Link, LinkRelation, LinkTier
from db.pgpool import SQLitePool


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
async def extractor(db):
    """Create auto extractor with test database."""
    # Create stub pages for FK constraints
    conn = await db.get_connection()
    now = datetime.now(timezone.utc).isoformat()
    await conn.execute(
        "INSERT OR IGNORE INTO pages (id, type, content, created_at, updated_at) VALUES (?, 'email', ?, ?, ?)",
        ("email:msg1@test.com", "Test", now, now)
    )
    await conn.commit()
    return AutoExtractor(db=db)


def make_link(source, target, relation, tier=LinkTier.TIER_1, metadata=None):
    """Helper to create a Link."""
    return Link(
        source_id=source,
        target_id=target,
        relation=relation,
        tier=tier,
        metadata=metadata or {},
    )


class TestEntityCandidate:
    """Tests for EntityCandidate dataclass."""

    def test_create_candidate(self):
        c = EntityCandidate(
            id="person:test@test.com",
            type="person",
            name="test@test.com",
        )
        assert c.type == "person"
        assert c.attributes == {}

    def test_candidate_with_attrs(self):
        c = EntityCandidate(
            id="person:test@test.com",
            type="person",
            name="test@test.com",
            attributes={"email": "test@test.com", "name": "Test User"},
        )
        assert c.attributes["name"] == "Test User"


class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""

    def test_default_result(self):
        r = ExtractionResult()
        assert r.entities_created == 0
        assert r.entities_updated == 0
        assert r.entities_merged == 0
        assert r.errors == 0


class TestAutoExtractor:
    """Tests for AutoExtractor."""

    @pytest.mark.asyncio
    async def test_extract_person_from_sent_by(self, extractor, db):
        """Test creating person entity from SENT_BY link."""
        links = [
            make_link(
                "email:msg1@test.com",
                "person:zhangsan@company.com",
                LinkRelation.SENT_BY,
                metadata={"name": "张三", "email": "zhangsan@company.com"},
            ),
        ]
        
        result = await extractor.extract_from_links(links)
        assert result.entities_created >= 1
        assert result.errors == 0

    @pytest.mark.asyncio
    async def test_extract_multiple_persons(self, extractor, db):
        """Test creating multiple person entities."""
        links = [
            make_link("email:msg1@test.com", "person:alice@test.com", LinkRelation.SENT_BY),
            make_link("email:msg1@test.com", "person:bob@test.com", LinkRelation.SENT_TO),
            make_link("email:msg1@test.com", "person:charlie@test.com", LinkRelation.CC_TO),
        ]
        
        result = await extractor.extract_from_links(links)
        assert result.entities_created == 3

    @pytest.mark.asyncio
    async def test_extract_url_entity(self, extractor, db):
        """Test creating URL entity from RELATED_TO link."""
        links = [
            make_link("email:msg1@test.com", "url:github.com", LinkRelation.RELATED_TO),
        ]
        
        result = await extractor.extract_from_links(links)
        assert result.entities_created == 1
        
        entity = await extractor.get_entity("url:github.com")
        assert entity is not None
        assert entity["type"] == "url"

    @pytest.mark.asyncio
    async def test_extract_project_entity(self, extractor, db):
        """Test creating project entity from BELONGS_TO link."""
        links = [
            make_link("email:msg1@test.com", "project:MailKnow", LinkRelation.BELONGS_TO),
        ]
        
        result = await extractor.extract_from_links(links)
        assert result.entities_created == 1

    @pytest.mark.asyncio
    async def test_update_existing_entity(self, extractor, db):
        """Test updating attributes of existing entity."""
        links1 = [
            make_link(
                "email:msg1@test.com",
                "person:test@company.com",
                LinkRelation.SENT_BY,
                metadata={"name": "Test User"},
            ),
        ]
        
        result1 = await extractor.extract_from_links(links1)
        assert result1.entities_created == 1
        
        # Second extraction with updated attributes
        links2 = [
            make_link(
                "email:msg1@test.com",
                "person:test@company.com",
                LinkRelation.SENT_BY,
                metadata={"department": "Engineering"},
            ),
        ]
        
        result2 = await extractor.extract_from_links(links2)
        assert result2.entities_updated == 1
        assert result2.entities_created == 0
        
        # Verify merged attributes
        entity = await extractor.get_entity("person:test@company.com")
        assert entity["attributes"]["department"] == "Engineering"

    @pytest.mark.asyncio
    async def test_entity_alignment(self, extractor, db):
        """Test entity alignment for same person."""
        # Create two links with same email (different casing)
        links = [
            make_link("email:msg1@test.com", "person:alice@company.com", LinkRelation.SENT_BY),
            make_link("email:msg1@test.com", "person:alice@company.com", LinkRelation.SENT_TO),
        ]
        
        result = await extractor.extract_from_links(links)
        # Should only create 1 unique entity
        assert result.entities_created == 1

    @pytest.mark.asyncio
    async def test_get_entity(self, extractor, db):
        """Test getting entity by ID."""
        links = [
            make_link(
                "email:msg1@test.com",
                "person:findme@test.com",
                LinkRelation.SENT_BY,
                metadata={"name": "Find Me"},
            ),
        ]
        
        await extractor.extract_from_links(links)
        
        entity = await extractor.get_entity("person:findme@test.com")
        assert entity is not None
        assert entity["name"] == "findme@test.com"
        assert entity["type"] == "person"

    @pytest.mark.asyncio
    async def test_get_nonexistent_entity(self, extractor, db):
        """Test getting nonexistent entity returns None."""
        entity = await extractor.get_entity("person:nonexistent@test.com")
        assert entity is None

    @pytest.mark.asyncio
    async def test_search_entities_by_type(self, extractor, db):
        """Test searching entities by type."""
        links = [
            make_link("email:msg1@test.com", "person:alice@test.com", LinkRelation.SENT_BY),
            make_link("email:msg1@test.com", "person:bob@test.com", LinkRelation.SENT_TO),
            make_link("email:msg1@test.com", "url:github.com", LinkRelation.RELATED_TO),
        ]
        
        await extractor.extract_from_links(links)
        
        persons = await extractor.search_entities(entity_type="person")
        assert len(persons) == 2
        
        urls = await extractor.search_entities(entity_type="url")
        assert len(urls) == 1

    @pytest.mark.asyncio
    async def test_search_entities_by_name(self, extractor, db):
        """Test searching entities by name query."""
        links = [
            make_link("email:msg1@test.com", "person:alice@company.com", LinkRelation.SENT_BY),
            make_link("email:msg1@test.com", "person:bob@company.com", LinkRelation.SENT_TO),
        ]
        
        await extractor.extract_from_links(links)
        
        results = await extractor.search_entities(query="company")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_skip_none_target(self, extractor, db):
        """Test that links with None target are skipped."""
        links = [
            make_link("email:msg1@test.com", None, LinkRelation.REPLY_TO),
        ]
        
        result = await extractor.extract_from_links(links)
        assert result.entities_created == 0

    @pytest.mark.asyncio
    async def test_mentioned_person_extraction(self, extractor, db):
        """Test extracting mentioned person entity."""
        links = [
            make_link(
                "email:msg1@test.com",
                "person:mentioned:张三",
                LinkRelation.MENTIONS,
                tier=LinkTier.TIER_2,
            ),
        ]
        
        result = await extractor.extract_from_links(links)
        assert result.entities_created == 1
        
        entity = await extractor.get_entity("person:mentioned:张三")
        assert entity is not None
        assert entity["name"] == "张三"

    @pytest.mark.asyncio
    async def test_empty_links(self, extractor, db):
        """Test extraction with empty links list."""
        result = await extractor.extract_from_links([])
        assert result.entities_created == 0
        assert result.entities_updated == 0

    @pytest.mark.asyncio
    async def test_extract_name_from_mentioned(self, extractor, db):
        """Test name extraction from mentioned: prefix."""
        name = extractor._extract_name("person:mentioned:王五")
        assert name == "王五"

    @pytest.mark.asyncio
    async def test_extract_name_from_email(self, extractor, db):
        """Test name extraction from email-based ID."""
        name = extractor._extract_name("person:alice@company.com")
        assert name == "alice@company.com"
