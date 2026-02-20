"""Pydantic schemas for analysis results."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from enum import Enum


class ComponentType(str, Enum):
    """Types of components."""
    SERVICE = "service"
    DATABASE = "database"
    CACHE = "cache"
    API = "api"
    QUEUE = "queue"
    EXTERNAL = "external"


class ImpactLevel(str, Enum):
    """Impact levels for components."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ComponentImpact(BaseModel):
    """Schema for affected component."""
    
    name: str = Field(..., description="Component name")
    type: ComponentType = Field(..., description="Component type")
    impact_level: ImpactLevel = Field(..., description="Impact level")


class AnalysisResult(BaseModel):
    """Schema for complete RCA result."""
    
    id: UUID
    log_id: UUID
    summary: str = Field(..., description="Error summary")
    root_cause: str = Field(..., description="Root cause analysis")
    affected_components: List[ComponentImpact] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0, description="AI confidence score")
    analyzed_at: datetime
    processing_time_ms: int = Field(..., description="Analysis duration in milliseconds")
    
    model_config = ConfigDict(from_attributes=True)


class AnalysisListResponse(BaseModel):
    """Schema for paginated list of analyses."""
    
    items: List[AnalysisResult]
    total: int
    page: int
    page_size: int
