from pydantic import BaseModel, Field
from typing import List

class TaskDefinition(BaseModel):
    task_id: str = Field(description="Unique identifier for the task, e.g., 'task_1'")
    name: str = Field(description="Short, descriptive name of the task")
    description: str = Field(description="Detailed instructions on what the task should accomplish")
    required_capabilities: List[str] = Field(description="List of agent capabilities required to execute this task, e.g., ['web_search', 'python_execution']")

class DependencyDefinition(BaseModel):
    task_id: str = Field(description="The ID of the task that has dependencies")
    depends_on: List[str] = Field(description="List of task IDs that must complete before this task can start")

class PlannerOutput(BaseModel):
    workflow_id: str = Field(description="The UUID of the workflow being planned")
    tasks: List[TaskDefinition] = Field(description="List of tasks required to complete the workflow")
    dependencies: List[DependencyDefinition] = Field(description="List of dependencies dictating the execution order of the tasks")
