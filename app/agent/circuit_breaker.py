"""Circuit breaker pattern implementation for resilient service calls.

The circuit breaker prevents cascading failures by temporarily stopping
requests to a failing service, allowing it time to recover.
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, TypeVar, Any

from app.core.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation, requests pass through
    OPEN = "open"           # Circuit is tripped, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service has recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    failure_threshold: int = 5          # Number of failures before opening circuit
    success_threshold: int = 2          # Number of successes in half-open before closing
    timeout: float = 30.0              # Seconds before attempting half-open
    half_open_max_calls: int = 3       # Max concurrent calls in half-open state


@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker monitoring."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    circuit_open_count: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and request is rejected."""
    def __init__(self, message: str = "Circuit breaker is open", retry_after: Optional[float] = None):
        self.message = message
        self.retry_after = retry_after
        super().__init__(self.message)


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.
    
    Prevents cascading failures by tracking service health and temporarily
    blocking requests when a service is unhealthy.
    
    States:
        CLOSED: Normal operation, all requests pass through
        OPEN: Service is failing, requests are rejected immediately
        HALF_OPEN: Testing recovery, limited requests allowed through
    """
    
    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._stats = CircuitBreakerStats()
        self._last_state_change = time.monotonic()
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state, checking for timeout transition."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_state_change
            if elapsed >= self.config.timeout:
                return CircuitState.HALF_OPEN
        return self._state
    
    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN
    
    @property
    def is_half_open(self) -> bool:
        return self.state == CircuitState.HALF_OPEN
    
    @property
    def stats(self) -> CircuitBreakerStats:
        return self._stats
    
    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute a function through the circuit breaker.
        
        Args:
            func: Async function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
            
        Returns:
            Result of the function call
            
        Raises:
            CircuitBreakerOpenError: If circuit is open
            Exception: Any exception from the underlying function
        """
        current_state = self.state
        
        if current_state == CircuitState.OPEN:
            retry_after = self.config.timeout - (time.monotonic() - self._last_state_change)
            logger.warning(
                f"Circuit breaker '{self.name}' is OPEN, rejecting request",
                extra={"retry_after_seconds": max(0, retry_after)}
            )
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is open, service unavailable",
                retry_after=max(0, retry_after)
            )
        
        async with self._lock:
            # Double-check state after acquiring lock
            if self.state == CircuitState.OPEN:
                retry_after = self.config.timeout - (time.monotonic() - self._last_state_change)
                raise CircuitBreakerOpenError(
                    f"Circuit breaker '{self.name}' is open",
                    retry_after=max(0, retry_after)
                )
            
            self._stats.total_calls += 1
        
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as exc:
            await self._on_failure(exc)
            raise
    
    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            self._stats.successful_calls += 1
            self._stats.consecutive_successes += 1
            self._stats.consecutive_failures = 0
            self._stats.last_success_time = time.monotonic()
            
            if self._state == CircuitState.HALF_OPEN:
                if self._stats.consecutive_successes >= self.config.success_threshold:
                    await self._transition_to(CircuitState.CLOSED)
                    logger.info(
                        f"Circuit breaker '{self.name}' CLOSED after recovery",
                        extra={"stats": self._get_stats_dict()}
                    )
    
    async def _on_failure(self, exc: Exception) -> None:
        """Handle failed call."""
        async with self._lock:
            self._stats.failed_calls += 1
            self._stats.consecutive_failures += 1
            self._stats.consecutive_successes = 0
            self._stats.last_failure_time = time.monotonic()
            
            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open state opens the circuit again
                await self._transition_to(CircuitState.OPEN)
                logger.warning(
                    f"Circuit breaker '{self.name}' OPEN after half-open failure",
                    extra={"error": str(exc), "stats": self._get_stats_dict()}
                )
            elif self._state == CircuitState.CLOSED:
                if self._stats.consecutive_failures >= self.config.failure_threshold:
                    await self._transition_to(CircuitState.OPEN)
                    self._stats.circuit_open_count += 1
                    logger.warning(
                        f"Circuit breaker '{self.name}' OPEN after {self._stats.consecutive_failures} failures",
                        extra={"error": str(exc), "stats": self._get_stats_dict()}
                    )
    
    async def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old_state = self._state
        self._state = new_state
        self._last_state_change = time.monotonic()
        
        if new_state == CircuitState.HALF_OPEN:
            self._stats.consecutive_successes = 0
        
        logger.debug(
            f"Circuit breaker '{self.name}' state change: {old_state.value} -> {new_state.value}"
        )
    
    async def reset(self) -> None:
        """Reset circuit breaker to closed state."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._stats = CircuitBreakerStats()
            self._last_state_change = time.monotonic()
            logger.info(f"Circuit breaker '{self.name}' reset to CLOSED")
    
    def _get_stats_dict(self) -> dict:
        """Get stats as dictionary for logging."""
        return {
            "total_calls": self._stats.total_calls,
            "successful_calls": self._stats.successful_calls,
            "failed_calls": self._stats.failed_calls,
            "consecutive_failures": self._stats.consecutive_failures,
            "circuit_open_count": self._stats.circuit_open_count,
        }
    
    def get_health_status(self) -> dict:
        """Get health status for monitoring."""
        return {
            "name": self.name,
            "state": self.state.value,
            "stats": self._get_stats_dict(),
            "last_failure_time": self._stats.last_failure_time,
            "last_success_time": self._stats.last_success_time,
        }
