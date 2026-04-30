"""Tests for email parser."""

import pytest
from sync.parser import EmailParser
from sync.models import Email, EmailAddress


def test_parse_simple_email():
    """Test parsing a simple email."""
    raw_email = b"""From: sender@example.com
To: recipient@example.com
Subject: Test Subject
Message-ID: <test123@example.com>
Date: Mon, 1 Jan 2024 12:00:00 +0000

This is a test email body.
"""
    
    email = EmailParser.parse(raw_email)
    
    assert email is not None
    assert email.subject == "Test Subject"
    assert email.from_addr.address == "sender@example.com"
    assert len(email.to_addrs) == 1
    assert email.to_addrs[0].address == "recipient@example.com"
    assert "test email body" in email.text_body


def test_parse_gbk_encoded_subject():
    """Test parsing GBK encoded subject."""
    # GBK encoded "测试主题"
    raw_email = b"""From: sender@example.com
To: recipient@example.com
Subject: =?GBK?B?suLK1M7E19S12A==?=
Message-ID: <test@example.com>

Test body.
"""
    
    email = EmailParser.parse(raw_email)
    
    assert email is not None
    assert "测试" in email.subject or "主题" in email.subject


def test_parse_utf8_encoded_subject():
    """Test parsing UTF-8 encoded subject."""
    raw_email = b"""From: sender@example.com
To: recipient@example.com
Subject: =?UTF-8?B?5rWL6K+V6K+t6K6w?=
Message-ID: <test@example.com>

Test body.
"""
    
    email = EmailParser.parse(raw_email)
    
    assert email is not None
    assert len(email.subject) > 0


def test_parse_multipart_email():
    """Test parsing multipart email."""
    raw_email = b"""From: sender@example.com
To: recipient@example.com
Subject: Multipart Test
Message-ID: <multipart@example.com>
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="boundary123"

--boundary123
Content-Type: text/plain; charset=UTF-8

Plain text body.

--boundary123
Content-Type: text/html; charset=UTF-8

<html><body>HTML body</body></html>

--boundary123--
"""
    
    email = EmailParser.parse(raw_email)
    
    assert email is not None
    assert email.text_body is not None
    assert "Plain text body" in email.text_body
    assert email.html_body is not None
    assert "HTML body" in email.html_body


def test_parse_email_with_cc():
    """Test parsing email with CC."""
    raw_email = b"""From: sender@example.com
To: recipient1@example.com, recipient2@example.com
Cc: cc1@example.com, cc2@example.com
Subject: Test with CC
Message-ID: <test-cc@example.com>

Body text.
"""
    
    email = EmailParser.parse(raw_email)
    
    assert email is not None
    assert len(email.to_addrs) == 2
    assert len(email.cc_addrs) == 2


def test_parse_email_with_chinese_body():
    """Test parsing email with Chinese body (GBK)."""
    # Simple test with UTF-8 Chinese
    raw_email = """From: sender@example.com
To: recipient@example.com
Subject: Test
Message-ID: <test@example.com>
Content-Type: text/plain; charset=UTF-8

这是一封中文邮件。
""".encode('utf-8')
    
    email = EmailParser.parse(raw_email)
    
    assert email is not None
    assert "中文" in email.text_body


def test_parse_email_with_attachment():
    """Test parsing email with attachment."""
    raw_email = b"""From: sender@example.com
To: recipient@example.com
Subject: Test with Attachment
Message-ID: <test-attach@example.com>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="boundary456"

--boundary456
Content-Type: text/plain; charset=UTF-8

Email body with attachment.

--boundary456
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="test.txt"

Attachment content here.

--boundary456--
"""
    
    email = EmailParser.parse(raw_email)
    
    assert email is not None
    assert "Email body" in email.text_body
    assert len(email.attachments) == 1
    assert email.attachments[0]['filename'] == 'test.txt'


def test_parse_address_with_name():
    """Test parsing address with name."""
    raw_email = b"""From: "Sender Name" <sender@example.com>
To: "Recipient Name" <recipient@example.com>
Subject: Test
Message-ID: <test@example.com>

Body.
"""
    
    email = EmailParser.parse(raw_email)
    
    assert email is not None
    assert email.from_addr.name == "Sender Name"
    assert email.from_addr.address == "sender@example.com"


def test_parse_date():
    """Test parsing email date."""
    raw_email = b"""From: sender@example.com
To: recipient@example.com
Subject: Test
Message-ID: <test@example.com>
Date: Mon, 15 Jan 2024 10:30:00 +0800

Body.
"""
    
    email = EmailParser.parse(raw_email)
    
    assert email is not None
    assert email.date is not None
    assert email.date.year == 2024
    assert email.date.month == 1
