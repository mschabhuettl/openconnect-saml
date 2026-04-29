"""Shared pytest fixtures for openconnect-saml tests."""

from __future__ import annotations

import os

import pytest

os.environ["COVERAGE_PROCESS_START"] = ".coveragerc"


@pytest.fixture(autouse=False)
def _reset_structlog_context():
    """Placeholder for structlog context reset if ever needed."""
    yield
