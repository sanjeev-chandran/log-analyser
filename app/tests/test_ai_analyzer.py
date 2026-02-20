"""Tests for AI Analyzer service."""

from datetime import datetime

import pytest

from app.agent.ai_analyzer import (
    AIAnalyzerInterface,
    ComponentAnalysis,
    RawAnalysis,
)
from app.agent.mock_analyzer import MockAnalyzer
from app.services.log_parser import ParsedLog


@pytest.fixture
def analyzer():
    """MockAnalyzer with delay disabled for fast tests."""
    return MockAnalyzer(simulate_delay=False)


def _make_log(message: str, level: str = "ERROR", service: str = "test-service") -> ParsedLog:
    return ParsedLog(
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        level=level,
        service=service,
        message=message,
    )


# ---------------------------------------------------------------------------
# MockAnalyzer basics
# ---------------------------------------------------------------------------

class TestMockAnalyzerBasics:

    @pytest.mark.asyncio
    async def test_returns_raw_analysis(self, analyzer):
        log = _make_log("Connection timeout to database")
        result = await analyzer.analyze(log)
        assert isinstance(result, RawAnalysis)

    @pytest.mark.asyncio
    async def test_result_has_required_fields(self, analyzer):
        log = _make_log("some error happened")
        result = await analyzer.analyze(log)
        assert result.summary
        assert result.root_cause
        assert isinstance(result.components, list)
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_components_are_valid(self, analyzer):
        log = _make_log("database connection pool exhausted")
        result = await analyzer.analyze(log)
        for comp in result.components:
            assert isinstance(comp, ComponentAnalysis)
            assert comp.name
            assert comp.type
            assert comp.impact_level



# ---------------------------------------------------------------------------
# Pattern routing
# ---------------------------------------------------------------------------

class TestMockAnalyzerPatternRouting:

    @pytest.mark.asyncio
    async def test_database_pattern(self, analyzer):
        for msg in ["database connection failed", "SQL query error", "connection pool exhausted"]:
            result = await analyzer.analyze(_make_log(msg))
            assert "database" in result.summary.lower() or "connection" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_timeout_pattern(self, analyzer):
        for msg in ["request timeout", "operation timed out"]:
            result = await analyzer.analyze(_make_log(msg))
            assert "timeout" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_memory_pattern(self, analyzer):
        for msg in ["out of memory error", "heap space exhausted"]:
            result = await analyzer.analyze(_make_log(msg))
            assert "memory" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_auth_pattern(self, analyzer):
        for msg in ["authentication failed", "unauthorized access", "auth token expired"]:
            result = await analyzer.analyze(_make_log(msg))
            assert "auth" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_api_pattern(self, analyzer):
        for msg in ["api call failed", "http 500 error", "bad request received"]:
            result = await analyzer.analyze(_make_log(msg))
            assert "api" in result.summary.lower() or "error" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_generic_fallback(self, analyzer):
        result = await analyzer.analyze(_make_log("something completely unknown broke"))
        assert "error" in result.summary.lower() or "detected" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_service_name_in_summary(self, analyzer):
        log = _make_log("database error", service="payments-api")
        result = await analyzer.analyze(log)
        assert "payments-api" in result.summary


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

class TestMockAnalyzerCapabilities:

    def test_capabilities_dict(self, analyzer):
        caps = analyzer.get_capabilities()
        assert isinstance(caps, dict)
        assert caps["name"] == "MockAnalyzer"
        assert "version" in caps

    def test_capabilities_has_expected_keys(self, analyzer):
        caps = analyzer.get_capabilities()
        for key in ("name", "version", "supports_streaming", "max_context_length",
                     "supported_languages", "analysis_types"):
            assert key in caps


# ---------------------------------------------------------------------------
# Simulate delay
# ---------------------------------------------------------------------------

class TestMockAnalyzerDelay:

    @pytest.mark.asyncio
    async def test_no_delay_when_disabled(self, analyzer):
        """Should return almost instantly with simulate_delay=False."""
        import time
        log = _make_log("test error")
        start = time.monotonic()
        await analyzer.analyze(log)
        elapsed = time.monotonic() - start
        assert elapsed < 0.05  # less than 50ms

    @pytest.mark.asyncio
    async def test_delay_when_enabled(self):
        """Should take at least min delay ms."""
        import time
        slow = MockAnalyzer(simulate_delay=True, delay_ms=(100, 100))
        log = _make_log("test error")
        start = time.monotonic()
        await slow.analyze(log)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.09  # at least ~90ms (allowing small tolerance)


# ---------------------------------------------------------------------------
# Interface contract
# ---------------------------------------------------------------------------

class TestAIAnalyzerInterface:

    def test_mock_is_instance_of_interface(self, analyzer):
        assert isinstance(analyzer, AIAnalyzerInterface)

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            AIAnalyzerInterface()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class TestDataClasses:

    def test_raw_analysis_defaults(self):
        ra = RawAnalysis(summary="s", root_cause="r")
        assert ra.components == []
        assert ra.confidence == 0.0
        assert ra.raw_text is None

    def test_component_analysis(self):
        c = ComponentAnalysis(name="db", type="database", impact_level="high")
        assert c.name == "db"


