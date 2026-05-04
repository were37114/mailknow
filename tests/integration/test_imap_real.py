"""IMAP integration tests with real servers.

Run with: pytest tests/integration/test_imap_real.py -m integration -v
"""

import os

import pytest

# Skip all tests if credentials not available
pytestmark = pytest.mark.skipif(
    not os.environ.get("MAILKNOW_TEST_EMAIL"),
    reason="MAILKNOW_TEST_EMAIL not set"
)


class TestIMAP163Real:
    """Test real IMAP connection for 163.com mailboxes."""

    @pytest.fixture
    def connector(self):
        """Create IMAP connector with test credentials."""
        from sync.imap_163 import IMAP163Connector

        email_addr = os.environ["MAILKNOW_TEST_EMAIL"]
        password = os.environ["MAILKNOW_TEST_PASSWORD"]

        return IMAP163Connector(
            email_address=email_addr,
            password=password
        )

    @pytest.mark.integration
    def test_connect_and_disconnect(self, connector):
        """Test basic connection and disconnection."""
        connector.connect()
        assert connector._client is not None

        connector.disconnect()
        assert connector._client is None

    @pytest.mark.integration
    def test_list_folders(self, connector):
        """Test listing IMAP folders."""
        connector.connect()
        try:
            folders = connector.list_folders()
            assert len(folders) > 0

            print(f"\nFound {len(folders)} folders:")
            for flags, name in folders[:10]:
                print(f"  - {name}")

        finally:
            connector.disconnect()

    @pytest.mark.integration
    def test_select_inbox(self, connector):
        """Test selecting INBOX folder."""
        connector.connect()
        try:
            count = connector.select_folder("INBOX")
            assert count >= 0
            print(f"\nINBOX: {count} messages")

        finally:
            connector.disconnect()

    @pytest.mark.integration
    def test_search_emails(self, connector):
        """Test searching emails."""
        connector.connect()
        try:
            connector.select_folder("INBOX")
            nums = connector.search("ALL")

            assert isinstance(nums, list)
            print(f"\nFound {len(nums)} emails")

            if nums:
                print(f"First 5 message numbers: {nums[:5]}")

        finally:
            connector.disconnect()

    @pytest.mark.integration
    def test_fetch_headers(self, connector):
        """Test fetching email headers."""
        connector.connect()
        try:
            connector.select_folder("INBOX")
            nums = connector.search("ALL")

            if not nums:
                pytest.skip("No messages in INBOX")

            headers = connector.fetch_headers(nums[0])
            assert len(headers) > 0

            print(f"\nHeaders for message {nums[0]}:")
            for key in ["Subject", "From", "Date"]:
                if key in headers:
                    print(f"  {key}: {headers[key][:50]}")

        finally:
            connector.disconnect()

    @pytest.mark.integration
    def test_context_manager(self, connector):
        """Test context manager usage."""
        with connector.connection() as conn:
            folders = conn.list_folders()
            assert len(folders) > 0

        # After context, should be disconnected
        assert connector._client is None

    @pytest.mark.integration
    def test_connection_resilience(self, connector):
        """Test connection recovery after disconnect."""
        connector.connect()
        assert connector._client is not None

        connector.disconnect()
        assert connector._client is None

        # Reconnect
        connector.connect()
        assert connector._client is not None

        folders = connector.list_folders()
        assert len(folders) > 0

        connector.disconnect()


class TestIMAPServerDetection:
    """Test automatic IMAP server detection."""

    @pytest.mark.integration
    def test_detect_163(self):
        """Test 163 server detection."""
        from sync.imap_163 import IMAP163Connector

        connector = IMAP163Connector(
            email_address="test@163.com",
            password="dummy"
        )
        assert connector.server == "imap.163.com"
        assert connector.port == 993

    @pytest.mark.integration
    def test_detect_126(self):
        """Test 126 server detection."""
        from sync.imap_163 import IMAP163Connector

        connector = IMAP163Connector(
            email_address="test@126.com",
            password="dummy"
        )
        assert connector.server == "imap.126.com"
        assert connector.port == 993

    @pytest.mark.integration
    def test_detect_qq(self):
        """Test QQ server detection."""
        from sync.imap_163 import IMAP163Connector

        connector = IMAP163Connector(
            email_address="test@qq.com",
            password="dummy"
        )
        assert connector.server == "imap.qq.com"
        assert connector.port == 993

    @pytest.mark.integration
    def test_custom_server(self):
        """Test custom server override."""
        from sync.imap_163 import IMAP163Connector

        connector = IMAP163Connector(
            email_address="test@custom.com",
            password="dummy",
            server="mail.custom.com",
            port=143
        )
        assert connector.server == "mail.custom.com"
        assert connector.port == 143


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
