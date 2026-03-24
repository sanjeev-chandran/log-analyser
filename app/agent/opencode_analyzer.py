"""OpenCode AI analyzer — uses a running OpenCode server for log analysis.

The OpenCode server (``opencode serve``) exposes an HTTP API that proxies
requests to whichever LLM provider is configured in the OpenCode instance
(Anthropic, OpenAI, Ollama, etc.).  This module creates a session, sends
the log entry as a structured-output prompt, and parses the result.

The only hard dependency is ``httpx`` (already in requirements.txt).
No direct LLM SDK is required.

Configuration is read from environment variables via ``app.config``:
    OPENCODE_SERVER_URL   – base URL of the OpenCode server (default http://localhost:4096)
    OPENCODE_PROVIDER_ID  – provider id configured in OpenCode (e.g. "anthropic", "openai")
    OPENCODE_MODEL_ID     – model id to use (e.g. "claude-sonnet-4-20250514")
    OPENCODE_SERVER_PASSWORD – optional basic-auth password
    OPENCODE_SERVER_USERNAME – optional basic-auth username (default "opencode")

Resilience features:
    - Retry logic with exponential backoff for transient failures
    - Circuit breaker to prevent cascading failures
    - Graceful degradation support via fallback analyzers
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

import httpx

from app.core.logger import get_logger
from app.core.exceptions import AnalysisError
from app.agent.ai_analyzer import AIAnalyzerInterface, ComponentAnalysis, RawAnalysis
from app.agent.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerOpenError, CircuitState
from app.services.log_parser import ParsedLog

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY = 1.0  # seconds
DEFAULT_RETRY_MAX_DELAY = 10.0  # seconds


def calculate_retry_delay(attempt: int, base_delay: float = DEFAULT_RETRY_BASE_DELAY, 
                           max_delay: float = DEFAULT_RETRY_MAX_DELAY) -> float:
    """Calculate exponential backoff delay with jitter.
    
    Args:
        attempt: Current retry attempt (0-indexed)
        base_delay: Base delay in seconds
        max_delay: Maximum delay cap in seconds
        
    Returns:
        Delay in seconds with jitter
    """
    import random
    delay = min(base_delay * (2 ** attempt), max_delay)
    # Add jitter (±20%)
    jitter = delay * 0.2 * (2 * random.random() - 1)
    return max(0.1, delay + jitter)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

# The system prompt is configured in OpenCode as the /sre command.
# No need to inject it from this service — just prefix messages with /sre.


def _build_user_prompt(log: ParsedLog) -> str:
    """Build the user message from a parsed log entry."""
    parts = [
        f"Timestamp : {log.timestamp.isoformat()}",
        f"Level     : {log.level}",
        f"Service   : {log.service}",
        f"Message   : {log.message}",
    ]
    if log.trace_id:
        parts.append(f"Trace ID  : {log.trace_id}")
    if log.metadata:
        parts.append(f"Metadata  : {json.dumps(log.metadata, default=str)}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Analyzer implementation
# ---------------------------------------------------------------------------


class OpenCodeAnalyzer(AIAnalyzerInterface):
    """Log analyser that delegates to a running OpenCode server.

    Parameters
    ----------
    server_url : str
        Base URL of the OpenCode server (e.g. ``http://localhost:4096``).
    provider_id : str | None
        OpenCode provider id (e.g. ``"anthropic"``).  If *None* the server
        will use its default provider.
    model_id : str | None
        Model id within the provider (e.g. ``"claude-sonnet-4-20250514"``).
        If *None* the server will use its default model.
    password : str | None
        Password for HTTP basic auth (``OPENCODE_SERVER_PASSWORD``).
    username : str
        Username for HTTP basic auth (default ``"opencode"``).
    timeout : float
        HTTP request timeout in seconds.
    max_retries : int
        Maximum number of retry attempts for transient failures.
    retry_base_delay : float
        Base delay for exponential backoff in seconds.
    fallback_analyzer : AIAnalyzerInterface | None
        Analyzer to use as fallback when OpenCode is unavailable.
    """

    def __init__(
        self,
        server_url: str = "http://localhost:8001",
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
        password: Optional[str] = None,
        username: str = "opencode",
        timeout: float = 60.0,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
        fallback_analyzer: Optional[AIAnalyzerInterface] = None,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._provider_id = provider_id
        self._model_id = model_id
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._fallback_analyzer = fallback_analyzer

        # Build httpx auth if password supplied
        self._auth: Optional[httpx.BasicAuth] = None
        if password:
            self._auth = httpx.BasicAuth(username=username, password=password)

        self._client = httpx.AsyncClient(
            base_url=self._server_url,
            timeout=httpx.Timeout(timeout),
            auth=self._auth,
        )

        # Initialize circuit breaker for connection resilience
        self._circuit_breaker = CircuitBreaker(
            name=f"opencode-{server_url}",
            config=CircuitBreakerConfig(
                failure_threshold=3,
                success_threshold=2,
                timeout=30.0,
            )
        )

        logger.info(
            "OpenCodeAnalyzer initialised",
            extra={
                "server_url": self._server_url,
                "provider_id": provider_id or "default",
                "model_id": model_id or "default",
                "max_retries": max_retries,
                "circuit_breaker": "enabled",
            },
        )

    def set_fallback_analyzer(self, analyzer: AIAnalyzerInterface) -> None:
        """Set a fallback analyzer to use when OpenCode is unavailable."""
        self._fallback_analyzer = analyzer
        logger.debug("Fallback analyzer configured", extra={"analyzer": type(analyzer).__name__})

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Get the circuit breaker instance for monitoring."""
        return self._circuit_breaker

    # ------------------------------------------------------------------
    # AIAnalyzerInterface
    # ------------------------------------------------------------------

    async def analyze(self, log: ParsedLog) -> RawAnalysis:
        """Create a session on the OpenCode server, send the log via /sre command, and parse the response.
        
        Implements retry logic with exponential backoff for transient failures.
        Falls back to configured fallback analyzer if OpenCode remains unavailable.
        """
        start = time.monotonic()
        session_id: Optional[str] = None
        last_exception: Optional[Exception] = None

        # Check circuit breaker first - fast rejection if circuit is open
        if self._circuit_breaker.is_open:
            logger.warning(
                "Circuit breaker is open, attempting with fallback",
                extra={"server_url": self._server_url}
            )
            return await self._try_fallback_or_fail(log, CircuitBreakerOpenError("Circuit breaker open"))

        for attempt in range(self._max_retries + 1):
            try:
                # 1. Health check — fast-fail if server is unreachable
                await self._health_check()

                # 2. Create a fresh session
                session_id = await self._create_session()

                # 3. Send the log entry with /sre command and get back the AI analysis
                raw_text = await self._send_analysis_prompt(session_id, log)

                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.debug(
                    "OpenCode analysis received",
                    extra={"elapsed_ms": elapsed_ms, "session_id": session_id, "attempts": attempt + 1},
                )

                return self._parse_response(raw_text, log)

            except CircuitBreakerOpenError:
                # Circuit is open, don't retry
                raise

            except AnalysisError:
                # Don't retry AnalysisErrors (business logic errors)
                raise

            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exception = exc
                elapsed_ms = int((time.monotonic() - start) * 1000)
                
                # Record failure in circuit breaker
                await self._record_failure(exc)
                
                if attempt < self._max_retries:
                    delay = calculate_retry_delay(attempt, self._retry_base_delay)
                    logger.warning(
                        f"OpenCode request failed, retrying in {delay:.2f}s",
                        extra={
                            "attempt": attempt + 1,
                            "max_retries": self._max_retries,
                            "error": str(exc),
                            "elapsed_ms": elapsed_ms,
                        }
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "OpenCode request failed after all retries",
                        extra={
                            "attempts": attempt + 1,
                            "error": str(exc),
                            "elapsed_ms": elapsed_ms,
                        }
                    )

            except Exception as exc:
                await self._record_failure(exc)
                logger.error("OpenCode analysis failed: %s", str(exc), exc_info=True)
                raise AnalysisError(
                    f"OpenCode analysis failed: {str(exc)}",
                    {"error": str(exc), "service": log.service},
                )
            finally:
                # Best-effort cleanup: delete the session so we don't leak state
                if session_id:
                    try:
                        await self._delete_session(session_id)
                    except Exception:
                        pass  # Non-critical cleanup

        # All retries exhausted - try fallback or raise
        return await self._try_fallback_or_fail(log, last_exception)

    async def _record_failure(self, exc: Exception) -> None:
        """Record a failure in the circuit breaker."""
        # Simulate failure tracking for circuit breaker
        # The circuit breaker tracks failures through our call pattern
        self._circuit_breaker._stats.failed_calls += 1
        self._circuit_breaker._stats.consecutive_failures += 1
        self._circuit_breaker._stats.consecutive_successes = 0
        self._circuit_breaker._stats.last_failure_time = time.monotonic()
        
        if self._circuit_breaker._stats.consecutive_failures >= self._circuit_breaker.config.failure_threshold:
            if not self._circuit_breaker.is_open:
                self._circuit_breaker._state = CircuitState.OPEN
                self._circuit_breaker._last_state_change = time.monotonic()
                self._circuit_breaker._stats.circuit_open_count += 1
                logger.warning(
                    f"Circuit breaker '{self._circuit_breaker.name}' OPEN after {self._circuit_breaker._stats.consecutive_failures} failures"
                )

    async def _record_success(self) -> None:
        """Record a success in the circuit breaker."""
        self._circuit_breaker._stats.successful_calls += 1
        self._circuit_breaker._stats.consecutive_successes += 1
        self._circuit_breaker._stats.consecutive_failures = 0
        self._circuit_breaker._stats.last_success_time = time.monotonic()

    async def _try_fallback_or_fail(self, log: ParsedLog, last_exception: Optional[Exception]) -> RawAnalysis:
        """Handle analysis failure with fallback to mock analyzer."""
        if self._fallback_analyzer is not None:
            logger.warning(
                "OpenCode unavailable, using fallback analyzer",
                extra={
                    "fallback_analyzer": type(self._fallback_analyzer).__name__,
                    "original_error": str(last_exception) if last_exception else "unknown",
                }
            )
            try:
                result = await self._fallback_analyzer.analyze(log)
                return result
            except Exception as fallback_error:
                logger.error(
                    "Fallback analyzer also failed",
                    extra={"error": str(fallback_error)}
                )
        
        # No fallback available - raise original error
        if isinstance(last_exception, (httpx.ConnectError, httpx.NetworkError)):
            error_type = "connection"
            error_msg = f"Cannot connect to OpenCode server at {self._server_url}"
        elif isinstance(last_exception, httpx.TimeoutException):
            error_type = "timeout"
            error_msg = "OpenCode server request timed out"
        elif isinstance(last_exception, CircuitBreakerOpenError):
            error_type = "circuit_breaker"
            error_msg = f"OpenCode service unavailable (circuit breaker open)"
        else:
            error_type = "unknown"
            error_msg = f"OpenCode analysis failed: {str(last_exception)}"

        logger.error(
            "OpenCode analysis failed with no fallback available",
            extra={"error_type": error_type, "error": str(last_exception)}
        )
        raise AnalysisError(
            error_msg,
            {"error": str(last_exception), "service": log.service, "error_type": error_type},
        )

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "name": "OpenCodeAnalyzer",
            "version": "1.1.0",
            "server_url": self._server_url,
            "provider_id": self._provider_id or "default",
            "model_id": self._model_id or "default",
            "supports_streaming": False,
            "max_context_length": 128000,
            "supported_languages": ["python", "javascript", "java", "go", "ruby", "rust", "c++"],
            "analysis_types": ["error_analysis", "root_cause", "components"],
            "resilience": {
                "retry_enabled": True,
                "max_retries": self._max_retries,
                "circuit_breaker": self._circuit_breaker.state.value,
                "has_fallback": self._fallback_analyzer is not None,
            },
        }

    # ------------------------------------------------------------------
    # OpenCode server helpers
    # ------------------------------------------------------------------

    async def _health_check(self) -> None:
        """Verify the OpenCode server is reachable."""
        resp = await self._client.get("/global/health")
        if resp.status_code != 200:
            raise AnalysisError(
                f"OpenCode server health check failed (HTTP {resp.status_code})",
                {"response": resp.text[:500]},
            )

    async def _create_session(self) -> str:
        """Create a new session and return its id."""
        resp = await self._client.post(
            "/session",
            json={"title": "log-analysis"},
        )
        resp.raise_for_status()
        data = resp.json()

        session_id = data.get("id") or data.get("data", {}).get("id")
        if not session_id:
            raise AnalysisError(
                "OpenCode server returned a session without an id",
                {"response": json.dumps(data)[:500]},
            )
        logger.debug("OpenCode session created", extra={"session_id": session_id})
        return session_id

    async def _send_analysis_prompt(self, session_id: str, log: ParsedLog) -> str:
        """Send the log data as a command and return the AI's JSON string.

        Uses the /session/:id/command endpoint to execute the /sre command
        with the log data as arguments.

        The HTTP response shape (from the OpenCode SDK types) is::

            {
              "info": AssistantMessage,   # metadata: tokens, cost, error …
              "parts": [                  # ordered list of response parts
                { "type": "text",  "text": "…" },     # TextPart
                { "type": "step-start", … },           # StepStartPart
                …
              ]
            }

        Extraction: concatenate all ``TextPart.text`` values.
        """
        user_prompt = _build_user_prompt(log)

        body: Dict[str, Any] = {
            "command": "sre",
            "arguments": user_prompt,
        }

        if self._provider_id and self._model_id:
            body["model"] = {
                "providerID": self._provider_id,
                "modelID": self._model_id,
            }

        resp = await self._client.post(
            f"/session/{session_id}/command",
            timeout=0,
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

        info = data.get("info", {})
        error = info.get("error")
        if error:
            error_name = error.get("name", "UnknownError")
            error_data = error.get("data", {})
            raise AnalysisError(
                f"OpenCode provider error: {error_name}",
                {"error_name": error_name, "error_data": error_data,
                 "service": log.service},
            )

        parts = data.get("parts", [])

        # ── Extract text from TextParts ──────────────────────────────
        #
        # The model responds with JSON in plain text (guided by the
        # system prompt).  We concatenate all TextPart.text values.
        #
        # TextPart shape: { type: "text", text: "..." }
        text_fragments: List[str] = []
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if text:
                    text_fragments.append(text)

        raw_text = "\n".join(text_fragments).strip()
        if raw_text:
            logger.debug(
                "Extracted response from TextParts",
                extra={"session_id": session_id},
            )
            return raw_text

        # ── Nothing usable found ────────────────────────────────────
        logger.warning(
            "OpenCode returned no extractable content",
            extra={
                "session_id": session_id,
                "part_types": [p.get("type") for p in parts if isinstance(p, dict)],
            },
        )
        raise AnalysisError(
            "OpenCode server returned an empty response",
            {"session_id": session_id, "service": log.service},
        )

    async def _delete_session(self, session_id: str) -> None:
        """Best-effort cleanup of the session."""
        try:
            await self._client.delete(f"/session/{session_id}")
        except Exception as exc:
            logger.debug(
                "Failed to delete OpenCode session (non-critical)",
                extra={"session_id": session_id, "error": str(exc)},
            )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, raw_text: str, log: ParsedLog) -> RawAnalysis:
        """Parse the raw JSON string into a ``RawAnalysis``."""
        # Strip markdown fences if the model wrapped the JSON
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = cleaned.index("\n") if "\n" in cleaned else 3
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning(
                "OpenCode returned invalid JSON",
                extra={"raw_text": raw_text[:500], "error": str(exc)},
            )
            raise AnalysisError(
                "AI returned malformed JSON — analysis could not be parsed",
                {"raw_text": raw_text[:500], "error": str(exc), "service": log.service},
            )

        summary = data.get("summary", f"Error detected in {log.service}")
        root_cause = data.get("root_cause", "Unable to determine root cause from AI response.")
        confidence = self._clamp(float(data.get("confidence", 0.5)), 0.0, 1.0)
        components = self._parse_components(data.get("components", []))

        return RawAnalysis(
            summary=summary,
            root_cause=root_cause,
            components=components,
            confidence=confidence,
            raw_text=raw_text,
        )

    @staticmethod
    def _parse_components(raw_components: List[Dict[str, Any]]) -> List[ComponentAnalysis]:
        valid_types = {"service", "database", "cache", "api", "queue", "external", "infrastructure"}
        valid_impacts = {"critical", "high", "medium", "low"}
        components: List[ComponentAnalysis] = []

        for item in raw_components:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "unknown"))
            comp_type = str(item.get("type", "service")).lower()
            impact = str(item.get("impact_level", "medium")).lower()

            if comp_type not in valid_types:
                comp_type = "service"
            if impact not in valid_impacts:
                impact = "medium"

            components.append(ComponentAnalysis(name=name, type=comp_type, impact_level=impact))

        return components

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))
