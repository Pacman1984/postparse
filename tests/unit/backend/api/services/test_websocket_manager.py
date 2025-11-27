"""
Unit tests for WebSocketManager class.

This module provides comprehensive tests for the WebSocketManager service which handles
WebSocket connections and progress broadcasting for extraction jobs.
"""

import asyncio
from datetime import datetime
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.postparse.api.services.websocket_manager import WebSocketManager
from backend.postparse.api.services.job_manager import Job
from backend.postparse.api.schemas.telegram import ExtractionStatus


@pytest.fixture
def mock_websocket() -> AsyncMock:
    """
    Create a mock WebSocket for testing.

    Returns:
        AsyncMock: Mock WebSocket with accept, send_json, and close methods.

    Example:
        def test_something(mock_websocket):
            await mock_websocket.accept()
            mock_websocket.accept.assert_called_once()
    """
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.fixture
def mock_websocket_factory():
    """
    Factory fixture to create multiple mock WebSockets.

    Returns:
        Callable: Function that creates new mock WebSocket instances.

    Example:
        def test_multiple_ws(mock_websocket_factory):
            ws1 = mock_websocket_factory()
            ws2 = mock_websocket_factory()
    """
    def _create_mock_websocket():
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.close = AsyncMock()
        return ws
    return _create_mock_websocket


@pytest.fixture
def sample_job() -> Job:
    """
    Create a sample Job for testing.

    Returns:
        Job: Sample job instance for testing.
    """
    return Job(
        job_id="test-job-123",
        status=ExtractionStatus.RUNNING,
        progress=50,
        messages_processed=100,
        errors=["Warning 1"],
        job_type="telegram",
        metadata={"limit": 200},
    )


class TestWebSocketManagerInitialization:
    """Tests for WebSocketManager initialization."""

    def test_manager_initialization(self) -> None:
        """
        Test WebSocketManager initializes with empty connection store.

        Verifies initial state is correctly set up.
        """
        manager = WebSocketManager()

        assert manager._active_connections == {}
        assert isinstance(manager._lock, asyncio.Lock)


class TestWebSocketManagerConnect:
    """Tests for WebSocketManager.connect()."""

    @pytest.mark.asyncio
    async def test_connect_accepts_websocket(self, mock_websocket: AsyncMock) -> None:
        """
        Test connect calls websocket.accept().

        Verifies WebSocket is properly accepted.
        """
        manager = WebSocketManager()

        await manager.connect("job-123", mock_websocket)

        mock_websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_stores_websocket_for_job(
        self, mock_websocket: AsyncMock
    ) -> None:
        """
        Test connect stores the WebSocket for the job ID.

        Verifies connection is registered.
        """
        manager = WebSocketManager()

        await manager.connect("job-123", mock_websocket)

        assert "job-123" in manager._active_connections
        assert mock_websocket in manager._active_connections["job-123"]

    @pytest.mark.asyncio
    async def test_connect_creates_list_for_new_job(
        self, mock_websocket: AsyncMock
    ) -> None:
        """
        Test connect creates connection list for new job ID.

        Verifies new jobs get their own connection list.
        """
        manager = WebSocketManager()

        await manager.connect("new-job", mock_websocket)

        assert isinstance(manager._active_connections["new-job"], list)
        assert len(manager._active_connections["new-job"]) == 1

    @pytest.mark.asyncio
    async def test_connect_allows_multiple_connections_per_job(
        self, mock_websocket_factory
    ) -> None:
        """
        Test connect allows multiple WebSockets for same job.

        Verifies multiple clients can monitor same job.
        """
        manager = WebSocketManager()
        ws1 = mock_websocket_factory()
        ws2 = mock_websocket_factory()
        ws3 = mock_websocket_factory()

        await manager.connect("job-123", ws1)
        await manager.connect("job-123", ws2)
        await manager.connect("job-123", ws3)

        assert len(manager._active_connections["job-123"]) == 3

    @pytest.mark.asyncio
    async def test_connect_multiple_jobs_are_independent(
        self, mock_websocket_factory
    ) -> None:
        """
        Test connections for different jobs are stored separately.

        Verifies job isolation.
        """
        manager = WebSocketManager()
        ws1 = mock_websocket_factory()
        ws2 = mock_websocket_factory()

        await manager.connect("job-1", ws1)
        await manager.connect("job-2", ws2)

        assert len(manager._active_connections["job-1"]) == 1
        assert len(manager._active_connections["job-2"]) == 1
        assert ws1 in manager._active_connections["job-1"]
        assert ws2 in manager._active_connections["job-2"]


