from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class AnalysisOutput(BaseModel):
    summary: str = Field(description="A clear summary of the analysis results.")
    comparisons: List[str] = Field(description="Points comparing the evaluated entities or datasets.")
    data_insights: List[str] = Field(description="Key insights derived from data analysis and reasoning.")
    trends: List[str] = Field(description="Identified trends over time or across categories.")
    calculated_metrics: Dict[str, float] = Field(description="Any mathematical or statistical metrics calculated.")
    status: str = Field(default="SUCCESS", description="Status of the analysis.")
    error_message: Optional[str] = Field(default=None, description="Error details if the analysis failed.")
