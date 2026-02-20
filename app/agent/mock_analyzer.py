"""Mock AI analyzer for development and testing."""

import asyncio
import random
from typing import Any, Dict

from app.core.logger import get_logger
from app.agent.ai_analyzer import AIAnalyzerInterface, RawAnalysis, ComponentAnalysis
from app.services.log_parser import ParsedLog

logger = get_logger(__name__)


class MockAnalyzer(AIAnalyzerInterface):
    """
    Mock AI analyzer for development and testing.
    Returns structured mock data with realistic patterns.
    """

    def __init__(self, simulate_delay: bool = True, delay_ms: tuple = (100, 500)):
        """
        Initialize mock analyzer.

        Args:
            simulate_delay: Whether to simulate processing delay
            delay_ms: Range (min, max) of delay in milliseconds
        """
        self.simulate_delay = simulate_delay
        self.delay_ms = delay_ms

    async def analyze(self, log: ParsedLog) -> RawAnalysis:
        """
        Analyze log and return mock analysis.

        Args:
            log: Parsed log data

        Returns:
            RawAnalysis with mock data
        """
        logger.debug(
            "MockAnalyzer invoked",
            extra={"service": log.service, "level": log.level},
        )

        # Simulate processing delay
        if self.simulate_delay:
            delay = random.randint(*self.delay_ms) / 1000.0
            await asyncio.sleep(delay)

        # Generate analysis based on log content patterns
        result = self._generate_analysis(log)
        logger.debug(
            "MockAnalyzer completed",
            extra={"pattern": result.summary[:60], "confidence": round(result.confidence, 3)},
        )
        return result

    def get_capabilities(self) -> Dict[str, Any]:
        """Return mock capabilities."""
        return {
            "name": "MockAnalyzer",
            "version": "1.0.0",
            "supports_streaming": False,
            "max_context_length": 4096,
            "supported_languages": ["python", "javascript", "java", "go", "ruby"],
            "analysis_types": ["error_analysis", "root_cause", "components"]
        }

    def _generate_analysis(self, log: ParsedLog) -> RawAnalysis:
        """Generate realistic mock analysis based on log patterns."""
        message = log.message.lower()

        # Detect patterns in the log message
        if "database" in message or "sql" in message or "connection" in message:
            return self._database_error_analysis(log)
        elif "timeout" in message or "timed out" in message:
            return self._timeout_error_analysis(log)
        elif "memory" in message or "heap" in message:
            return self._memory_error_analysis(log)
        elif "authentication" in message or "auth" in message or "unauthorized" in message:
            return self._auth_error_analysis(log)
        elif "api" in message or "http" in message or "request" in message:
            return self._api_error_analysis(log)
        else:
            return self._generic_error_analysis(log)

    def _database_error_analysis(self, log: ParsedLog) -> RawAnalysis:
        """Generate analysis for database-related errors."""
        return RawAnalysis(
            summary=f"Database connection issue in {log.service}",
            root_cause=f"The {log.service} failed to establish or maintain a connection to the database. "
                      f"This could be due to connection pool exhaustion, network issues, or database server overload.",
            components=[
                ComponentAnalysis(name=log.service, type="service", impact_level="critical"),
                ComponentAnalysis(name="postgres-db", type="database", impact_level="high"),
                ComponentAnalysis(name="connection-pool", type="infrastructure", impact_level="high")
            ],
            confidence=random.uniform(0.85, 0.95)
        )

    def _timeout_error_analysis(self, log: ParsedLog) -> RawAnalysis:
        """Generate analysis for timeout errors."""
        return RawAnalysis(
            summary=f"Operation timeout in {log.service}",
            root_cause=f"An operation in {log.service} exceeded the configured timeout threshold. "
                      f"This typically occurs when dependent services are slow or unresponsive.",
            components=[
                ComponentAnalysis(name=log.service, type="service", impact_level="high"),
                ComponentAnalysis(name="downstream-service", type="service", impact_level="medium"),
                ComponentAnalysis(name="network-layer", type="infrastructure", impact_level="medium")
            ],
            confidence=random.uniform(0.80, 0.90)
        )

    def _memory_error_analysis(self, log: ParsedLog) -> RawAnalysis:
        """Generate analysis for memory-related errors."""
        return RawAnalysis(
            summary=f"Memory resource issue in {log.service}",
            root_cause=f"The {log.service} is experiencing memory pressure, which could lead to "
                      f"out-of-memory errors or degraded performance. This may be caused by memory leaks "
                      f"or insufficient memory allocation.",
            components=[
                ComponentAnalysis(name=log.service, type="service", impact_level="critical"),
                ComponentAnalysis(name="memory-heap", type="infrastructure", impact_level="high"),
                ComponentAnalysis(name="garbage-collector", type="infrastructure", impact_level="medium")
            ],
            confidence=random.uniform(0.88, 0.98)
        )

    def _auth_error_analysis(self, log: ParsedLog) -> RawAnalysis:
        """Generate analysis for authentication errors."""
        return RawAnalysis(
            summary=f"Authentication failure in {log.service}",
            root_cause=f"The {log.service} encountered an authentication error. "
                      f"This could be due to expired credentials, invalid tokens, or authentication service issues.",
            components=[
                ComponentAnalysis(name=log.service, type="service", impact_level="high"),
                ComponentAnalysis(name="auth-service", type="service", impact_level="high"),
                ComponentAnalysis(name="token-store", type="cache", impact_level="medium")
            ],
            confidence=random.uniform(0.82, 0.92)
        )

    def _api_error_analysis(self, log: ParsedLog) -> RawAnalysis:
        """Generate analysis for API-related errors."""
        return RawAnalysis(
            summary=f"API error in {log.service}",
            root_cause=f"The {log.service} encountered an error while processing an API request. "
                      f"This could indicate issues with request validation, rate limiting, or downstream API failures.",
            components=[
                ComponentAnalysis(name=log.service, type="service", impact_level="high"),
                ComponentAnalysis(name="api-gateway", type="api", impact_level="medium"),
                ComponentAnalysis(name="rate-limiter", type="infrastructure", impact_level="low")
            ],
            confidence=random.uniform(0.78, 0.88)
        )

    def _generic_error_analysis(self, log: ParsedLog) -> RawAnalysis:
        """Generate generic analysis for unrecognized error patterns."""
        return RawAnalysis(
            summary=f"Error detected in {log.service}",
            root_cause=f"An error occurred in {log.service}. The log message indicates: {log.message[:100]}. "
                      f"Further investigation is needed to determine the root cause.",
            components=[
                ComponentAnalysis(name=log.service, type="service", impact_level="medium"),
                ComponentAnalysis(name="application-layer", type="infrastructure", impact_level="medium")
            ],
            confidence=random.uniform(0.60, 0.75)
        )
