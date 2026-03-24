"""Tests for circuit breaker implementation."""

import asyncio
import pytest
import time

from app.agent.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
)


@pytest.fixture
def config():
    return CircuitBreakerConfig(
        failure_threshold=3,
        success_threshold=2,
        timeout=2.0,  # Short timeout for testing
    )


@pytest.fixture
def breaker(config):
    return CircuitBreaker(name="test-breaker", config=config)


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

class TestCircuitBreakerStateTransitions:
    
    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self, breaker):
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed
    
    @pytest.mark.asyncio
    async def test_successful_calls_keep_circuit_closed(self, breaker):
        async def succeed():
            return "success"
        
        for _ in range(5):
            result = await breaker.call(succeed)
            assert result == "success"
        
        assert breaker.is_closed
    
    @pytest.mark.asyncio
    async def test_failure_threshold_opens_circuit(self, breaker):
        call_count = 0
        
        async def fail_once():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise ConnectionError("Connection failed")
            return "success"
        
        # First 3 calls should fail but not raise CircuitBreakerOpenError
        for i in range(3):
            with pytest.raises(ConnectionError):
                await breaker.call(fail_once)
        
        assert breaker.is_open, "Circuit should be open after failure threshold"
        assert breaker.stats.consecutive_failures == 3
    
    @pytest.mark.asyncio
    async def test_open_circuit_rejects_requests(self, breaker):
        call_count = 0
        
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Always failing")
        
        # Trigger circuit open
        for _ in range(3):
            try:
                await breaker.call(always_fail)
            except ConnectionError:
                pass
        
        assert breaker.is_open
        
        # Next call should raise CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await breaker.call(always_fail)
        
        assert "circuit breaker" in str(exc_info.value).lower()
        assert exc_info.value.retry_after is not None
    
    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self, breaker):
        call_count = 0
        
        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise ConnectionError("Failing")
            return "success"
        
        # Trigger circuit open
        for _ in range(3):
            try:
                await breaker.call(fail_then_succeed)
            except ConnectionError:
                pass
        
        assert breaker.is_open
        
        # Wait for timeout
        await asyncio.sleep(2.5)
        
        # Should transition to half-open
        assert breaker.state == CircuitState.HALF_OPEN


class TestCircuitBreakerStats:
    
    @pytest.mark.asyncio
    async def test_stats_tracked_correctly(self, breaker):
        async def succeed():
            return "success"
        
        async def fail():
            raise ConnectionError("fail")
        
        # 3 successful calls
        for _ in range(3):
            await breaker.call(succeed)
        
        # 2 failed calls
        for _ in range(2):
            try:
                await breaker.call(fail)
            except ConnectionError:
                pass
        
        stats = breaker.stats
        assert stats.total_calls == 5
        assert stats.successful_calls == 3
        assert stats.failed_calls == 2
        assert stats.consecutive_failures == 2
    
    @pytest.mark.asyncio
    async def test_reset_clears_stats(self, breaker):
        async def fail():
            raise ConnectionError("fail")
        
        for _ in range(3):
            try:
                await breaker.call(fail)
            except ConnectionError:
                pass
        
        assert breaker.is_open
        assert breaker.stats.total_calls == 3
        
        await breaker.reset()
        
        assert breaker.is_closed
        assert breaker.stats.total_calls == 0


class TestCircuitBreakerHealth:
    
    def test_health_status(self, breaker):
        status = breaker.get_health_status()
        
        assert "name" in status
        assert "state" in status
        assert "stats" in status
        assert status["name"] == "test-breaker"
        assert status["state"] == "closed"


class TestCircuitBreakerInternalState:
    """Tests for internal state manipulation and transitions."""
    
    def test_direct_state_transition(self):
        """Test direct state manipulation for testing purposes."""
        cb = CircuitBreaker(name="test", config=CircuitBreakerConfig(timeout=1.0))
        
        # Manually set to OPEN state and past timeout using time.monotonic()
        cb._state = CircuitState.OPEN
        cb._last_state_change = time.monotonic() - 2  # Past timeout
        
        # After timeout, should transition to HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN
        
        # Manually set to HALF_OPEN and then back to OPEN
        cb._state = CircuitState.HALF_OPEN
        assert cb.is_half_open
        
        # Manually set to CLOSED
        cb._state = CircuitState.CLOSED
        assert cb.is_closed
