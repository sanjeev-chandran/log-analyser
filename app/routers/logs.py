"""Log upload and analysis endpoints."""

from fastapi import APIRouter, Depends, status

from app.dependencies import get_analysis_service
from app.schemas.log import LogEntryInput
from app.schemas.analysis import AnalysisResult
from app.services.analysis_service import AnalysisService

router = APIRouter(prefix="/logs", tags=["logs"])


@router.post(
    "/analyze",
    response_model=AnalysisResult,
    status_code=status.HTTP_201_CREATED,
    summary="Upload log and get immediate analysis",
    description="Accepts a JSON-structured log entry, analyzes it using AI, "
    "and returns an RCA report.",
)
async def analyze_log(
    log_input: LogEntryInput,
    analysis_service: AnalysisService = Depends(get_analysis_service),
) -> AnalysisResult:
    """Upload a log entry and get immediate RCA analysis."""
    return await analysis_service.analyze_log(log_input.model_dump())
