from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime, timezone

class AnalysisOutput(BaseModel):
    comparison: Optional[str] = Field(None, description="Comparative analysis between entities, options, or datasets")
    reasoning: str = Field(..., description="Logical deductions, synthesis, and step-by-step rationale")
    data_analysis: Optional[Dict[str, Any]] = Field(None, description="Structured insights extracted from raw data")
    mathematical_results: Optional[Dict[str, float]] = Field(None, description="Results of numerical calculations")
    trend_analysis: Optional[str] = Field(None, description="Identified historical patterns and future projections")

class ExecutionLog(BaseModel):
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: Dict[str, Any]