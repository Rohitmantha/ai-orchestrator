from pydantic import BaseModel, Field
from typing import List, Optional
import enum

class AgentHealthStatus(str, enum.Enum):
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    OFFLINE = "OFFLINE"

class AgentRegistration(BaseModel):
    id: str
    name: str
    description: str
    capabilities: List[str] = Field(description="List of capabilities, e.g. ['web_search', 'python']")
    supported_tools: List[str] = Field(default_factory=list, description="Specific tools it can use")
    supported_task_types: List[str] = Field(default_factory=list, description="Task types it handles")
    priority: int = 1
    health_status: AgentHealthStatus = AgentHealthStatus.HEALTHY
    current_load: int = 0
    max_load: int = 5
