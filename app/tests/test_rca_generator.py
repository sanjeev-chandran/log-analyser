"""Tests for RCA Generator service."""

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import AnalysisError
from app.schemas.analysis import (
    AnalysisResult,
    ComponentImpact,
    ComponentType,
    ImpactLevel,
)
from app.agent.ai_analyzer import (
    AIAnalyzerInterface,
    ComponentAnalysis,
    RawAnalysis,
)
from app.agent.mock_analyzer import MockAnalyzer
from app.services.log_parser import ParsedLog
from app.services.rca_generator import RCAGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_log(
    message: str = "Connection timeout to database",
    level: str = "ERROR",
    service: str = "auth-service",
) -> ParsedLog:
    return ParsedLog(
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        level=level,
        service=service,
        message=message,
    )


_DEFAULT_COMPONENTS = [
    ComponentAnalysis(name="svc", type="service", impact_level="high"),
]


def _make_raw_analysis(
    confidence: float = 0.9,
    components: list = None,
) -> RawAnalysis:
    return RawAnalysis(
        summary="Test summary",
        root_cause="Test root cause",
        components=_DEFAULT_COMPONENTS if components is None else components,
        confidence=confidence,
    )


class FailingAnalyzer(AIAnalyzerInterface):
    """Analyzer that always raises."""

    async def analyze(self, log: ParsedLog) -> RawAnalysis:
        raise RuntimeError("AI backend exploded")

    def get_capabilities(self):
        return {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def generator():
    return RCAGenerator(
        ai_analyzer=MockAnalyzer(simulate_delay=False),
    )


# ---------------------------------------------------------------------------
# generate() - happy path
# ---------------------------------------------------------------------------

class TestGenerate:

    @pytest.mark.asyncio
    async def test_returns_analysis_result(self, generator):
        log = _make_log()
        result = await generator.generate(log)
        assert isinstance(result, AnalysisResult)

    @pytest.mark.asyncio
    async def test_result_has_uuid_ids(self, generator):
        result = await generator.generate(_make_log())
        assert isinstance(result.id, UUID)
        assert isinstance(result.log_id, UUID)

    @pytest.mark.asyncio
    async def test_uses_provided_log_entry_id(self, generator):
        entry_id = uuid4()
        result = await generator.generate(_make_log(), log_entry_id=entry_id)
        assert result.log_id == entry_id

    @pytest.mark.asyncio
    async def test_summary_and_root_cause_populated(self, generator):
        result = await generator.generate(_make_log())
        assert result.summary
        assert result.root_cause

    @pytest.mark.asyncio
    async def test_components_are_component_impact(self, generator):
        result = await generator.generate(_make_log())
        for comp in result.affected_components:
            assert isinstance(comp, ComponentImpact)

    @pytest.mark.asyncio
    async def test_confidence_in_range(self, generator):
        result = await generator.generate(_make_log())
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_processing_time_positive(self, generator):
        result = await generator.generate(_make_log())
        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_analyzed_at_is_datetime(self, generator):
        result = await generator.generate(_make_log())
        assert isinstance(result.analyzed_at, datetime)


# ---------------------------------------------------------------------------
# generate() - error handling
# ---------------------------------------------------------------------------

class TestGenerateErrors:

    @pytest.mark.asyncio
    async def test_wraps_unexpected_error_in_analysis_error(self):
        gen = RCAGenerator(ai_analyzer=FailingAnalyzer())
        with pytest.raises(AnalysisError, match="Failed to generate RCA"):
            await gen.generate(_make_log())

    @pytest.mark.asyncio
    async def test_analysis_error_has_details(self):
        gen = RCAGenerator(ai_analyzer=FailingAnalyzer())
        with pytest.raises(AnalysisError) as exc_info:
            await gen.generate(_make_log(service="my-svc"))
        assert exc_info.value.details["log_service"] == "my-svc"


# ---------------------------------------------------------------------------
# _structure_components()
# ---------------------------------------------------------------------------

class TestStructureComponents:

    def setup_method(self):
        self.gen = RCAGenerator(ai_analyzer=MockAnalyzer(simulate_delay=False))

    def test_maps_known_types(self):
        raw = _make_raw_analysis(components=[
            ComponentAnalysis(name="pg", type="database", impact_level="high"),
            ComponentAnalysis(name="redis", type="cache", impact_level="medium"),
            ComponentAnalysis(name="gateway", type="api", impact_level="low"),
            ComponentAnalysis(name="rabbitmq", type="queue", impact_level="critical"),
            ComponentAnalysis(name="stripe", type="external", impact_level="high"),
        ])
        result = self.gen._structure_components(raw)
        types = [c.type for c in result]
        assert ComponentType.DATABASE in types
        assert ComponentType.CACHE in types
        assert ComponentType.API in types
        assert ComponentType.QUEUE in types
        assert ComponentType.EXTERNAL in types

    def test_unknown_type_defaults_to_service(self):
        raw = _make_raw_analysis(components=[
            ComponentAnalysis(name="x", type="unknown_thing", impact_level="low"),
        ])
        result = self.gen._structure_components(raw)
        assert result[0].type == ComponentType.SERVICE

    def test_maps_impact_levels(self):
        raw = _make_raw_analysis(components=[
            ComponentAnalysis(name="a", type="service", impact_level="critical"),
            ComponentAnalysis(name="b", type="service", impact_level="high"),
            ComponentAnalysis(name="c", type="service", impact_level="medium"),
            ComponentAnalysis(name="d", type="service", impact_level="low"),
        ])
        result = self.gen._structure_components(raw)
        levels = [c.impact_level for c in result]
        assert levels == [ImpactLevel.CRITICAL, ImpactLevel.HIGH, ImpactLevel.MEDIUM, ImpactLevel.LOW]

    def test_empty_components(self):
        raw = _make_raw_analysis(components=[])
        assert self.gen._structure_components(raw) == []


# ---------------------------------------------------------------------------
# Enum mapping helpers
# ---------------------------------------------------------------------------

class TestEnumMappings:

    def setup_method(self):
        self.gen = RCAGenerator(ai_analyzer=MockAnalyzer(simulate_delay=False))

    # Component type aliases
    def test_db_alias(self):
        assert self.gen._map_component_type("db") == ComponentType.DATABASE

    def test_redis_alias(self):
        assert self.gen._map_component_type("redis") == ComponentType.CACHE

    def test_memcached_alias(self):
        assert self.gen._map_component_type("memcached") == ComponentType.CACHE

    def test_gateway_alias(self):
        assert self.gen._map_component_type("gateway") == ComponentType.API

    def test_message_queue_alias(self):
        assert self.gen._map_component_type("message_queue") == ComponentType.QUEUE

    def test_third_party_alias(self):
        assert self.gen._map_component_type("third_party") == ComponentType.EXTERNAL

    def test_hyphenated_type(self):
        assert self.gen._map_component_type("message-queue") == ComponentType.QUEUE

    # Impact level
    def test_unknown_impact_defaults_medium(self):
        assert self.gen._map_impact_level("unknown") == ImpactLevel.MEDIUM
