"""Shared test fixtures for Concerto TSS tests."""

from __future__ import annotations

import uuid

import pytest


@pytest.fixture
def agent_id() -> uuid.UUID:
    """Generate a random agent UUID."""
    return uuid.uuid4()


@pytest.fixture
def job_id() -> uuid.UUID:
    """Generate a random job UUID."""
    return uuid.uuid4()
