"""Tests for W13: IPC auth + Integrity checker + NL→SQL integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.auth import AuthConfig, IPCAuth


class TestIPCAuth:
    """Test IPC-based authentication."""

    @pytest.fixture
    def auth(self):
        return IPCAuth(enabled=True)

    def test_token_generated(self, auth):
        """Token should be auto-generated on init."""
        assert len(auth.token) == 64  # 32 bytes hex = 64 chars

    def test_validate_valid_token(self, auth):
        """Valid token should pass validation."""
        assert auth.validate_token(auth.token) is True

    def test_validate_invalid_token(self, auth):
        """Invalid token should fail."""
        assert auth.validate_token("invalid-token") is False

    def test_validate_empty_token(self, auth):
        """Empty token should fail."""
        assert auth.validate_token("") is False

    def test_validate_disabled_auth(self):
        """When auth disabled, all tokens pass."""
        auth = IPCAuth(enabled=False)
        assert auth.validate_token("anything") is True

    def test_rotate_token(self, auth):
        """Token rotation should change the token."""
        old_token = auth.token
        new_token = auth.rotate_token()
        assert new_token != old_token
        assert auth.validate_token(new_token) is True
        assert auth.validate_token(old_token) is False

    def test_get_config(self, auth):
        """Config should not expose token."""
        config = auth.get_config()
        assert isinstance(config, AuthConfig)
        assert config.token == ""  # Security: no token in config
        assert config.enabled is True

    def test_get_stats(self, auth):
        """Stats should track requests."""
        auth.validate_token(auth.token)
        auth.validate_token("invalid")
        stats = auth.get_stats()
        assert stats["total_requests"] == 2
        assert stats["failed_auth"] == 1

    def test_socket_path(self, auth):
        """Socket path should be set."""
        assert len(auth.socket_path) > 0


class TestIntegrityChecker:
    """Test database integrity checking."""

    @pytest.mark.asyncio
    async def test_check_without_db(self):
        """Check without database should return empty report."""
        from db.integrity import IntegrityChecker, IntegrityReport
        checker = IntegrityChecker(db=None)
        report = await checker.check()
        assert isinstance(report, IntegrityReport)
        # No DB means no issues found (can't check)
        assert len(report.issues) == 0

    def test_integrity_issue_types(self):
        """All issue types should be defined."""
        from db.integrity import IntegrityIssueType
        expected = [
            "ORPHAN_PAGE", "BROKEN_LINK_SOURCE", "BROKEN_LINK_TARGET",
            "STALE_ENTITY", "MISSING_ENTITY_PAGE", "DUPLICATE_ENTITY",
            "EMPTY_METADATA",
        ]
        for name in expected:
            assert hasattr(IntegrityIssueType, name)

    def test_integrity_report_model(self):
        """Test IntegrityReport data model."""
        from db.integrity import IntegrityIssue, IntegrityIssueType, IntegrityReport
        report = IntegrityReport(total_pages=100, total_links=500, total_entities=50)
        assert report.total_pages == 100
        assert not report.has_critical

    def test_integrity_report_with_critical(self):
        """Report with critical issue."""
        from db.integrity import IntegrityIssue, IntegrityIssueType, IntegrityReport
        report = IntegrityReport()
        report.issues.append(IntegrityIssue(
            issue_type=IntegrityIssueType.BROKEN_LINK_SOURCE,
            severity="critical",
            description="Link source missing",
        ))
        assert report.has_critical
