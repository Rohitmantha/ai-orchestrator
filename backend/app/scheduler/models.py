from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum

class TaskExecutionStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFIED = "verified"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (TaskExecutionStatus.VERIFIED, TaskExecutionStatus.FAILED, 
                        TaskExecutionStatus.SKIPPED, TaskExecutionStatus.CANCELLED)

    @property
    def is_successful_terminal(self) -> bool:
        return self == TaskExecutionStatus.VERIFIED

@dataclass
class TaskNode:
    task_id: str
    task_type: str
    status: TaskExecutionStatus
    priority: int = 0
    is_critical: bool = True
    retry_count: int = 0
    input_payload: Dict[str, Any] = field(default_factory=dict)
    output_payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def description(self) -> str:
        return self.input_payload.get("description", "")

@dataclass
class DependencyEdge:
    task_id: str
    depends_on_task_id: str

@dataclass
class ScheduledTask:
    task_id: str
    task_type: str
    priority: int
    attempt_number: int
    timeout_seconds: int
    is_retry: bool

@dataclass
class SkippedTask:
    task_id: str
    reason: str

@dataclass
class ExecutionPlan:
    current_batch: List[ScheduledTask]
    skipped: List[SkippedTask]
    blocked_task_ids: List[str]
    workflow_can_progress: bool
    workflow_is_complete: bool
    workflow_terminal_state: Optional[str] = None

@dataclass
class RetryPolicy:
    max_retries: int = 3
    backoff_factor: float = 2.0
    def backoff_for_attempt(self, attempt: int) -> float:
        return (self.backoff_factor ** (attempt - 1)) * 5.0

@dataclass
class TimeoutPolicy:
    execution_timeout_seconds: int = 300

DEFAULT_RETRY_POLICIES = {
    "research": RetryPolicy(max_retries=3),
    "coding": RetryPolicy(max_retries=2),
    "analysis": RetryPolicy(max_retries=2),
    "writing": RetryPolicy(max_retries=2),
    "verification": RetryPolicy(max_retries=2),
}

DEFAULT_TIMEOUT_POLICIES = {
    "research": TimeoutPolicy(execution_timeout_seconds=600),
    "coding": TimeoutPolicy(execution_timeout_seconds=300),
    "analysis": TimeoutPolicy(execution_timeout_seconds=300),
}