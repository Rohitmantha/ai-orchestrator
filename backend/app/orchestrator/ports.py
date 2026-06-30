from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from app.scheduler.models import TaskNode, DependencyEdge

class ITaskRepository(ABC):
    @abstractmethod
    async def get_tasks(self, workflow_id: str) -> List[TaskNode]:
        pass
        
    @abstractmethod
    async def get_dependencies(self, workflow_id: str) -> List[DependencyEdge]:
        pass

    @abstractmethod
    async def update_task_state(self, task_id: str, status: str, output: Optional[Dict[str, Any]] = None, metrics: Optional[Dict[str, Any]] = None):
        pass

class IWorkflowRepository(ABC):
    @abstractmethod
    async def update_workflow_state(self, workflow_id: str, status: str, metrics: Optional[Dict[str, Any]] = None):
        pass

class IAgentDispatcher(ABC):
    @abstractmethod
    async def dispatch(self, task: TaskNode, context: Dict[str, Any]) -> Dict[str, Any]:
        """Executes the task via the Agent Registry/Queue and returns the result."""
        pass