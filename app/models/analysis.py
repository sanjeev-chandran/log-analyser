"""AnalysisResult SQLAlchemy model."""

from sqlalchemy import Column, DateTime, Float, Integer, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from uuid import uuid4

from app.database import Base


class AnalysisResult(Base):
    """Model for storing AI-generated RCA results."""
    
    __tablename__ = "analysis_results"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    log_entry_id = Column(UUID(as_uuid=True), ForeignKey("log_entries.id", ondelete="CASCADE"), nullable=False, unique=True)
    summary = Column(Text, nullable=False)
    root_cause = Column(Text, nullable=False)
    components = Column(JSONB, nullable=True)
    confidence = Column(Float, nullable=True)
    analyzed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processing_time_ms = Column(Integer, nullable=True)
    
    # Relationship to log_entries
    log_entry = relationship("LogEntry", back_populates="analysis")
    
    def __repr__(self):
        return f"<AnalysisResult(id={self.id}, confidence={self.confidence})>"