class TestWebSocketManagerDisconnect:
    """Tests for WebSocketManager.disconnect()."""

    @pytest.mark.asyncio
    async def test_disconnect_removes_websocket(
        self, mock_websocket: AsyncMock
    ) -> None:
        """
        Test disconnect removes the WebSocket from connection list.

        Verifies connection is unregistered.
        """
        manager = WebSocketManager()
        await manager.connect("job-123", mock_websocket)

        await manager.disconnect("job-123", mock_websocket)

        assert mock_websocket not in manager._active_connections.get("job-123", [])

    @pytest.mark.asyncio
    async def test_disconnect_closes_websocket(
        self, mock_websocket: AsyncMock
    ) -> None:
        """
        Test disconnect calls websocket.close().

        Verifies WebSocket is properly closed.
        """
        manager = WebSocketManager()
        await manager.connect("job-123", mock_websocket)

        await manager.disconnect("job-123", mock_websocket)

        mock_websocket.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_removes_empty_job_list(
        self, mock_websocket: AsyncMock
    ) -> None:
        """
        Test disconnect removes job entry when no connections remain.

        Verifies cleanup of empty connection lists.
        """
        manager = WebSocketManager()
        await manager.connect("job-123", mock_websocket)

        await manager.disconnect("job-123", mock_websocket)

        assert "job-123" not in manager._active_connections

    @pytest.mark.asyncio
    async def test_disconnect_keeps_other_connections(
        self, mock_websocket_factory
    ) -> None:
        """
        Test disconnect only removes the specified WebSocket.

        Verifies other connections are preserved.
        """
        manager = WebSocketManager()
        ws1 = mock_websocket_factory()
        ws2 = mock_websocket_factory()
        await manager.connect("job-123", ws1)
        await manager.connect("job-123", ws2)

        await manager.disconnect("job-123", ws1)

        assert ws1 not in manager._active_connections["job-123"]
        assert ws2 in manager._active_connections["job-123"]

    @pytest.mark.asyncio
    async def test_disconnect_handles_nonexistent_job(
        self, mock_websocket: AsyncMock
    ) -> None:
        """
        Test disconnect handles disconnecting from nonexistent job gracefully.

        Verifies no error is raised.
        """
        manager = WebSocketManager()

        # Should not raise
        await manager.disconnect("nonexistent-job", mock_websocket)

    @pytest.mark.asyncio
    async def test_disconnect_handles_close_error(
        self, mock_websocket: AsyncMock
    ) -> None:
        """
        Test disconnect handles websocket.close() errors gracefully.

        Verifies errors don't crash the manager.
        """
        manager = WebSocketManager()
        await manager.connect("job-123", mock_websocket)
        mock_websocket.close.side_effect = Exception("Close error")

        # Should not raise
        await manager.disconnect("job-123", mock_websocket)


