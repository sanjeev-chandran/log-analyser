"""Repository for analysis_results table operations."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func

from app.core.logger import get_logger
from app.database import Database
from app.models.analysis import AnalysisResult as AnalysisResultModel
from app.models.log_entry import LogEntry

logger = get_logger(__name__)


@dataclass
class AnalysisFilters:
    """Query filters for listing analyses."""
    service: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class AnalysisRepository:
    """Pure data-access layer for analysis results."""

    async def find_by_id(self, analysis_id: UUID) -> Optional[AnalysisResultModel]:
        """Return the analysis matching *analysis_id*, or ``None``."""
        async with Database.session() as session:
            result = await session.execute(
                select(AnalysisResultModel).where(
                    AnalysisResultModel.id == analysis_id
                )
            )
            return result.scalar_one_or_none()

    async def find_by_log_id(self, log_id: UUID) -> Optional[AnalysisResultModel]:
        """Return the analysis linked to *log_id*, or ``None``."""
        async with Database.session() as session:
            result = await session.execute(
                select(AnalysisResultModel).where(
                    AnalysisResultModel.log_entry_id == log_id
                )
            )
            return result.scalar_one_or_none()

    async def create(self, model: AnalysisResultModel) -> AnalysisResultModel:
        """Insert an analysis result (uses current session if one exists)."""
        async with Database.session() as session:
            session.add(model)
            await session.flush()
            logger.debug(
                "Analysis result inserted",
                extra={"analysis_id": str(model.id)},
            )
            return model

    async def list_with_count(
        self,
        skip: int,
        limit: int,
        filters: AnalysisFilters,
    ) -> Tuple[List[AnalysisResultModel], int]:
        """
        Return ``(items, total_count)`` applying *filters* and pagination.

        Results are ordered by ``analyzed_at`` descending.
        """
        async with Database.session() as session:
            base_query = select(AnalysisResultModel).join(
                LogEntry, AnalysisResultModel.log_entry_id == LogEntry.id
            )
            count_query = (
                select(func.count())
                .select_from(AnalysisResultModel)
                .join(LogEntry, AnalysisResultModel.log_entry_id == LogEntry.id)
            )

            if filters.service is not None:
                base_query = base_query.where(LogEntry.source == filters.service)
                count_query = count_query.where(LogEntry.source == filters.service)

            if filters.start_date is not None:
                base_query = base_query.where(
                    AnalysisResultModel.analyzed_at >= filters.start_date
                )
                count_query = count_query.where(
                    AnalysisResultModel.analyzed_at >= filters.start_date
                )

            if filters.end_date is not None:
                base_query = base_query.where(
                    AnalysisResultModel.analyzed_at <= filters.end_date
                )
                count_query = count_query.where(
                    AnalysisResultModel.analyzed_at <= filters.end_date
                )

            total_result = await session.execute(count_query)
            total = total_result.scalar()

            query = (
                base_query.order_by(AnalysisResultModel.analyzed_at.desc())
                .offset(skip)
                .limit(limit)
            )
            result = await session.execute(query)
            items = list(result.scalars().all())

        logger.debug(
            "Analysis list query completed",
            extra={"total": total, "returned": len(items)},
        )
        return items, total
