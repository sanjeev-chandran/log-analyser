"""Tests for API endpoints (Phase 3).

Tests mock at the *service* layer so routers stay thin and tests don't
need to know anything about SQLAlchemy or session management.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.dependencies import get_analysis_service
from app.schemas.analysis import (
    AnalysisResult,
    AnalysisListResponse,
    ComponentImpact,
    ComponentType,
    ImpactLevel,
)
from app.core.exceptions import (
    AnalysisNotFoundError,
    LogNotFoundError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_analysis_result(**overrides) -> AnalysisResult:
    """Build a valid AnalysisResult with sensible defaults."""
    defaults = dict(
        id=uuid4(),
        log_id=uuid4(),
        summary="Database connection issue in auth-service",
        root_cause="Connection pool exhaustion caused timeout",
        affected_components=[
            ComponentImpact(
                name="auth-service",
                type=ComponentType.SERVICE,
                impact_level=ImpactLevel.CRITICAL,
            ),
            ComponentImpact(
                name="postgres-db",
                type=ComponentType.DATABASE,
                impact_level=ImpactLevel.HIGH,
            ),
        ],
        confidence=0.92,
        analyzed_at=datetime(2024, 1, 15, 10, 23, 50, tzinfo=timezone.utc),
        processing_time_ms=450,
    )
    defaults.update(overrides)
    return AnalysisResult(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_log_payload():
    return {
        "timestamp": "2024-01-15T10:23:45Z",
        "level": "ERROR",
        "service": "auth-service",
        "message": "Connection timeout to database",
        "trace_id": "abc-123-xyz",
        "metadata": {"user_id": "12345"},
    }


@pytest.fixture
def client():
    """Synchronous test client."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Ensure dependency overrides are cleaned up after every test."""
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestHealthCheck:

    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_status_healthy(self, client):
        data = client.get("/health").json()
        assert data["status"] == "healthy"

    def test_health_returns_service_name(self, client):
        data = client.get("/health").json()
        assert "service" in data

    def test_health_returns_version(self, client):
        data = client.get("/health").json()
        assert "version" in data


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


class TestExceptionHandlers:

    def test_log_parse_error_returns_400_or_422(self, client):
        """POST with invalid level is rejected by Pydantic validation."""
        response = client.post(
            "/api/v1/logs/analyze",
            json={
                "timestamp": "2024-01-15T10:23:45Z",
                "level": "INVALID_LEVEL",
                "service": "svc",
                "message": "msg",
            },
        )
        assert response.status_code in (400, 422)

    def test_missing_required_field_returns_422(self, client):
        response = client.post(
            "/api/v1/logs/analyze",
            json={"level": "ERROR", "service": "svc", "message": "msg"},
        )
        assert response.status_code == 422

    def test_empty_body_returns_422(self, client):
        response = client.post("/api/v1/logs/analyze", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/logs/analyze
# ---------------------------------------------------------------------------


class TestAnalyzeLogEndpoint:

    @pytest.mark.asyncio
    async def test_analyze_returns_201_with_valid_input(self, valid_log_payload):
        expected = _make_analysis_result()
        mock_service = AsyncMock()
        mock_service.analyze_log.return_value = expected
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/logs/analyze", json=valid_log_payload
            )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == str(expected.id)
        assert data["log_id"] == str(expected.log_id)
        assert data["summary"] == expected.summary
        assert data["root_cause"] == expected.root_cause
        assert data["confidence"] == expected.confidence
        assert data["processing_time_ms"] == expected.processing_time_ms
        assert 0.0 <= data["confidence"] <= 1.0

        # Service was called with the parsed dict
        mock_service.analyze_log.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_analyze_returns_analysis_with_components(self, valid_log_payload):
        expected = _make_analysis_result()
        mock_service = AsyncMock()
        mock_service.analyze_log.return_value = expected
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/logs/analyze", json=valid_log_payload
            )

        data = response.json()
        components = data["affected_components"]
        assert isinstance(components, list)
        assert len(components) == 2
        for comp in components:
            assert "name" in comp
            assert "type" in comp
            assert "impact_level" in comp

    def test_analyze_rejects_invalid_level(self, client, valid_log_payload):
        valid_log_payload["level"] = "CRITICAL"
        response = client.post("/api/v1/logs/analyze", json=valid_log_payload)
        assert response.status_code == 422

    def test_analyze_rejects_empty_service(self, client, valid_log_payload):
        valid_log_payload["service"] = ""
        response = client.post("/api/v1/logs/analyze", json=valid_log_payload)
        assert response.status_code == 422

    def test_analyze_rejects_empty_message(self, client, valid_log_payload):
        valid_log_payload["message"] = ""
        response = client.post("/api/v1/logs/analyze", json=valid_log_payload)
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/{analysis_id}
# ---------------------------------------------------------------------------