class TestWebSocketManagerBroadcastProgress:
    """Tests for WebSocketManager.broadcast_progress()."""

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_connections(
        self, mock_websocket_factory
    ) -> None:
        """
        Test broadcast_progress sends to all connected WebSockets.

        Verifies all clients receive the update.
        """
        manager = WebSocketManager()
        ws1 = mock_websocket_factory()
        ws2 = mock_websocket_factory()
        ws3 = mock_websocket_factory()

        await manager.connect("job-123", ws1)
        await manager.connect("job-123", ws2)
        await manager.connect("job-123", ws3)

        progress_data = {"status": "running", "progress": 50}
        await manager.broadcast_progress("job-123", progress_data)

        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()
        ws3.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_adds_timestamp_if_missing(
        self, mock_websocket: AsyncMock
    ) -> None:
        """
        Test broadcast_progress adds timestamp if not present.

        Verifies timestamp is auto-added.
        """
        manager = WebSocketManager()
        await manager.connect("job-123", mock_websocket)

        progress_data = {"status": "running", "progress": 50}
        await manager.broadcast_progress("job-123", progress_data)

        # Get the data that was sent
        sent_data = mock_websocket.send_json.call_args[0][0]
        assert "timestamp" in sent_data

    @pytest.mark.asyncio
    async def test_broadcast_preserves_existing_timestamp(
        self, mock_websocket: AsyncMock
    ) -> None:
        """
        Test broadcast_progress preserves existing timestamp.

        Verifies custom timestamps aren't overwritten.
        """
        manager = WebSocketManager()
        await manager.connect("job-123", mock_websocket)

        custom_timestamp = "2024-01-15T10:30:00Z"
        progress_data = {
            "status": "running",
            "progress": 50,
            "timestamp": custom_timestamp,
        }
        await manager.broadcast_progress("job-123", progress_data)

        sent_data = mock_websocket.send_json.call_args[0][0]
        assert sent_data["timestamp"] == custom_timestamp

    @pytest.mark.asyncio
    async def test_broadcast_does_nothing_for_nonexistent_job(
        self, mock_websocket: AsyncMock
    ) -> None:
        """
        Test broadcast_progress does nothing for unknown job ID.

        Verifies no error for missing jobs.
        """
        manager = WebSocketManager()

        # Should not raise
        progress_data = {"status": "running", "progress": 50}
        await manager.broadcast_progress("nonexistent-job", progress_data)

    @pytest.mark.asyncio
    async def test_broadcast_removes_disconnected_clients(
        self, mock_websocket_factory
    ) -> None:
        """
        Test broadcast_progress removes clients that fail to receive.

        Verifies cleanup of broken connections.
        """
        manager = WebSocketManager()
        ws_good = mock_websocket_factory()
        ws_bad = mock_websocket_factory()
        ws_bad.send_json.side_effect = Exception("Connection closed")

        await manager.connect("job-123", ws_good)
        await manager.connect("job-123", ws_bad)

        progress_data = {"status": "running", "progress": 50}
        await manager.broadcast_progress("job-123", progress_data)

        # Bad connection should be removed
        assert ws_bad not in manager._active_connections.get("job-123", [])
        # Good connection should remain
        assert ws_good in manager._active_connections["job-123"]

    @pytest.mark.asyncio
    async def test_broadcast_only_to_specific_job(
        self, mock_websocket_factory
    ) -> None:
        """
        Test broadcast_progress only sends to the specified job's connections.

        Verifies job isolation during broadcasts.
        """
        manager = WebSocketManager()
        ws_job1 = mock_websocket_factory()
        ws_job2 = mock_websocket_factory()

        await manager.connect("job-1", ws_job1)
        await manager.connect("job-2", ws_job2)

        progress_data = {"status": "running", "progress": 50}
        await manager.broadcast_progress("job-1", progress_data)

        ws_job1.send_json.assert_called_once()
        ws_job2.send_json.assert_not_called()


class TestWebSocketManagerSendJobUpdate:
    """Tests for WebSocketManager.send_job_update()."""

    @pytest.mark.asyncio
    async def test_send_job_update_converts_job_to_dict(
        self, mock_websocket: AsyncMock, sample_job: Job
    ) -> None:
        """
        Test send_job_update converts Job object to dict format.

        Verifies correct data structure is sent.
        """
        manager = WebSocketManager()
        await manager.connect(sample_job.job_id, mock_websocket)

        await manager.send_job_update(sample_job.job_id, sample_job)

        sent_data = mock_websocket.send_json.call_args[0][0]
        assert sent_data["job_id"] == sample_job.job_id
        assert sent_data["status"] == sample_job.status.value
        assert sent_data["progress"] == sample_job.progress
        assert sent_data["messages_processed"] == sample_job.messages_processed
        assert sent_data["errors"] == sample_job.errors

    @pytest.mark.asyncio
    async def test_send_job_update_includes_timestamp(
        self, mock_websocket: AsyncMock, sample_job: Job
    ) -> None:
        """
        Test send_job_update includes timestamp in progress data.

        Verifies timestamp is added to job update.
        """
        manager = WebSocketManager()
        await manager.connect(sample_job.job_id, mock_websocket)

        await manager.send_job_update(sample_job.job_id, sample_job)

        sent_data = mock_websocket.send_json.call_args[0][0]
        assert "timestamp" in sent_data

    @pytest.mark.asyncio
    async def test_send_job_update_broadcasts_to_all(
        self, mock_websocket_factory, sample_job: Job
    ) -> None:
        """
        Test send_job_update broadcasts to all job connections.

        Verifies all clients receive job update.
        """
        manager = WebSocketManager()
        ws1 = mock_websocket_factory()
        ws2 = mock_websocket_factory()

        await manager.connect(sample_job.job_id, ws1)
        await manager.connect(sample_job.job_id, ws2)

        await manager.send_job_update(sample_job.job_id, sample_job)

        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()


