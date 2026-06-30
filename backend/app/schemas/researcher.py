from pydantic import BaseModel, Field
from typing import List, Optional

class SourceCitation(BaseModel):
    title: str
    url: Optional[str]
    snippet: str

class ResearchOutput(BaseModel):
    summary: str = Field(description="A comprehensive summary of the researched topic.")
    key_findings: List[str] = Field(description="Bullet points of the most important facts extracted.")
    sources: List[SourceCitation] = Field(description="List of sources used to compile the research.")
    status: str = Field(default="SUCCESS", description="Status of the research, e.g., 'SUCCESS', 'FAILED'")
    error_message: Optional[str] = Field(default=None, description="Error details if the research failed.")
