"""
Unit tests for extraction services.

This module provides tests for TelegramExtractionService and InstagramExtractionService,
focusing on job lifecycle management, progress tracking, and error handling.
"""

import asyncio
from datetime import datetime
from typing import AsyncIterator, Iterator, List
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from backend.postparse.api.services.extraction_service import (
    TelegramExtractionService,
    InstagramExtractionService,
)
from backend.postparse.api.services.job_manager import JobManager, Job
from backend.postparse.api.services.websocket_manager import WebSocketManager
from backend.postparse.api.schemas.telegram import ExtractionStatus


@pytest.fixture
def mock_job_manager() -> Mock:
    """
    Create a mock JobManager for testing.

    Returns:
        Mock JobManager with all methods mocked.
    """
    manager = Mock(spec=JobManager)
    manager.update_job_status = Mock()
    manager.mark_job_completed = Mock()
    manager.mark_job_failed = Mock()
    manager.get_job = Mock(return_value=Job(
        job_id="test-job-123",
        status=ExtractionStatus.RUNNING,
        progress=50,
        messages_processed=100,
    ))
    return manager


@pytest.fixture
def mock_ws_manager() -> AsyncMock:
    """
    Create a mock WebSocketManager for testing.

    Returns:
        AsyncMock WebSocketManager with broadcast_progress mocked.
    """
    manager = AsyncMock(spec=WebSocketManager)
    manager.broadcast_progress = AsyncMock()
    return manager


@pytest.fixture
def mock_database() -> Mock:
    """
    Create a mock SocialMediaDatabase for testing.

    Returns:
        Mock database with insert methods mocked.
    """
    db = Mock()
    db._insert_telegram_message = Mock(return_value=1)
    db._insert_instagram_post = Mock(return_value=1)
    return db