class TestWebSocketManagerGetConnectionCount:
    """Tests for WebSocketManager.get_connection_count()."""

    def test_get_connection_count_returns_zero_for_nonexistent_job(self) -> None:
        """
        Test get_connection_count returns 0 for unknown job.

        Verifies correct count for missing jobs.
        """
        manager = WebSocketManager()

        count = manager.get_connection_count("nonexistent-job")

        assert count == 0

    @pytest.mark.asyncio
    async def test_get_connection_count_returns_correct_count(
        self, mock_websocket_factory
    ) -> None:
        """
        Test get_connection_count returns accurate count.

        Verifies count matches actual connections.
        """
        manager = WebSocketManager()
        ws1 = mock_websocket_factory()
        ws2 = mock_websocket_factory()
        ws3 = mock_websocket_factory()

        await manager.connect("job-123", ws1)
        await manager.connect("job-123", ws2)
        await manager.connect("job-123", ws3)

        count = manager.get_connection_count("job-123")

        assert count == 3

    @pytest.mark.asyncio
    async def test_get_connection_count_updates_after_disconnect(
        self, mock_websocket_factory
    ) -> None:
        """
        Test get_connection_count updates after disconnection.

        Verifies count decreases after disconnect.
        """
        manager = WebSocketManager()
        ws1 = mock_websocket_factory()
        ws2 = mock_websocket_factory()

        await manager.connect("job-123", ws1)
        await manager.connect("job-123", ws2)

        assert manager.get_connection_count("job-123") == 2

        await manager.disconnect("job-123", ws1)

        assert manager.get_connection_count("job-123") == 1

    @pytest.mark.asyncio
    async def test_get_connection_count_different_jobs(
        self, mock_websocket_factory
    ) -> None:
        """
        Test get_connection_count returns count per job.

        Verifies counts are job-specific.
        """
        manager = WebSocketManager()
        ws1 = mock_websocket_factory()
        ws2 = mock_websocket_factory()
        ws3 = mock_websocket_factory()

        await manager.connect("job-1", ws1)
        await manager.connect("job-2", ws2)
        await manager.connect("job-2", ws3)

        assert manager.get_connection_count("job-1") == 1
        assert manager.get_connection_count("job-2") == 2


class TestWebSocketManagerConcurrency:
    """Tests for WebSocketManager async concurrency."""

    @pytest.mark.asyncio
    async def test_concurrent_connects(self, mock_websocket_factory) -> None:
        """
        Test concurrent connect operations are handled correctly.

        Verifies no race conditions during parallel connects.
        """
        manager = WebSocketManager()
        websockets = [mock_websocket_factory() for _ in range(10)]

        # Connect all websockets concurrently
        await asyncio.gather(
            *[manager.connect("job-123", ws) for ws in websockets]
        )

        # All should be connected
        assert manager.get_connection_count("job-123") == 10

    @pytest.mark.asyncio
    async def test_concurrent_broadcast_and_disconnect(
        self, mock_websocket_factory
    ) -> None:
        """
        Test concurrent broadcast and disconnect operations.

        Verifies no race conditions during parallel operations.
        """
        manager = WebSocketManager()
        websockets = [mock_websocket_factory() for _ in range(5)]

        for ws in websockets:
            await manager.connect("job-123", ws)

        # Run broadcast and disconnect concurrently
        progress_data = {"status": "running", "progress": 50}
        tasks = [
            manager.broadcast_progress("job-123", progress_data),
            manager.disconnect("job-123", websockets[0]),
            manager.broadcast_progress("job-123", progress_data),
        ]

        # Should not raise
        await asyncio.gather(*tasks)


