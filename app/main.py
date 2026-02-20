"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import APP_NAME, VERSION, DEBUG, ALLOWED_ORIGINS, API_V1_PREFIX
from app.core.logger import get_logger
from app.middleware import RequestIDMiddleware
from app.core.exceptions import (
    LogParseError,
    AnalysisError,
    LogNotFoundError,
    AnalysisNotFoundError,
    DuplicateLogError,
)
from app.routers import logs, analysis

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application started", extra={"version": VERSION, "debug": DEBUG})
    yield
    logger.info("Application shutting down")

# ---------------------------------------------------------------------------
# App initialization
# ---------------------------------------------------------------------------

app = FastAPI(
    title=APP_NAME,
    version=VERSION,
    description="A service that accepts application-level error logs in JSON format, "
    "analyzes them using AI, and generates Root Cause Analysis (RCA) reports.",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RequestID middleware — generates a unique ID per request, stores it in a
# ContextVar, and injects it into every JSON log line automatically.
# Added after CORS so it executes first (Starlette LIFO order).
app.add_middleware(RequestIDMiddleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(logs.router, prefix=API_V1_PREFIX)
app.include_router(analysis.router, prefix=API_V1_PREFIX)

# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(LogParseError)
async def log_parse_error_handler(request: Request, exc: LogParseError) -> JSONResponse:
    """Handle invalid log format errors."""
    logger.warning(
        "Log parse error: %s",
        exc.message,
        extra={"path": request.url.path, "details": exc.details},
    )
    return JSONResponse(
        status_code=400,
        content={
            "error": "Bad Request",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(DuplicateLogError)
async def duplicate_log_error_handler(request: Request, exc: DuplicateLogError) -> JSONResponse:
    """Handle duplicate log entry errors."""
    logger.info(
        "Duplicate log rejected: %s",
        exc.message,
        extra={"path": request.url.path, "details": exc.details},
    )
    return JSONResponse(
        status_code=409,
        content={
            "error": "Conflict",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(LogNotFoundError)
async def log_not_found_error_handler(request: Request, exc: LogNotFoundError) -> JSONResponse:
    """Handle log not found errors."""
    logger.info(
        "Log not found: %s",
        exc.message,
        extra={"path": request.url.path, "details": exc.details},
    )
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(AnalysisNotFoundError)
async def analysis_not_found_error_handler(
    request: Request, exc: AnalysisNotFoundError
) -> JSONResponse:
    """Handle analysis not found errors."""
    logger.info(
        "Analysis not found: %s",
        exc.message,
        extra={"path": request.url.path, "details": exc.details},
    )
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(AnalysisError)
async def analysis_error_handler(request: Request, exc: AnalysisError) -> JSONResponse:
    """Handle AI analysis failure errors."""
    logger.error(
        "Analysis failed: %s",
        exc.message,
        extra={"path": request.url.path, "details": exc.details},
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": exc.message,
            "details": exc.details,
        },
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health", tags=["health"], summary="Health check")
async def health_check() -> dict:
    """Check that the service is running."""
    return {
        "status": "healthy",
        "service": APP_NAME,
        "version": VERSION,
    }
