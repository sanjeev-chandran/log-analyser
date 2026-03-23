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
"""

import json
import time
from typing import Any, Dict, List, Optional

import httpx

from app.core.logger import get_logger
from app.core.exceptions import AnalysisError
from app.agent.ai_analyzer import AIAnalyzerInterface, ComponentAnalysis, RawAnalysis
from app.services.log_parser import ParsedLog

logger = get_logger(__name__)

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
    """

    def __init__(
        self,
        server_url: str = "http://localhost:8001",
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
        password: Optional[str] = None,
        username: str = "opencode",
        timeout: float = 60.0,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._provider_id = provider_id
        self._model_id = model_id
        self._timeout = timeout

        # Build httpx auth if password supplied
        self._auth: Optional[httpx.BasicAuth] = None
        if password:
            self._auth = httpx.BasicAuth(username=username, password=password)

        self._client = httpx.AsyncClient(
            base_url=self._server_url,
            timeout=httpx.Timeout(timeout),
            auth=self._auth,
        )

        logger.info(
            "OpenCodeAnalyzer initialised",
            extra={
                "server_url": self._server_url,
                "provider_id": provider_id or "default",
                "model_id": model_id or "default",
            },
        )

    # ------------------------------------------------------------------
    # AIAnalyzerInterface
    # ------------------------------------------------------------------

    async def analyze(self, log: ParsedLog) -> RawAnalysis:
        """Create a session on the OpenCode server, send the log via /sre command, and parse the response."""
        start = time.monotonic()
        session_id: Optional[str] = None

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
                extra={"elapsed_ms": elapsed_ms, "session_id": session_id},
            )

            return self._parse_response(raw_text, log)

        except AnalysisError:
            raise
        except httpx.ConnectError as exc:
            logger.error("Cannot connect to OpenCode server", extra={"error": str(exc)})
            raise AnalysisError(
                f"Cannot connect to OpenCode server at {self._server_url}",
                {"error": str(exc), "service": log.service},
            )
        except httpx.TimeoutException as exc:
            logger.error("OpenCode server request timed out", extra={"error": str(exc)})
            raise AnalysisError(
                "OpenCode server request timed out",
                {"error": str(exc), "service": log.service, "timeout": self._timeout},
            )
        except Exception as exc:
            logger.error("OpenCode analysis failed: %s", str(exc), exc_info=True)
            raise AnalysisError(
                f"OpenCode analysis failed: {str(exc)}",
                {"error": str(exc), "service": log.service},
            )
        finally:
            # Best-effort cleanup: delete the session so we don't leak state
            if session_id:
                await self._delete_session(session_id)

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "name": "OpenCodeAnalyzer",
            "version": "1.0.0",
            "server_url": self._server_url,
            "provider_id": self._provider_id or "default",
            "model_id": self._model_id or "default",
            "supports_streaming": False,
            "max_context_length": 128000,
            "supported_languages": ["python", "javascript", "java", "go", "ruby", "rust", "c++"],
            "analysis_types": ["error_analysis", "root_cause", "components"],
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
