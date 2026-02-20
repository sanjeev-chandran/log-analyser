"""RCA Generator service for creating structured analysis results."""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4
import time

from app.core.logger import get_logger
from app.core.exceptions import AnalysisError
from app.agent.ai_analyzer import RawAnalysis, AIAnalyzerInterface
from app.agent.mock_analyzer import MockAnalyzer
from app.services.log_parser import ParsedLog
from app.schemas.analysis import (
    AnalysisResult,
    ComponentImpact,
    ComponentType,
    ImpactLevel,
)

logger = get_logger(__name__)


class RCAGenerator:
    """Generator for Root Cause Analysis reports."""
    
    def __init__(
        self,
        ai_analyzer: Optional[AIAnalyzerInterface] = None,
    ):
        """
        Initialize RCA Generator.
        
        Args:
            ai_analyzer: AI analyzer instance (defaults to MockAnalyzer)
        """
        self.ai_analyzer = ai_analyzer or MockAnalyzer()
    
    async def generate(
        self,
        log: ParsedLog,
        log_entry_id: Optional[UUID] = None
    ) -> AnalysisResult:
        """
        Generate complete RCA analysis for a log entry.
        
        Args:
            log: Parsed log data
            log_entry_id: Optional UUID of the saved log entry
            
        Returns:
            AnalysisResult with complete RCA data
            
        Raises:
            AnalysisError: If analysis fails
        """
        start_time = time.time()
        
        try:
            # Get raw analysis from AI analyzer
            raw_analysis = await self.ai_analyzer.analyze(log)
            
            # Calculate processing time
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            # Structure components
            components = self._structure_components(raw_analysis)
            
            # Create final result
            result = AnalysisResult(
                id=uuid4(),
                log_id=log_entry_id or uuid4(),
                summary=raw_analysis.summary,
                root_cause=raw_analysis.root_cause,
                affected_components=components,
                confidence=raw_analysis.confidence,
                analyzed_at=datetime.now(timezone.utc),
                processing_time_ms=processing_time_ms
            )

            logger.info(
                "RCA generated",
                extra={
                    "service": log.service,
                    "confidence": round(raw_analysis.confidence, 3),
                    "processing_time_ms": processing_time_ms,
                    "components_count": len(components),
                },
            )
            return result
            
        except Exception as e:
            if isinstance(e, AnalysisError):
                raise
            logger.error(
                "RCA generation failed: %s",
                str(e),
                extra={"service": log.service},
                exc_info=True,
            )
            raise AnalysisError(
                f"Failed to generate RCA: {str(e)}",
                {"log_service": log.service, "error": str(e)}
            )
    
    def _structure_components(self, raw_analysis: RawAnalysis) -> List[ComponentImpact]:
        """
        Convert raw component analysis to schema format.
        
        Args:
            raw_analysis: Raw analysis from AI analyzer
            
        Returns:
            List of ComponentImpact objects
        """
        structured = []
        
        for comp in raw_analysis.components:
            # Map component type to enum
            comp_type = self._map_component_type(comp.type)
            
            # Map impact level to enum
            impact_level = self._map_impact_level(comp.impact_level)
            
            structured.append(ComponentImpact(
                name=comp.name,
                type=comp_type,
                impact_level=impact_level
            ))
        
        return structured
    
    def _map_component_type(self, type_str: str) -> ComponentType:
        """Map string component type to enum."""
        type_mapping = {
            "service": ComponentType.SERVICE,
            "database": ComponentType.DATABASE,
            "db": ComponentType.DATABASE,
            "cache": ComponentType.CACHE,
            "redis": ComponentType.CACHE,
            "memcached": ComponentType.CACHE,
            "api": ComponentType.API,
            "gateway": ComponentType.API,
            "queue": ComponentType.QUEUE,
            "message_queue": ComponentType.QUEUE,
            "external": ComponentType.EXTERNAL,
            "third_party": ComponentType.EXTERNAL,
            "infrastructure": ComponentType.SERVICE,
        }
        
        normalized = type_str.lower().replace("-", "_").replace(" ", "_")
        return type_mapping.get(normalized, ComponentType.SERVICE)
    
    def _map_impact_level(self, level_str: str) -> ImpactLevel:
        """Map string impact level to enum."""
        level_mapping = {
            "critical": ImpactLevel.CRITICAL,
            "high": ImpactLevel.HIGH,
            "medium": ImpactLevel.MEDIUM,
            "low": ImpactLevel.LOW,
        }
        
        normalized = level_str.lower()
        return level_mapping.get(normalized, ImpactLevel.MEDIUM)
