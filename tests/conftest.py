"""Shared test fixtures for Concerto TSS tests."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def agent_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def job_id() -> uuid.UUID:
    return uuid.uuid4()
