"""AI analyzer interface and data classes.

Defines the contract that all AI analyzer implementations must follow,
plus the shared data classes (``RawAnalysis``, ``ComponentAnalysis``)
used across the analysis pipeline.

Implementations live in their own modules (e.g. ``mock_analyzer.py``).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.log_parser import ParsedLog


@dataclass
class ComponentAnalysis:
    """Analysis of an affected component."""
    name: str
    type: str  # service, database, cache, api, queue, external
    impact_level: str  # critical, high, medium, low


@dataclass
class RawAnalysis:
    """Raw analysis result from AI analyzer."""

    summary: str
    root_cause: str
    components: List[ComponentAnalysis] = field(default_factory=list)
    confidence: float = 0.0  # 0.0 to 1.0
    raw_text: Optional[str] = None  # Original AI response if available


class AIAnalyzerInterface(ABC):
    """Abstract base class for AI analyzers."""

    @abstractmethod
    async def analyze(self, log: ParsedLog) -> RawAnalysis:
        """
        Analyze a log entry and return raw analysis.

        Args:
            log: Parsed log data

        Returns:
            RawAnalysis object containing the analysis results

        Raises:
            AnalysisError: If analysis fails
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> Dict[str, Any]:
        """
        Get analyzer capabilities.

        Returns:
            Dictionary describing analyzer capabilities
        """
        pass
