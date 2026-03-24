"""Tests for OpenCodeAnalyzer resilience features (retry, circuit breaker, fallback)."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import time

import pytest
import httpx

from app.agent.opencode_analyzer import (
    OpenCodeAnalyzer,
    calculate_retry_delay,
    DEFAULT_MAX_RETRIES,
)
from app.agent.mock_analyzer import MockAnalyzer
from app.agent.ai_analyzer import RawAnalysis
from app.agent.circuit_breaker import CircuitState
from app.core.exceptions import AnalysisError
from app.services.log_parser import ParsedLog


@pytest.fixture
def sample_log():
    return ParsedLog(
        timestamp=datetime(2024, 1, 15, 10, 0, 0),
        level="ERROR",
        service="test-service",
        message="Connection timeout to database",
        trace_id="test-trace-123",
    )


@pytest.fixture
def mock_analyzer():
    return MockAnalyzer(simulate_delay=False)


# ---------------------------------------------------------------------------
# Retry delay calculation
# ---------------------------------------------------------------------------

class TestRetryDelayCalculation:
    
    def test_exponential_backoff(self):
        # Attempt 0: base delay
        delay0 = calculate_retry_delay(0, base_delay=1.0)
        assert delay0 >= 0.8  # ~1s ± 20%
        
        # Attempt 1: 2x base
        delay1 = calculate_retry_delay(1, base_delay=1.0)
        assert delay1 >= 1.6  # ~2s ± 20%
        
        # Attempt 2: 4x base
        delay2 = calculate_retry_delay(2, base_delay=1.0)
        assert delay2 >= 3.2  # ~4s ± 20%
    
    def test_max_delay_cap(self):
        delay = calculate_retry_delay(10, base_delay=1.0, max_delay=5.0)
        assert delay <= 6.0  # 5s + 20% max
    
    def test_minimum_delay(self):
        delay = calculate_retry_delay(0, base_delay=0.01)
        assert delay >= 0.1  # Minimum of 0.1s


# ---------------------------------------------------------------------------
# OpenCodeAnalyzer initialization
# ---------------------------------------------------------------------------

class TestOpenCodeAnalyzerInit:
    
    def test_initialization_with_defaults(self):
        analyzer = OpenCodeAnalyzer(server_url="http://localhost:4096")
        
        assert analyzer._server_url == "http://localhost:4096"
        assert analyzer._max_retries == DEFAULT_MAX_RETRIES
        assert analyzer._fallback_analyzer is None
        assert analyzer.circuit_breaker is not None
    
    def test_initialization_with_fallback(self, mock_analyzer):
        analyzer = OpenCodeAnalyzer(
            server_url="http://localhost:4096",
            fallback_analyzer=mock_analyzer,
        )
        
        assert analyzer._fallback_analyzer is mock_analyzer
    
    def test_circuit_breaker_enabled(self):
        analyzer = OpenCodeAnalyzer(server_url="http://localhost:4096")
        assert analyzer.circuit_breaker.is_closed


# ---------------------------------------------------------------------------
# Fallback mechanism
# ---------------------------------------------------------------------------

class TestFallbackMechanism:
    
    @pytest.mark.asyncio
    async def test_uses_fallback_when_opencode_unavailable(self, sample_log, mock_analyzer):
        analyzer = OpenCodeAnalyzer(
            server_url="http://unreachable-host:9999",
            fallback_analyzer=mock_analyzer,
            max_retries=0,  # No retries for faster test
        )
        
        # Should not raise, should use fallback
        result = await analyzer.analyze(sample_log)
        
        assert isinstance(result, RawAnalysis)
        assert result.summary is not None
        assert result.root_cause is not None
    
    @pytest.mark.asyncio
    async def test_raises_error_when_no_fallback(self, sample_log):
        analyzer = OpenCodeAnalyzer(
            server_url="http://unreachable-host:9999",
            fallback_analyzer=None,
            max_retries=0,
        )
        
        with pytest.raises(AnalysisError):
            await analyzer.analyze(sample_log)
    
    @pytest.mark.asyncio
    async def test_set_fallback_analyzer(self, sample_log, mock_analyzer):
        analyzer = OpenCodeAnalyzer(
            server_url="http://unreachable-host:9999",
            fallback_analyzer=None,
            max_retries=0,
        )
        
        assert analyzer._fallback_analyzer is None
        
        analyzer.set_fallback_analyzer(mock_analyzer)
        assert analyzer._fallback_analyzer is mock_analyzer
        
        # Should now work with fallback
        result = await analyzer.analyze(sample_log)
        assert isinstance(result, RawAnalysis)


# ---------------------------------------------------------------------------
# Circuit breaker integration
# ---------------------------------------------------------------------------

class TestCircuitBreakerIntegration:
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_tracks_failures(self, sample_log):
        analyzer = OpenCodeAnalyzer(
            server_url="http://unreachable-host:9999",
            max_retries=0,
        )
        
        # Verify initial state
        assert analyzer.circuit_breaker._stats.total_calls == 0
        
        # Trigger failures
        for _ in range(3):
            try:
                await analyzer.analyze(sample_log)
            except AnalysisError:
                pass
        
        # Circuit breaker should have tracked the failures
        assert analyzer.circuit_breaker._stats.failed_calls == 3
        assert analyzer.circuit_breaker.is_open, "Circuit should be open after failure threshold"
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_rejects_when_open(self, sample_log):
        """When circuit is open, requests should fail fast."""
        analyzer = OpenCodeAnalyzer(
            server_url="http://unreachable-host:9999",
            max_retries=0,
        )
        
        # Trigger circuit open
        for _ in range(3):
            try:
                await analyzer.analyze(sample_log)
            except AnalysisError:
                pass
        
        assert analyzer.circuit_breaker.is_open
        
        # Next request should attempt fallback (if configured)
        # Since no fallback, it should raise AnalysisError
        analyzer._fallback_analyzer = MockAnalyzer()
        result = await analyzer.analyze(sample_log)
        assert isinstance(result, RawAnalysis)
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_recovery(self, sample_log):
        """Test circuit breaker can transition from open to half-open after timeout."""
        analyzer = OpenCodeAnalyzer(
            server_url="http://localhost:4096",
            max_retries=0,
        )
        
        # Open the circuit manually
        analyzer.circuit_breaker._state = CircuitState.OPEN
        analyzer.circuit_breaker._last_state_change = time.monotonic() - 31  # Past timeout
        
        # The state property should now return HALF_OPEN since timeout has passed
        assert analyzer.circuit_breaker.state.value == "half_open"


# ---------------------------------------------------------------------------
# Retry mechanism
# ---------------------------------------------------------------------------

class TestRetryMechanism:
    
    @pytest.mark.asyncio
    async def test_retries_on_transient_failure(self, sample_log):
        call_count = 0
        
        async def mock_health_check():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("Connection refused")
            # Success on third attempt
        
        with patch.object(OpenCodeAnalyzer, '_health_check', side_effect=mock_health_check):
            with patch.object(OpenCodeAnalyzer, '_create_session', new_callable=AsyncMock) as mock_session:
                with patch.object(OpenCodeAnalyzer, '_send_analysis_prompt', new_callable=AsyncMock) as mock_send:
                    with patch.object(OpenCodeAnalyzer, '_parse_response') as mock_parse:
                        mock_session.return_value = "test-session"
                        mock_send.return_value = '{"summary": "test", "root_cause": "test"}'
                        mock_parse.return_value = RawAnalysis(summary="test", root_cause="test")
                        
                        analyzer = OpenCodeAnalyzer(
                            server_url="http://localhost:4096",
                            max_retries=3,
                            fallback_analyzer=None,
                        )
                        
                        result = await analyzer.analyze(sample_log)
                        
                        # Should have been called 3 times
                        assert call_count == 3
                        assert result is not None
    
    @pytest.mark.asyncio
    async def test_no_retry_on_analysis_error(self, sample_log):
        """AnalysisErrors (business logic errors) should not be retried."""
        with patch.object(OpenCodeAnalyzer, '_health_check', side_effect=AnalysisError("Business error")):
            analyzer = OpenCodeAnalyzer(
                server_url="http://localhost:4096",
                max_retries=3,
            )
            
            with pytest.raises(AnalysisError):
                await analyzer.analyze(sample_log)


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

class TestCapabilities:
    
    def test_capabilities_include_resilience(self):
        analyzer = OpenCodeAnalyzer(
            server_url="http://localhost:4096",
            max_retries=3,
            fallback_analyzer=MockAnalyzer(),
        )
        
        caps = analyzer.get_capabilities()
        
        assert "resilience" in caps
        assert caps["resilience"]["retry_enabled"] is True
        assert caps["resilience"]["max_retries"] == 3
        assert caps["resilience"]["has_fallback"] is True
        assert "circuit_breaker" in caps["resilience"]
