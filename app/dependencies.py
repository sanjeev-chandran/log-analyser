"""FastAPI dependency injection — wires services and providers."""

from app.core.logger import get_logger
from app.services.log_parser import LogParser
from app.agent.ai_analyzer import AIAnalyzerInterface
from app.agent.mock_analyzer import MockAnalyzer
from app.services.rca_generator import RCAGenerator
from app.services.log_service import LogService
from app.services.analysis_service import AnalysisService
from app.repositories.analysis_repository import AnalysisRepository
from app import config

logger = get_logger(__name__)

# -- Stateless repositories (no constructor args) --------------------------
_analysis_repository = AnalysisRepository()

# -- Pure / stateless services ---------------------------------------------
_log_parser = LogParser()


def _build_ai_analyzer() -> AIAnalyzerInterface:
    """Select the AI analyzer based on configuration.

    If ``OPENCODE_SERVER_URL`` is set the real :class:`OpenCodeAnalyzer` is
    used (talks to a running ``opencode serve`` instance); otherwise the
    lightweight :class:`MockAnalyzer` is returned so the app still works in
    development without an OpenCode server.
    
    The OpenCodeAnalyzer is configured with a MockAnalyzer fallback to provide
    graceful degradation when the OpenCode server is unavailable.
    """
    # Create mock analyzer as potential fallback
    mock_analyzer = MockAnalyzer()
    
    if config.OPENCODE_SERVER_URL:
        from app.agent.opencode_analyzer import OpenCodeAnalyzer

        logger.info(
            "Using OpenCodeAnalyzer (server=%s, provider=%s, model=%s)",
            config.OPENCODE_SERVER_URL,
            config.OPENCODE_PROVIDER_ID or "default",
            config.OPENCODE_MODEL_ID or "default",
        )
        analyzer = OpenCodeAnalyzer(
            server_url=config.OPENCODE_SERVER_URL,
            provider_id=config.OPENCODE_PROVIDER_ID,
            model_id=config.OPENCODE_MODEL_ID,
            # password=config.OPENCODE_SERVER_PASSWORD,
            # username=config.OPENCODE_SERVER_USERNAME,
            timeout=config.OPENCODE_TIMEOUT,
            fallback_analyzer=mock_analyzer,
        )
        logger.info(
            "Configured OpenCodeAnalyzer with MockAnalyzer fallback for graceful degradation"
        )
        return analyzer

    logger.info("OPENCODE_SERVER_URL not set — using MockAnalyzer")
    return mock_analyzer


_ai_analyzer: AIAnalyzerInterface = _build_ai_analyzer()
_rca_generator = RCAGenerator(ai_analyzer=_ai_analyzer)

# -- Business services -----------------------------------------------------
_log_service = LogService(log_parser=_log_parser)
_analysis_service = AnalysisService(
    log_service=_log_service,
    analysis_repository=_analysis_repository,
    rca_generator=_rca_generator,
)


# -- FastAPI dependency providers ------------------------------------------

def get_log_parser() -> LogParser:
    return _log_parser


def get_ai_analyzer() -> AIAnalyzerInterface:
    return _ai_analyzer


def get_rca_generator() -> RCAGenerator:
    return _rca_generator


def get_log_service() -> LogService:
    return _log_service


def get_analysis_service() -> AnalysisService:
    return _analysis_service


def get_analysis_repository() -> AnalysisRepository:
    return _analysis_repository
