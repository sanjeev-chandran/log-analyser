"""Analysis query endpoints."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_analysis_service
from app.schemas.analysis import AnalysisResult, AnalysisListResponse
from app.services.analysis_service import AnalysisService
from app.repositories.analysis_repository import AnalysisFilters
from app.config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get(
    "/{analysis_id}",
    response_model=AnalysisResult,
    summary="Get analysis by ID",
    description="Retrieve a specific RCA analysis result by its unique identifier.",
)
async def get_analysis(
    analysis_id: UUID,
    analysis_service: AnalysisService = Depends(get_analysis_service),
) -> AnalysisResult:
    """Get a specific analysis by ID."""
    return await analysis_service.get_by_id(analysis_id)


@router.get(
    "",
    response_model=AnalysisListResponse,
    summary="List analyses",
    description="List all RCA analyses with optional filtering and pagination.",
)
async def list_analyses(
    analysis_service: AnalysisService = Depends(get_analysis_service),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(
        DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Number of records to return",
    ),
    service: Optional[str] = Query(None, description="Filter by service name"),
    start_date: Optional[datetime] = Query(
        None, description="Filter from date (inclusive)"
    ),
    end_date: Optional[datetime] = Query(
        None, description="Filter to date (inclusive)"
    ),
) -> AnalysisListResponse:
    """List analyses with pagination and optional filters."""
    filters = AnalysisFilters(
        service=service,
        start_date=start_date,
        end_date=end_date,
    )
    return await analysis_service.list_analyses(skip, limit, filters)


@router.get(
    "/by-log/{log_id}",
    response_model=AnalysisResult,
    summary="Get analysis for a log entry",
    description="Retrieve the RCA analysis associated with a specific log entry.",
)
async def get_analysis_by_log_id(
    log_id: UUID,
    analysis_service: AnalysisService = Depends(get_analysis_service),
) -> AnalysisResult:
    """Get the analysis result for a specific log entry."""
    return await analysis_service.get_by_log_id(log_id)
