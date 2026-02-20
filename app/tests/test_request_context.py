"""Tests for request context ContextVar and RequestID middleware."""

import asyncio
import json
import logging
import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.request_context import (
    get_request_id,
    set_request_id,
    reset_request_id,
)
from app.main import app
from app.dependencies import get_analysis_service
from app.schemas.analysis import AnalysisResult, ComponentImpact, ComponentType, ImpactLevel
from datetime import datetime, timezone
from uuid import uuid4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_analysis_result(**overrides) -> AnalysisResult:
    defaults = dict(
        id=uuid4(),
        log_id=uuid4(),
        summary="Test summary",
        root_cause="Test root cause",
        affected_components=[
            ComponentImpact(
                name="test-service",
                type=ComponentType.SERVICE,
                impact_level=ImpactLevel.HIGH,
            ),
        ],
        confidence=0.85,
        analyzed_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        processing_time_ms=100,
    )
    defaults.update(overrides)
    return AnalysisResult(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# ContextVar unit tests
# ---------------------------------------------------------------------------


class TestRequestContext:
    """Direct tests for the ContextVar helpers."""

    def test_default_is_none(self):
        assert get_request_id() is None

    def test_set_and_get(self):
        token = set_request_id("abc-123")
        try:
            assert get_request_id() == "abc-123"
        finally:
            reset_request_id(token)

    def test_reset_restores_none(self):
        token = set_request_id("abc-123")
        reset_request_id(token)
        assert get_request_id() is None

    def test_nested_set_and_reset(self):
        """Inner set/reset should not affect the outer value."""
        outer_token = set_request_id("outer")
        inner_token = set_request_id("inner")
        assert get_request_id() == "inner"
        reset_request_id(inner_token)
        assert get_request_id() == "outer"
        reset_request_id(outer_token)
        assert get_request_id() is None

    @pytest.mark.asyncio
    async def test_isolation_across_async_tasks(self):
        """Each async task should have its own ContextVar scope."""
        results = {}

        async def _set_and_read(name: str, delay: float):
            token = set_request_id(name)
            await asyncio.sleep(delay)
            results[name] = get_request_id()
            reset_request_id(token)

        await asyncio.gather(
            _set_and_read("task-a", 0.01),
            _set_and_read("task-b", 0.005),
        )
        assert results["task-a"] == "task-a"
        assert results["task-b"] == "task-b"


# ---------------------------------------------------------------------------
# Middleware integration tests (via real HTTP through the app)
# ---------------------------------------------------------------------------


class TestRequestIDMiddleware:
    """Test middleware behaviour through the FastAPI app."""

    @pytest.mark.asyncio
    async def test_response_contains_x_request_id_header(self):
        """Every response should include X-Request-ID."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/health")

        assert response.status_code == 200
        assert "x-request-id" in response.headers

    @pytest.mark.asyncio
    async def test_generated_request_id_is_valid_uuid(self):
        """When no X-Request-ID is sent, the middleware should generate a UUID-4."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/health")

        request_id = response.headers["x-request-id"]
        # Should not raise
        parsed = uuid.UUID(request_id, version=4)
        assert str(parsed) == request_id

    @pytest.mark.asyncio
    async def test_caller_supplied_request_id_is_echoed_back(self):
        """If caller sends X-Request-ID, the same value should be echoed."""
        custom_id = "my-custom-trace-id-999"
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get(
                "/health",
                headers={"X-Request-ID": custom_id},
            )

        assert response.headers["x-request-id"] == custom_id

    @pytest.mark.asyncio
    async def test_different_requests_get_different_ids(self):
        """Two requests without X-Request-ID should get distinct IDs."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r1 = await ac.get("/health")
            r2 = await ac.get("/health")

        assert r1.headers["x-request-id"] != r2.headers["x-request-id"]

    @pytest.mark.asyncio
    async def test_request_id_present_on_error_responses(self):
        """Even 4xx/5xx responses should carry the X-Request-ID header."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analysis/not-a-uuid")

        assert response.status_code == 422
        assert "x-request-id" in response.headers

    @pytest.mark.asyncio
    async def test_request_id_available_in_service_layer(self):
        """The ContextVar should be readable from within the service layer during a request."""
        captured_request_id = None

        original_result = _make_analysis_result()
        mock_service = AsyncMock()

        async def _capture_and_return(log_data):
            nonlocal captured_request_id
            captured_request_id = get_request_id()
            return original_result

        mock_service.analyze_log.side_effect = _capture_and_return
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        custom_id = "trace-from-gateway-42"
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/logs/analyze",
                json={
                    "timestamp": "2024-01-15T10:23:45Z",
                    "level": "ERROR",
                    "service": "auth-service",
                    "message": "Connection timeout to database",
                },
                headers={"X-Request-ID": custom_id},
            )

        assert response.status_code == 201
        assert captured_request_id == custom_id

    @pytest.mark.asyncio
    async def test_request_id_cleared_after_request(self):
        """The ContextVar should be None outside of a request context."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            await ac.get("/health")

        # After the request completes, the ContextVar should be reset
        assert get_request_id() is None


# ---------------------------------------------------------------------------
# Logger integration tests
# ---------------------------------------------------------------------------


class TestLoggerRequestIDInjection:
    """Verify the JSON formatter injects request_id into log output."""

    def test_request_id_appears_in_log_output_when_set(self):
        """When a request_id is active, the JSON formatter should include it."""
        from app.core.logger import _AppJsonFormatter, _LOG_FORMAT

        # Use a logger under the "app" hierarchy so it inherits the configured level
        logger = logging.getLogger("app.test.request_id_injection")
        logger.setLevel(logging.DEBUG)

        captured = []
        class _CapturingHandler(logging.Handler):
            def emit(self, record):
                captured.append(self.format(record))

        cap_handler = _CapturingHandler()
        cap_handler.setFormatter(_AppJsonFormatter(_LOG_FORMAT))
        logger.addHandler(cap_handler)

        try:
            token = set_request_id("test-trace-123")
            try:
                logger.info("test message")
            finally:
                reset_request_id(token)
        finally:
            logger.removeHandler(cap_handler)

        assert len(captured) == 1
        log_data = json.loads(captured[0])
        assert log_data["request_id"] == "test-trace-123"
        assert log_data["message"] == "test message"

    def test_request_id_absent_when_not_set(self):
        """When no request_id is active, it should not appear in the JSON."""
        from app.core.logger import _AppJsonFormatter, _LOG_FORMAT

        logger = logging.getLogger("app.test.no_request_id")
        logger.setLevel(logging.DEBUG)

        captured = []
        class _CapturingHandler(logging.Handler):
            def emit(self, record):
                captured.append(self.format(record))

        cap_handler = _CapturingHandler()
        cap_handler.setFormatter(_AppJsonFormatter(_LOG_FORMAT))
        logger.addHandler(cap_handler)

        try:
            logger.info("no context message")
        finally:
            logger.removeHandler(cap_handler)

        assert len(captured) == 1
        log_data = json.loads(captured[0])
        assert "request_id" not in log_data
