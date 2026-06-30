from pydantic import BaseModel, Field
from typing import List, Any, Optional


class WorkflowCreateRequest(BaseModel):
    intent: str = Field(..., description="The natural language query describing the task.")


class WorkflowCreateResponse(BaseModel):
    workflow_id: str = Field(..., description="The generated UUID for the workflow.")
    status: str = Field(default="pending")
    message: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    output: Optional[Any] = None


class WorkflowStatusResponse(BaseModel):
    workflow_id: str
    status: str
    tasks: List[TaskStatusResponse]
    result: Optional[str] = None
    logs: Optional[List[dict]] = None


class LogResponse(BaseModel):
    id: Optional[str] = None
    log_level: str
    message: str
    timestamp: Optional[str] = None


class BasicResponse(BaseModel):
    message: str