class TestTelegramExtractionServiceInit:
    """Tests for TelegramExtractionService initialization."""

    def test_initialization_stores_dependencies(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test service initialization stores all dependencies.

        Verifies all managers are properly stored.
        """
        service = TelegramExtractionService(
            job_manager=mock_job_manager,
            ws_manager=mock_ws_manager,
            db=mock_database,
        )

        assert service.job_manager is mock_job_manager
        assert service.ws_manager is mock_ws_manager
        assert service.db is mock_database


class TestTelegramExtractionServiceCalculateProgress:
    """Tests for TelegramExtractionService._calculate_progress()."""

    def test_calculate_progress_with_known_total(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test progress calculation with known total.

        Verifies percentage is calculated correctly.
        """
        service = TelegramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        assert service._calculate_progress(50, 100) == 50
        assert service._calculate_progress(0, 100) == 0
        assert service._calculate_progress(100, 100) == 100
        assert service._calculate_progress(75, 100) == 75

    def test_calculate_progress_clamps_to_100(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test progress calculation clamps to 100%.

        Verifies progress doesn't exceed 100.
        """
        service = TelegramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        assert service._calculate_progress(150, 100) == 100
        assert service._calculate_progress(200, 100) == 100

    def test_calculate_progress_with_none_total(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test progress calculation with unknown total.

        Verifies logarithmic scale is used.
        """
        service = TelegramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        # With None total, uses formula: min(95, 50 + 10 * (current / 100))
        assert service._calculate_progress(0, None) == 50
        assert service._calculate_progress(100, None) == 60
        assert service._calculate_progress(500, None) == 95  # clamped at 95

    def test_calculate_progress_with_zero_total(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test progress calculation with zero total (treated as unknown).

        Verifies zero total is handled like None.
        """
        service = TelegramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        assert service._calculate_progress(50, 0) == 55


class TestTelegramExtractionServiceRunExtraction:
    """Tests for TelegramExtractionService.run_extraction()."""

    @pytest.mark.asyncio
    async def test_run_extraction_marks_job_running(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test run_extraction marks job as RUNNING at start.

        Verifies initial status update.
        """
        service = TelegramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        # Mock the parser to raise immediately so we can check initial state
        with patch(
            "backend.postparse.api.services.extraction_service.TelegramParser"
        ) as MockParser:
            mock_parser = AsyncMock()
            mock_parser.__aenter__ = AsyncMock(side_effect=Exception("Test"))
            MockParser.return_value = mock_parser

            await service.run_extraction(
                job_id="job-123",
                api_id=12345,
                api_hash="abc123",
                phone="+1234567890",
                limit=100,
                force_update=False,
                max_requests_per_session=30,
            )

        # First call should be to mark as RUNNING
        first_call = mock_job_manager.update_job_status.call_args_list[0]
        assert first_call[0][1] == ExtractionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_run_extraction_broadcasts_initial_progress(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test run_extraction broadcasts initial progress via WebSocket.

        Verifies initial broadcast is sent.
        """
        service = TelegramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        with patch(
            "backend.postparse.api.services.extraction_service.TelegramParser"
        ) as MockParser:
            mock_parser = AsyncMock()
            mock_parser.__aenter__ = AsyncMock(side_effect=Exception("Test"))
            MockParser.return_value = mock_parser

            await service.run_extraction(
                job_id="job-123",
                api_id=12345,
                api_hash="abc123",
                phone=None,
                limit=100,
                force_update=False,
                max_requests_per_session=None,
            )

        # First broadcast should be running status with 0 progress
        first_broadcast = mock_ws_manager.broadcast_progress.call_args_list[0]
        assert first_broadcast[0][0] == "job-123"
        assert first_broadcast[0][1]["status"] == "running"
        assert first_broadcast[0][1]["progress"] == 0

    @pytest.mark.asyncio
    async def test_run_extraction_handles_general_error(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test run_extraction marks job as FAILED on general error.

        Verifies error handling marks job failed.
        """
        service = TelegramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        with patch(
            "backend.postparse.api.services.extraction_service.TelegramParser"
        ) as MockParser:
            mock_parser = AsyncMock()
            mock_parser.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
            MockParser.return_value = mock_parser

            await service.run_extraction(
                job_id="job-123",
                api_id=12345,
                api_hash="abc123",
                phone=None,
                limit=100,
                force_update=False,
                max_requests_per_session=None,
            )

        mock_job_manager.mark_job_failed.assert_called_once()
        call_args = mock_job_manager.mark_job_failed.call_args[0]
        assert call_args[0] == "job-123"
        assert "Connection failed" in call_args[1]

    @pytest.mark.asyncio
    async def test_run_extraction_handles_value_error(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test run_extraction handles ValueError (auth errors) specially.

        Verifies authentication errors are handled.
        """
        service = TelegramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        with patch(
            "backend.postparse.api.services.extraction_service.TelegramParser"
        ) as MockParser:
            mock_parser = AsyncMock()
            mock_parser.__aenter__ = AsyncMock(
                side_effect=ValueError("Invalid session")
            )
            MockParser.return_value = mock_parser

            await service.run_extraction(
                job_id="job-123",
                api_id=12345,
                api_hash="abc123",
                phone=None,
                limit=100,
                force_update=False,
                max_requests_per_session=None,
            )

        mock_job_manager.mark_job_failed.assert_called_once()
        call_args = mock_job_manager.mark_job_failed.call_args[0]
        assert "Authentication error" in call_args[1]

    @pytest.mark.asyncio
    async def test_run_extraction_broadcasts_failure(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test run_extraction broadcasts failure via WebSocket.

        Verifies failure broadcast is sent.
        """
        service = TelegramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        with patch(
            "backend.postparse.api.services.extraction_service.TelegramParser"
        ) as MockParser:
            mock_parser = AsyncMock()
            mock_parser.__aenter__ = AsyncMock(side_effect=Exception("Error"))
            MockParser.return_value = mock_parser

            await service.run_extraction(
                job_id="job-123",
                api_id=12345,
                api_hash="abc123",
                phone=None,
                limit=100,
                force_update=False,
                max_requests_per_session=None,
            )

        # Last broadcast should be failure status
        last_broadcast = mock_ws_manager.broadcast_progress.call_args_list[-1]
        assert last_broadcast[0][1]["status"] == "failed"
        assert len(last_broadcast[0][1]["errors"]) > 0


class TestInstagramExtractionServiceInit:
    """Tests for InstagramExtractionService initialization."""

    def test_initialization_stores_dependencies(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test service initialization stores all dependencies.

        Verifies all managers are properly stored.
        """
        service = InstagramExtractionService(
            job_manager=mock_job_manager,
            ws_manager=mock_ws_manager,
            db=mock_database,
        )

        assert service.job_manager is mock_job_manager
        assert service.ws_manager is mock_ws_manager
        assert service.db is mock_database


class TestInstagramExtractionServiceCalculateProgress:
    """Tests for InstagramExtractionService._calculate_progress()."""

    def test_calculate_progress_with_known_total(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test progress calculation with known total.

        Verifies percentage is calculated correctly.
        """
        service = InstagramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        assert service._calculate_progress(25, 100) == 25
        assert service._calculate_progress(0, 50) == 0
        assert service._calculate_progress(50, 50) == 100

    def test_calculate_progress_with_none_total(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test progress calculation with unknown total.

        Verifies logarithmic scale is used.
        """
        service = InstagramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        assert service._calculate_progress(0, None) == 50
        assert service._calculate_progress(200, None) == 70


class TestInstagramExtractionServiceRunExtraction:
    """Tests for InstagramExtractionService.run_extraction()."""

    @pytest.mark.asyncio
    async def test_run_extraction_marks_job_running(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test run_extraction marks job as RUNNING at start.

        Verifies initial status update.
        """
        service = InstagramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        with patch(
            "backend.postparse.api.services.extraction_service.InstaloaderParser"
        ) as MockParser:
            mock_parser = MagicMock()
            mock_parser.__enter__ = MagicMock(
                side_effect=Exception("Test")
            )
            MockParser.return_value = mock_parser

            await service.run_extraction(
                job_id="job-123",
                username="test_user",
                password="password",
                access_token=None,
                limit=50,
                force_update=False,
                use_api=False,
            )

        # First call should be to mark as RUNNING
        first_call = mock_job_manager.update_job_status.call_args_list[0]
        assert first_call[0][1] == ExtractionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_run_extraction_api_raises_not_implemented(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test run_extraction with use_api=True raises NotImplementedError.

        Verifies API mode is not yet supported.
        """
        service = InstagramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        await service.run_extraction(
            job_id="job-123",
            username="test_user",
            password=None,
            access_token="token",
            limit=50,
            force_update=False,
            use_api=True,
        )

        # Should mark job as failed with NotImplementedError message
        mock_job_manager.mark_job_failed.assert_called_once()
        call_args = mock_job_manager.mark_job_failed.call_args[0]
        assert "not yet fully implemented" in call_args[1]

    @pytest.mark.asyncio
    async def test_run_extraction_handles_error(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test run_extraction marks job as FAILED on error.

        Verifies error handling.
        """
        service = InstagramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        with patch(
            "backend.postparse.api.services.extraction_service.InstaloaderParser"
        ) as MockParser:
            mock_parser = MagicMock()
            mock_parser.__enter__ = MagicMock(
                side_effect=Exception("Login failed")
            )
            MockParser.return_value = mock_parser

            await service.run_extraction(
                job_id="job-123",
                username="test_user",
                password="password",
                access_token=None,
                limit=50,
                force_update=False,
                use_api=False,
            )

        mock_job_manager.mark_job_failed.assert_called_once()
        call_args = mock_job_manager.mark_job_failed.call_args[0]
        assert "Login failed" in call_args[1]

    @pytest.mark.asyncio
    async def test_run_extraction_broadcasts_initial_progress(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test run_extraction broadcasts initial progress.

        Verifies initial broadcast is sent.
        """
        service = InstagramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        with patch(
            "backend.postparse.api.services.extraction_service.InstaloaderParser"
        ) as MockParser:
            mock_parser = MagicMock()
            mock_parser.__enter__ = MagicMock(
                side_effect=Exception("Error")
            )
            MockParser.return_value = mock_parser

            await service.run_extraction(
                job_id="job-123",
                username="test_user",
                password="password",
                access_token=None,
                limit=50,
                force_update=False,
                use_api=False,
            )

        # First broadcast should be running status with 0 progress
        first_broadcast = mock_ws_manager.broadcast_progress.call_args_list[0]
        assert first_broadcast[0][0] == "job-123"
        assert first_broadcast[0][1]["status"] == "running"
        assert first_broadcast[0][1]["progress"] == 0

    @pytest.mark.asyncio
    async def test_run_extraction_broadcasts_failure(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test run_extraction broadcasts failure via WebSocket.

        Verifies failure broadcast is sent.
        """
        service = InstagramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        with patch(
            "backend.postparse.api.services.extraction_service.InstaloaderParser"
        ) as MockParser:
            mock_parser = MagicMock()
            mock_parser.__enter__ = MagicMock(
                side_effect=Exception("Error")
            )
            MockParser.return_value = mock_parser

            await service.run_extraction(
                job_id="job-123",
                username="test_user",
                password="password",
                access_token=None,
                limit=50,
                force_update=False,
                use_api=False,
            )

        # Last broadcast should be failure status
        last_broadcast = mock_ws_manager.broadcast_progress.call_args_list[-1]
        assert last_broadcast[0][1]["status"] == "failed"


class TestExtractionServiceEdgeCases:
    """Tests for edge cases in extraction services."""

    def test_calculate_progress_exact_percentage(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test progress calculation produces exact percentages.

        Verifies integer rounding.
        """
        service = TelegramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        # 1 out of 3 should be 33%
        assert service._calculate_progress(1, 3) == 33
        # 2 out of 3 should be 66%
        assert service._calculate_progress(2, 3) == 66

    def test_calculate_progress_large_numbers(
        self,
        mock_job_manager: Mock,
        mock_ws_manager: AsyncMock,
        mock_database: Mock,
    ) -> None:
        """
        Test progress calculation with large numbers.

        Verifies no overflow issues.
        """
        service = TelegramExtractionService(
            mock_job_manager, mock_ws_manager, mock_database
        )

        assert service._calculate_progress(500000, 1000000) == 50
        assert service._calculate_progress(999999, 1000000) == 99


