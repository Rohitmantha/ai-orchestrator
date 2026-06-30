from pydantic import BaseModel, Field
from typing import Dict, Any
from datetime import datetime, timezone

class WriterOutput(BaseModel):
    formatted_content: str = Field(..., description="The final generated text, HTML, Markdown, or JSON string")
    content_type: str = Field(..., description="The format of the content (e.g., 'markdown', 'html', 'json', 'report', 'summary')")
    word_count: int

class ExecutionLog(BaseModel):
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: Dict[str, Any]