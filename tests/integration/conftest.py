"""Pytest configuration for integration tests."""

import pytest


# Register custom markers
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires real credentials)"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
