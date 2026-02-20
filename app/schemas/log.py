"""Pydantic schemas for log entries."""

from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class LogLevel:
    """Log level constants."""
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"
    DEBUG = "DEBUG"
    
    LEVELS = [ERROR, WARN, INFO, DEBUG]


class LogEntryInput(BaseModel):
    """Schema for log entry input."""
    
    timestamp: datetime = Field(..., description="Original log timestamp")
    level: str = Field(..., description="Log level (ERROR, WARN, INFO, DEBUG)")
    service: str = Field(..., min_length=1, max_length=100, description="Service/app name")
    message: str = Field(..., min_length=1, description="Log message")
    trace_id: Optional[str] = Field(None, max_length=100, description="Trace/correlation ID")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    
    @field_validator('level')
    @classmethod
    def validate_level(cls, v: str) -> str:
        """Validate log level."""
        upper_v = v.upper()
        if upper_v not in LogLevel.LEVELS:
            raise ValueError(f"Level must be one of {LogLevel.LEVELS}")
        return upper_v


class LogEntryResponse(BaseModel):
    """Schema for log entry response."""
    
    id: UUID
    log_hash: str
    source: str
    level: str
    timestamp: datetime
    message_preview: Optional[str]
    has_analysis: bool
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
