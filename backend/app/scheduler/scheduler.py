from typing import List, Dict, Set, Optional
from datetime import datetime
import enum

class TaskStatus(enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"

class TaskNode:
    def __init__(self, task_id: str, priority: int = 1, timeout_seconds: int = 300, max_retries: int = 3):
        self.task_id = task_id
        self.status = TaskStatus.PENDING
        self.dependencies: Set[str] = set()
        self.priority = priority
        
        # Execution tracking
        self.max_retries = max_retries
        self.retries_count = 0
        self.timeout_seconds = timeout_seconds
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None

class DynamicTaskScheduler:
    """
    Manages the task DAG, resolves dependencies, and yields executable tasks.
    Supports parallel execution checking, timeouts, retries, and priority scheduling.
    """
    def __init__(self):
        self.tasks: Dict[str, TaskNode] = {}
        
    def add_task(self, task_id: str, priority: int = 1, max_retries: int = 3, timeout_seconds: int = 300):
        if task_id not in self.tasks:
            self.tasks[task_id] = TaskNode(
                task_id=task_id, 
                priority=priority, 
                max_retries=max_retries, 
                timeout_seconds=timeout_seconds
            )
            
    def add_dependency(self, task_id: str, depends_on_id: str):
        if task_id in self.tasks:
            self.tasks[task_id].dependencies.add(depends_on_id)
            
    def load_from_planner(self, planner_output: dict):
        """
        Bootstrap the scheduler from the PlannerOutput dict.
        """
        for task in planner_output.get("tasks", []):
            # We default to priority 1, can be extended to parse priority from schema
            self.add_task(task["task_id"], priority=1)
            
        for dep in planner_output.get("dependencies", []):
            task_id = dep["task_id"]
            for depends_on in dep.get("depends_on", []):
                self.add_dependency(task_id, depends_on)

    def get_executable_tasks(self) -> List[TaskNode]:
        """
        Returns a list of tasks that are ready to run.
        Ready means: status is PENDING or RETRYING, and all dependencies are COMPLETED.
        Tasks are sorted by priority (higher number = higher priority).
        This inherently supports parallel execution by returning ALL currently executable tasks.
        """
        executable = []
        for task in self.tasks.values():
            if task.status in [TaskStatus.PENDING, TaskStatus.RETRYING]:
                # Check if all dependencies are satisfied
                deps_satisfied = all(
                    self.tasks[dep_id].status == TaskStatus.COMPLETED 
                    for dep_id in task.dependencies if dep_id in self.tasks
                )
                if deps_satisfied:
                    executable.append(task)
                    
        # Sort by priority descending
        executable.sort(key=lambda t: t.priority, reverse=True)
        return executable
        
    def mark_task_running(self, task_id: str):
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()

    def mark_task_completed(self, task_id: str):
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()

    def mark_task_failed(self, task_id: str):
        """
        Marks a task as failed and increments retry count.
        Transitions to RETRYING if under max_retries limit.
        """
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.retries_count += 1
            if task.retries_count <= task.max_retries:
                task.status = TaskStatus.RETRYING
            else:
                task.status = TaskStatus.FAILED
                
    def check_timeouts(self) -> List[TaskNode]:
        """
        Identifies running tasks that have exceeded their timeout duration.
        """
        timed_out = []
        now = datetime.utcnow()
        for task in self.tasks.values():
            if task.status == TaskStatus.RUNNING and task.started_at:
                elapsed = (now - task.started_at).total_seconds()
                if elapsed > task.timeout_seconds:
                    timed_out.append(task)
                    # Force a failure which triggers retry logic
                    self.mark_task_failed(task.task_id)
        return timed_out
        
    def get_workflow_status(self) -> str:
        """
        Determines the overall status of the workflow DAG.
        """
        statuses = [t.status for t in self.tasks.values()]
        if TaskStatus.FAILED in statuses:
            return "FAILED"
        if all(s == TaskStatus.COMPLETED for s in statuses):
            return "COMPLETED"
        if TaskStatus.RUNNING in statuses:
            return "RUNNING"
        return "PENDING"
