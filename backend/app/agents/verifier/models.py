from enum import Enum
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

class VerificationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    RETRY = "RETRY"

class VerificationOutput(BaseModel):
    status: VerificationStatus
    reason: str
    missing_fields: List[str] = Field(default_factory=list)

class ExecutionLog(BaseModel):
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: Dict[str, Any]