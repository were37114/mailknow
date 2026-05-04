"""Tests for Tier 1 link extractor."""

from datetime import datetime

import pytest

from core.wiring import Link, LinkRelation, LinkTier, Tier1Extractor
from sync.models import Email, EmailAddress


@pytest.fixture
def extractor():
    """Create a Tier 1 extractor."""
    return Tier1Extractor()


@pytest.fixture
def simple_email():
    """Create a simple email."""
    return Email(
        message_id="<test123@example.com>",
        subject="Test Subject",
        from_addr=EmailAddress("sender@example.com", "Sender Name"),
        to_addrs=[EmailAddress("recipient@example.com", "Recipient Name")],
        text_body="Test content",
        date=datetime(2024, 1, 1, 12, 0)
    )


@pytest.fixture
def reply_email():
    """Create a reply email."""
    return Email(
        message_id="<reply456@example.com>",
        subject="Re: Test Subject",
        from_addr=EmailAddress("recipient@example.com", "Recipient Name"),
        to_addrs=[EmailAddress("sender@example.com", "Sender Name")],
        in_reply_to="<test123@example.com>",
        references=["<test123@example.com>", "<parent@example.com>"],
        text_body="Reply content",
        date=datetime(2024, 1, 1, 13, 0)
    )


@pytest.fixture
def cc_email():
    """Create an email with CC."""
    return Email(
        message_id="<cc789@example.com>",
        subject="CC Test",
        from_addr=EmailAddress("sender@example.com", "Sender"),
        to_addrs=[EmailAddress("recipient@example.com", "Recipient")],
        cc_addrs=[
            EmailAddress("cc1@example.com", "CC One"),
            EmailAddress("cc2@example.com", "CC Two")
        ],
        text_body="CC content",
        date=datetime(2024, 1, 1, 14, 0)
    )


def test_extract_simple_email(extractor: Tier1Extractor, simple_email: Email):
    """Test extracting links from simple email."""
    links = extractor.extract(simple_email)

    # Should have 2 links: sent_by + sent_to
    assert len(links) == 2

    # Check sent_by link
    sent_by = next(l for l in links if l.relation == LinkRelation.SENT_BY)
    assert sent_by.source_id == "email:test123@example.com"
    assert sent_by.target_id == "person:sender@example.com"
    assert sent_by.tier == LinkTier.TIER_1

    # Check sent_to link
    sent_to = next(l for l in links if l.relation == LinkRelation.SENT_TO)
    assert sent_to.source_id == "email:test123@example.com"
    assert sent_to.target_id == "person:recipient@example.com"


def test_extract_reply_email(extractor: Tier1Extractor, reply_email: Email):
    """Test extracting links from reply email."""
    links = extractor.extract(reply_email)

    # Should have 5 links: reply_to + 2 references + sent_by + sent_to
    assert len(links) == 5

    # Check reply_to link
    reply_to = next(l for l in links if l.relation == LinkRelation.REPLY_TO)
    assert reply_to.source_id == "email:reply456@example.com"
    assert reply_to.target_id == "<test123@example.com>"
    assert reply_to.weight == 1.0

    # Check references link
    references = [l for l in links if l.relation == LinkRelation.REFERENCES]
    assert len(references) == 2
    assert references[0].weight == 0.8  # References are weaker


def test_extract_cc_email(extractor: Tier1Extractor, cc_email: Email):
    """Test extracting links from email with CC."""
    links = extractor.extract(cc_email)

    # Should have 4 links: sent_by + sent_to + 2 cc_to
    assert len(links) == 4

    # Check CC links
    cc_links = [l for l in links if l.relation == LinkRelation.CC_TO]
    assert len(cc_links) == 2

    # CC should have lower weight
    for cc_link in cc_links:
        assert cc_link.weight == 0.7


def test_email_id_generation(extractor: Tier1Extractor):
    """Test email ID generation."""
    # With Message-ID
    email1 = Email(
        message_id="<msg123@example.com>",
        subject="Test",
        from_addr=EmailAddress("test@example.com"),
        to_addrs=[EmailAddress("to@example.com")]
    )
    assert extractor._get_email_id(email1) == "email:msg123@example.com"

    # Without Message-ID (should generate hash)
    email2 = Email(
        message_id="",
        subject="Test Subject",
        from_addr=EmailAddress("test@example.com"),
        to_addrs=[EmailAddress("to@example.com")],
        date=datetime(2024, 1, 1)
    )
    email_id = extractor._get_email_id(email2)
    assert email_id.startswith("email:generated:")
    assert len(email_id) == len("email:generated:") + 16


def test_person_id_generation(extractor: Tier1Extractor):
    """Test person entity ID generation."""
    # Should normalize email address
    id1 = extractor._get_person_id("Test@Example.COM")
    assert id1 == "person:test@example.com"

    id2 = extractor._get_person_id("  user@example.com  ")
    assert id2 == "person:user@example.com"


def test_link_to_dict(extractor: Tier1Extractor, simple_email: Email):
    """Test Link.to_dict() method."""
    links = extractor.extract(simple_email)

    for link in links:
        link_dict = link.to_dict()

        assert "id" in link_dict
        assert "source_id" in link_dict
        assert "target_id" in link_dict
        assert "relation" in link_dict
        assert "tier" in link_dict
        assert "weight" in link_dict
        assert "metadata" in link_dict

        # Verify ID format
        assert link_dict["id"] == link.id


def test_link_id_uniqueness(extractor: Tier1Extractor, simple_email: Email):
    """Test that link IDs are unique."""
    links = extractor.extract(simple_email)
    link_ids = [link.id for link in links]

    # All IDs should be unique
    assert len(link_ids) == len(set(link_ids))


def test_empty_email(extractor: Tier1Extractor):
    """Test extracting from minimal email."""
    email = Email(
        message_id="<empty@example.com>",
        subject="",
        from_addr=EmailAddress("sender@example.com"),
        to_addrs=[]
    )

    links = extractor.extract(email)

    # Should still have sent_by link
    assert len(links) == 1
    assert links[0].relation == LinkRelation.SENT_BY
