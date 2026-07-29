"""
tests/conftest.py
Shared fixtures for all test modules.
Uses an in-memory SQLite-compatible mock via MagicMock for DB isolation,
and provides a real Database instance wired to an in-process test schema
when TiDB is available (controlled by MERIDIAN_TEST_DB env var).
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch
from config import AppConfig


@pytest.fixture
def cfg() -> AppConfig:
    return AppConfig(
        tidb_host="localhost",
        tidb_port=4000,
        tidb_user="test",
        tidb_password="test",
        tidb_database="meridian_test",
        tidb_use_tls=False,
        resend_api_key="re_testkey123456",
        default_from_name="Test Sender",
        default_from_email="sender@example.com",
        api_secret_token="test-token-1234567890abcdef",
        api_host="127.0.0.1",
        api_port=8765,
    )


@pytest.fixture
def mock_db():
    """A MagicMock that mimics the Database interface."""
    db = MagicMock()
    db.fetch_one.return_value = None
    db.fetch_all.return_value = []
    db.execute.return_value = 1
    db.executemany.return_value = 0
    db.get_config_value.return_value = "200"
    db.ping.return_value = True
    return db
