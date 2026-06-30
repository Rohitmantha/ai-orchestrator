from pydantic import BaseModel, Field
from typing import List, Optional
import enum

class VerificationDecision(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    RETRY = "RETRY"

class VerifierOutput(BaseModel):
    decision: VerificationDecision = Field(description="The final decision: PASS, FAIL, or RETRY.")
    confidence_score: float = Field(description="Confidence score from 0.0 to 1.0 based on how well the output matches the constraints.")
    feedback: str = Field(description="Detailed feedback explaining the decision, missing fields, or detected hallucinations. Used for RETRY context.")
    missing_fields: List[str] = Field(description="List of any required fields or information that were missing from the output.")
    hallucinations_detected: List[str] = Field(description="List of potential hallucinations or unsupported claims found in the output.")