class TestGetAnalysisEndpoint:

    @pytest.mark.asyncio
    async def test_get_existing_analysis_returns_200(self):
        expected = _make_analysis_result()
        mock_service = AsyncMock()
        mock_service.get_by_id.return_value = expected
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get(f"/api/v1/analysis/{expected.id}")

        assert response.status_code == 200
        assert response.json()["id"] == str(expected.id)

    @pytest.mark.asyncio
    async def test_get_nonexistent_analysis_returns_404(self):
        mock_service = AsyncMock()
        aid = uuid4()
        mock_service.get_by_id.side_effect = AnalysisNotFoundError(str(aid))
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get(f"/api/v1/analysis/{aid}")

        assert response.status_code == 404
        assert response.json()["error"] == "Not Found"

    def test_get_analysis_invalid_uuid_returns_422(self, client):
        response = client.get("/api/v1/analysis/not-a-uuid")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/analysis  (list)
# ---------------------------------------------------------------------------


class TestListAnalysesEndpoint:

    @pytest.mark.asyncio
    async def test_list_returns_200_with_empty_results(self):
        mock_service = AsyncMock()
        mock_service.list_analyses.return_value = AnalysisListResponse(
            items=[], total=0, page=1, page_size=20
        )
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analysis")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_list_returns_items(self):
        items = [_make_analysis_result(), _make_analysis_result()]
        mock_service = AsyncMock()
        mock_service.list_analyses.return_value = AnalysisListResponse(
            items=items, total=2, page=1, page_size=20
        )
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analysis")

        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 2

    def test_list_validates_limit_too_large(self, client):
        response = client.get("/api/v1/analysis?limit=999")
        assert response.status_code == 422

    def test_list_validates_negative_skip(self, client):
        response = client.get("/api/v1/analysis?skip=-1")
        assert response.status_code == 422

    def test_list_validates_zero_limit(self, client):
        response = client.get("/api/v1/analysis?limit=0")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/by-log/{log_id}
# ---------------------------------------------------------------------------


class TestGetAnalysisByLogEndpoint:

    @pytest.mark.asyncio
    async def test_existing_log_returns_analysis(self):
        expected = _make_analysis_result()
        mock_service = AsyncMock()
        mock_service.get_by_log_id.return_value = expected
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get(
                f"/api/v1/analysis/by-log/{expected.log_id}"
            )

        assert response.status_code == 200
        assert response.json()["log_id"] == str(expected.log_id)

    @pytest.mark.asyncio
    async def test_nonexistent_log_returns_404(self):
        lid = uuid4()
        mock_service = AsyncMock()
        mock_service.get_by_log_id.side_effect = LogNotFoundError(str(lid))
        app.dependency_overrides[get_analysis_service] = lambda: mock_service

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get(f"/api/v1/analysis/by-log/{lid}")

        assert response.status_code == 404

    def test_invalid_uuid_returns_422(self, client):
        response = client.get("/api/v1/analysis/by-log/not-a-uuid")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


class TestCORS:

    def test_cors_headers_on_options(self, client):
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200

    def test_cors_allow_origin_header(self, client):
        response = client.get(
            "/health", headers={"Origin": "http://localhost:3000"}
        )
        assert "access-control-allow-origin" in response.headers
