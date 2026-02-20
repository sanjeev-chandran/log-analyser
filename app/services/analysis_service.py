"""Service layer for analysis orchestration (business logic only).

All persistence is delegated to repositories.  ``Database.session()``
uses a ContextVar so nested calls join the existing transaction —
just like Hibernate's ``getCurrentSession()``.
"""

from uuid import UUID

from app.core.logger import get_logger
from app.database import Database
from app.models.analysis import AnalysisResult as AnalysisResultModel
from app.schemas.analysis import AnalysisResult, AnalysisListResponse
from app.core.exceptions import AnalysisNotFoundError
from app.services.log_service import LogService
from app.services.rca_generator import RCAGenerator
from app.repositories.analysis_repository import AnalysisRepository, AnalysisFilters

logger = get_logger(__name__)


def _model_to_schema(model: AnalysisResultModel) -> AnalysisResult:
    """Convert a DB model to the response schema."""
    return AnalysisResult(
        id=model.id,
        log_id=model.log_entry_id,
        summary=model.summary,
        root_cause=model.root_cause,
        affected_components=model.components or [],
        confidence=model.confidence,
        analyzed_at=model.analyzed_at,
        processing_time_ms=model.processing_time_ms,
    )


class AnalysisService:
    """Orchestrates the analyse-log workflow."""

    def __init__(
        self,
        log_service: LogService,
        analysis_repository: AnalysisRepository,
        rca_generator: RCAGenerator,
    ):
        self._log_service = log_service
        self._analysis_repo = analysis_repository
        self._rca_generator = rca_generator

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def analyze_log(self, log_data: dict) -> AnalysisResult:
        """
        Full analysis workflow:
        parse -> deduplicate -> AI analyse -> persist log + result.

        Raises:
            DuplicateLogError, LogParseError, AnalysisError
        """
        logger.debug("Starting log analysis workflow")

        # 1. Parse + deduplicate (LogService owns parser and log repo)
        parsed_log, existing = await self._log_service.parse_and_deduplicate(log_data)
        if existing is not None:
            logger.debug(
                "Returning cached analysis for duplicate log",
                extra={"log_hash": parsed_log.log_hash, "service": parsed_log.service},
            )
            return _model_to_schema(existing.analysis)

        # 2. Run AI analysis (no DB needed)
        logger.debug(
            "Running AI analysis",
            extra={"service": parsed_log.service, "level": parsed_log.level},
        )
        analysis_result = await self._rca_generator.generate(
            log=parsed_log,
            log_entry_id=None,
        )

        # 3. Build the analysis model
        analysis_model = AnalysisResultModel(
            id=analysis_result.id,
            summary=analysis_result.summary,
            root_cause=analysis_result.root_cause,
            components=[
                c.model_dump() for c in analysis_result.affected_components
            ],
            confidence=analysis_result.confidence,
            analyzed_at=analysis_result.analyzed_at,
            processing_time_ms=analysis_result.processing_time_ms,
        )

        # 4. Persist log + analysis in a single transaction
        async with Database.session() as session:
            log_entry = await self._log_service.create(parsed_log)
            analysis_model.log_entry_id = log_entry.id
            await self._analysis_repo.create(analysis_model)
            await session.commit()

        logger.info(
            "Analysis completed and persisted",
            extra={
                "analysis_id": str(analysis_result.id),
                "log_hash": parsed_log.log_hash,
                "confidence": analysis_result.confidence,
                "processing_time_ms": analysis_result.processing_time_ms,
            },
        )
        return analysis_result

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_by_id(self, analysis_id: UUID) -> AnalysisResult:
        """
        Retrieve a single analysis by primary key.

        Raises:
            AnalysisNotFoundError
        """
        logger.debug("Fetching analysis", extra={"analysis_id": str(analysis_id)})
        model = await self._analysis_repo.find_by_id(analysis_id)
        if model is None:
            raise AnalysisNotFoundError(str(analysis_id))
        return _model_to_schema(model)

    async def get_by_log_id(self, log_id: UUID) -> AnalysisResult:
        """
        Retrieve the analysis for a log entry.

        Raises:
            LogNotFoundError, AnalysisNotFoundError
        """
        logger.debug("Fetching analysis by log ID", extra={"log_id": str(log_id)})
        await self._log_service.find_by_id(log_id)

        model = await self._analysis_repo.find_by_log_id(log_id)
        if model is None:
            raise AnalysisNotFoundError(
                f"No analysis found for log entry: {log_id}"
            )
        return _model_to_schema(model)

    async def list_analyses(
        self,
        skip: int,
        limit: int,
        filters: AnalysisFilters,
    ) -> AnalysisListResponse:
        """Return a paginated, filterable list of analyses."""
        logger.debug(
            "Listing analyses",
            extra={"skip": skip, "limit": limit, "service_filter": filters.service},
        )
        items, total = await self._analysis_repo.list_with_count(
            skip, limit, filters
        )
        page = (skip // limit) + 1 if limit > 0 else 1
        return AnalysisListResponse(
            items=[_model_to_schema(a) for a in items],
            total=total,
            page=page,
            page_size=limit,
        )
