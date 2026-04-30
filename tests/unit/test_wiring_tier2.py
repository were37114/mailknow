"""Tests for Tier 2 link extractor."""

import pytest
from datetime import datetime

from core.wiring import Tier2Extractor, Link, LinkRelation, LinkTier
from sync.models import Email, EmailAddress


@pytest.fixture
def extractor():
    """Create a Tier 2 extractor."""
    return Tier2Extractor()


@pytest.fixture
def email_with_mentions():
    """Create an email with @mentions."""
    return Email(
        message_id="<mention@example.com>",
        subject="Project Discussion",
        from_addr=EmailAddress("sender@example.com", "Sender"),
        to_addrs=[EmailAddress("recipient@example.com", "Recipient")],
        text_body="请 @张三 和 @李四 确认一下项目进度",
        date=datetime(2024, 1, 1, 12, 0)
    )


@pytest.fixture
def email_with_urls():
    """Create an email with URLs."""
    return Email(
        message_id="<url@example.com>",
        subject="Links",
        from_addr=EmailAddress("sender@example.com", "Sender"),
        to_addrs=[EmailAddress("recipient@example.com", "Recipient")],
        text_body="参考文档：https://docs.example.com/api 和 http://blog.example.com/post",
        date=datetime(2024, 1, 1, 13, 0)
    )


@pytest.fixture
def email_with_projects():
    """Create an email with project names."""
    return Email(
        message_id="<project@example.com>",
        subject="Project Update",
        from_addr=EmailAddress("sender@example.com", "Sender"),
        to_addrs=[EmailAddress("recipient@example.com", "Recipient")],
        text_body="#MailKnow 项目进展顺利，#GBrain 架构已完成",
        date=datetime(2024, 1, 1, 14, 0)
    )


@pytest.fixture
def email_with_emails():
    """Create an email with email addresses in content."""
    return Email(
        message_id="<emails@example.com>",
        subject="Contacts",
        from_addr=EmailAddress("sender@example.com", "Sender"),
        to_addrs=[EmailAddress("recipient@example.com", "Recipient")],
        text_body="请联系 support@example.com 或 sales@example.com",
        date=datetime(2024, 1, 1, 15, 0)
    )


@pytest.fixture
def complex_email():
    """Create an email with multiple types of links."""
    return Email(
        message_id="<complex@example.com>",
        subject="Complex Email",
        from_addr=EmailAddress("pm@example.com", "PM"),
        to_addrs=[EmailAddress("dev@example.com", "Dev")],
        text_body="""
        #MailKnow 项目更新：
        
        请 @张三 审核代码。
        参考：https://github.com/example/mailknow
        
        联系方式：contact@example.com
        """,
        date=datetime(2024, 1, 1, 16, 0)
    )


def test_extract_mentions(extractor: Tier2Extractor, email_with_mentions: Email):
    """Test extracting @mentions."""
    links = extractor.extract(email_with_mentions)
    
    # Should have 2 mention links
    mentions = [l for l in links if l.relation == LinkRelation.MENTIONS]
    assert len(mentions) == 2
    
    # Check mention details
    names = [l.metadata["name"] for l in mentions]
    assert "张三" in names
    assert "李四" in names
    
    # Check weight
    for mention in mentions:
        assert mention.weight == 0.6
        assert mention.tier == LinkTier.TIER_2


def test_extract_urls(extractor: Tier2Extractor, email_with_urls: Email):
    """Test extracting URLs."""
    links = extractor.extract(email_with_urls)
    
    # Should have 2 URL links
    url_links = [l for l in links if l.metadata.get("type") == "url"]
    assert len(url_links) == 2
    
    # Check domains
    domains = [l.metadata["domain"] for l in url_links]
    assert "docs.example.com" in domains
    assert "blog.example.com" in domains


def test_extract_projects(extractor: Tier2Extractor, email_with_projects: Email):
    """Test extracting project names."""
    links = extractor.extract(email_with_projects)
    
    # Should have 2 project links
    project_links = [l for l in links if l.relation == LinkRelation.BELONGS_TO]
    assert len(project_links) == 2
    
    # Check project names
    names = [l.metadata["name"] for l in project_links]
    assert "MailKnow" in names
    assert "GBrain" in names


def test_extract_emails(extractor: Tier2Extractor, email_with_emails: Email):
    """Test extracting email addresses from content."""
    links = extractor.extract(email_with_emails)
    
    # Should have 2 email links (not counting To/From)
    email_links = [
        l for l in links 
        if l.metadata.get("type") == "email_in_content"
    ]
    assert len(email_links) == 2
    
    # Check emails
    emails = [l.metadata["email"] for l in email_links]
    assert "support@example.com" in emails
    assert "sales@example.com" in emails


def test_skip_known_addresses(extractor: Tier2Extractor):
    """Test that addresses in To/Cc are not extracted again."""
    email = Email(
        message_id="<skip@example.com>",
        subject="Test",
        from_addr=EmailAddress("sender@example.com", "Sender"),
        to_addrs=[EmailAddress("recipient@example.com", "Recipient")],
        text_body="发送给 recipient@example.com 的邮件",
        date=datetime(2024, 1, 1)
    )
    
    links = extractor.extract(email)
    
    # Should not have duplicate link for recipient
    email_links = [
        l for l in links 
        if l.metadata.get("type") == "email_in_content"
    ]
    assert len(email_links) == 0


def test_complex_email(extractor: Tier2Extractor, complex_email: Email):
    """Test extracting from complex email."""
    links = extractor.extract(complex_email)
    
    # Should have multiple types of links
    assert len(links) > 0
    
    # Check different types exist
    relations = [l.relation for l in links]
    assert LinkRelation.MENTIONS in relations
    assert LinkRelation.BELONGS_TO in relations
    
    # Check all are Tier 2
    for link in links:
        assert link.tier == LinkTier.TIER_2


def test_deduplication(extractor: Tier2Extractor):
    """Test that duplicate links are removed."""
    email = Email(
        message_id="<dup@example.com>",
        subject="Test",
        from_addr=EmailAddress("sender@example.com", "Sender"),
        to_addrs=[EmailAddress("recipient@example.com", "Recipient")],
        text_body="联系 @张三 或 @张三 都可以",
        date=datetime(2024, 1, 1)
    )
    
    links = extractor.extract(email)
    
    # Should only have 1 mention link for 张三
    mentions = [l for l in links if l.relation == LinkRelation.MENTIONS]
    assert len(mentions) == 1


def test_empty_content(extractor: Tier2Extractor):
    """Test extracting from empty content."""
    email = Email(
        message_id="<empty@example.com>",
        subject="Test",
        from_addr=EmailAddress("sender@example.com", "Sender"),
        to_addrs=[EmailAddress("recipient@example.com", "Recipient")],
        text_body="",
        date=datetime(2024, 1, 1)
    )
    
    links = extractor.extract(email)
    
    # Should have no links
    assert len(links) == 0


def test_html_content(extractor: Tier2Extractor):
    """Test extracting from HTML content."""
    email = Email(
        message_id="<html@example.com>",
        subject="Test",
        from_addr=EmailAddress("sender@example.com", "Sender"),
        to_addrs=[EmailAddress("recipient@example.com", "Recipient")],
        html_body="<p>联系 @张三 或访问 <a href='https://example.com'>网站</a></p>",
        date=datetime(2024, 1, 1)
    )
    
    links = extractor.extract(email)
    
    # Should extract from HTML
    assert len(links) > 0
    
    # Should have mention
    mentions = [l for l in links if l.relation == LinkRelation.MENTIONS]
    assert len(mentions) > 0
