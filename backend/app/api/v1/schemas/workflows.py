from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


class WorkflowCreateRequest(BaseModel):
    query: str = Field(..., description="The natural language request to execute")


class WorkflowResponse(BaseModel):
    workflow_id: str
    status: str
    query: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    result: Optional[str] = None
    error_message: Optional[str] = None


class TaskResponse(BaseModel):
    task_id: str
    name: str = ""
    task_type: str
    status: str
    priority: int
    output_payload: Optional[Dict[str, Any]] = None
    dependencies: List[str] = []
    result: Optional[str] = None
    error_message: Optional[str] = None
    agent_name: Optional[str] = None
    execution_order: int = 0


class LogResponse(BaseModel):
    event_type: str
    timestamp: datetime
    details: Dict[str, Any]


class ActionResponse(BaseModel):
    workflow_id: str
    message: str