"""Tests for IMAP connector."""

import pytest

from sync.imap_sync import IMAPConnector, IMAPSyncError
from sync.models import Email, EmailAddress, EmailFlag, IMAPFolder


def test_email_address():
    """Test EmailAddress model."""
    addr1 = EmailAddress(address="test@example.com")
    assert str(addr1) == "test@example.com"

    addr2 = EmailAddress(address="test@example.com", name="Test User")
    assert str(addr2) == "Test User <test@example.com>"


def test_email_model():
    """Test Email model."""
    email = Email(
        message_id="<test123@example.com>",
        subject="Test Subject",
        from_addr=EmailAddress(address="sender@example.com"),
        to_addrs=[EmailAddress(address="recipient@example.com")],
        text_body="Test body",
    )

    assert email.message_id == "<test123@example.com>"
    assert email.subject == "Test Subject"
    assert not email.is_read
    assert not email.is_replied


def test_email_flags():
    """Test Email flags."""
    email = Email(
        message_id="<test@example.com>",
        subject="Test",
        from_addr=EmailAddress(address="test@example.com"),
        flags=[EmailFlag.SEEN, EmailFlag.ANSWERED]
    )

    assert email.is_read
    assert email.is_replied


def test_imap_folder():
    """Test IMAPFolder model."""
    folder = IMAPFolder(
        name="INBOX",
        delimiter="/",
        flags=["\\HasNoChildren"],
        total_messages=100,
        unread_messages=10
    )

    assert folder.name == "INBOX"
    assert folder.total_messages == 100


def test_imap_connector_init():
    """Test IMAPConnector initialization."""
    # Test auto-detection for 163
    connector = IMAPConnector(
        email_address="test@163.com",
        password="testpass"
    )

    assert connector.server == "imap.163.com"
    assert connector.port == 993


def test_imap_connector_unknown_provider():
    """Test IMAPConnector with unknown provider."""
    with pytest.raises(IMAPSyncError) as exc_info:
        IMAPConnector(
            email_address="test@unknown-provider.xyz",
            password="testpass"
        )

    assert "Unknown email provider" in str(exc_info.value)


def test_imap_connector_custom_server():
    """Test IMAPConnector with custom server."""
    connector = IMAPConnector(
        email_address="test@example.com",
        password="testpass",
        server="mail.example.com",
        port=993
    )

    assert connector.server == "mail.example.com"
    assert connector.port == 993


def test_server_detection():
    """Test server auto-detection."""
    test_cases = [
        ("user@gmail.com", "imap.gmail.com", 993),
        ("user@outlook.com", "outlook.office365.com", 993),
        ("user@yahoo.com", "imap.mail.yahoo.com", 993),
        ("user@163.com", "imap.163.com", 993),
        ("user@qq.com", "imap.qq.com", 993),
        ("user@126.com", "imap.126.com", 993),
    ]

    for email_addr, expected_server, expected_port in test_cases:
        connector = IMAPConnector(
            email_address=email_addr,
            password="testpass"
        )
        assert connector.server == expected_server, f"Failed for {email_addr}"
        assert connector.port == expected_port, f"Failed for {email_addr}"


# 注意：以下测试需要真实的邮箱账号，在 CI/CD 中应使用 mock
# 这里只测试初始化逻辑，不测试实际连接


def test_imap_connector_gmail():
    """Test Gmail IMAP configuration."""
    connector = IMAPConnector(
        email_address="test@gmail.com",
        password="app_password"
    )

    assert connector.server == "imap.gmail.com"
    assert connector.port == 993


def test_imap_connector_qq():
    """Test QQ Mail IMAP configuration."""
    connector = IMAPConnector(
        email_address="test@qq.com",
        password="auth_code"
    )

    assert connector.server == "imap.qq.com"
    assert connector.port == 993
