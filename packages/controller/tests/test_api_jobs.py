"""Tests for the jobs REST API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from concerto_controller.api.jobs import JobCreateBody, create_job, get_job, list_jobs
from concerto_controller.db.models import JobRecord
from concerto_shared.enums import JobStatus, Product


def _make_job(job_id=None, product=Product.VEHICLE_GATEWAY, status=JobStatus.QUEUED):
    return JobRecord(
        id=job_id or uuid.uuid4(),
        product=product,
        status=status,
        created_at=datetime.now(timezone.utc),
    )


class TestCreateJob:
    """Tests for the create_job endpoint."""

    @pytest.mark.asyncio
    async def test_creates_and_returns_job(self):
        """Verify create_job adds a job and triggers dispatch."""
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()

        async def fake_refresh(obj):
            obj.created_at = datetime.now(timezone.utc)

        session.refresh = AsyncMock(side_effect=fake_refresh)

        body = JobCreateBody(product=Product.VEHICLE_GATEWAY)

        with (
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            result = await create_job(body=body, session=session)

        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        assert result.product == Product.VEHICLE_GATEWAY
        assert result.status == JobStatus.QUEUED

    @pytest.mark.asyncio
    async def test_creates_job_with_duration(self):
        """Verify create_job stores custom duration."""
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()

        async def fake_refresh(obj):
            obj.created_at = datetime.now(timezone.utc)

        session.refresh = AsyncMock(side_effect=fake_refresh)

        body = JobCreateBody(product=Product.ASSET_GATEWAY, duration=5.0)

        with (
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            result = await create_job(body=body, session=session)

        assert result.duration == 5.0


class TestListJobs:
    """Tests for the list_jobs endpoint."""

    @pytest.mark.asyncio
    async def test_returns_all_jobs(self):
        """Verify list_jobs returns all jobs when no filters."""
        job = _make_job()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [job]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await list_jobs(status=None, product=None, session=session)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_filters_by_status(self):
        """Verify list_jobs applies status filter."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await list_jobs(
            status=JobStatus.COMPLETED, product=None, session=session
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_filters_by_product(self):
        """Verify list_jobs applies product filter."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await list_jobs(
            status=None, product=Product.VEHICLE_GATEWAY, session=session
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_filters_by_both(self):
        """Verify list_jobs applies both status and product filters."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await list_jobs(
            status=JobStatus.QUEUED, product=Product.ASSET_GATEWAY, session=session
        )
        assert result == []


class TestGetJob:
    """Tests for the get_job endpoint."""

    @pytest.mark.asyncio
    async def test_returns_job(self):
        """Verify get_job returns a job by ID."""
        job = _make_job()
        session = AsyncMock()
        session.get = AsyncMock(return_value=job)

        result = await get_job(job_id=job.id, session=session)
        assert result.id == job.id

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        """Verify get_job raises 404."""
        from fastapi import HTTPException

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_job(job_id=uuid.uuid4(), session=session)
        assert exc_info.value.status_code == 404
