from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.orm_models import ExecutionLogModel, TaskDependencyModel, TaskModel, WorkflowModel
from app.orchestrator.ports import IWorkflowRepository, ITaskRepository
from app.scheduler.models import DependencyEdge, TaskExecutionStatus, TaskNode

def _to_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)

class PostgresTaskRepository(ITaskRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_tasks(self, workflow_id: str) -> list[TaskNode]:
        wf_uuid = _to_uuid(workflow_id)
        result = await self._session.execute(
            select(TaskModel).where(TaskModel.workflow_id == wf_uuid, TaskModel.deleted_at.is_(None))
        )
        return [self._row_to_task_node(row) for row in result.scalars().all()]

    async def get_dependencies(self, workflow_id: str) -> list[DependencyEdge]:
        wf_uuid = _to_uuid(workflow_id)
        result = await self._session.execute(
            select(TaskDependencyModel)
            .join(TaskModel, TaskDependencyModel.task_id == TaskModel.id)
            .where(TaskModel.workflow_id == wf_uuid, TaskDependencyModel.deleted_at.is_(None))
        )
        return [DependencyEdge(task_id=str(row.task_id), depends_on_task_id=str(row.depends_on_task_id)) for row in result.scalars().all()]

    async def update_task_state(self, task_id: str, status: str, output: dict[str, Any] | None = None, metrics: dict[str, Any] | None = None) -> None:
        task_uuid = _to_uuid(task_id)
        result = await self._session.execute(select(TaskModel).where(TaskModel.id == task_uuid))
        row = result.scalar_one()

        status_value = status.value if isinstance(status, TaskExecutionStatus) else status
        row.status = status_value

        now = datetime.now(timezone.utc)
        if status_value == TaskExecutionStatus.RUNNING.value and row.started_at is None:
            row.started_at = now
        if status_value in (TaskExecutionStatus.VERIFIED.value, TaskExecutionStatus.FAILED.value):
            row.completed_at = now

        if output is not None:
            row.output_payload = output
            if status_value == TaskExecutionStatus.FAILED.value and "error" in output:
                row.error_message = str(output["error"])

        if metrics is not None and "attempts" in metrics:
            row.retry_count = max(0, int(metrics["attempts"]) - 1)

        row.updated_at = now
        await self._session.commit()

    @staticmethod
    def _row_to_task_node(row: TaskModel) -> TaskNode:
        try:
            status = TaskExecutionStatus(row.status)
        except ValueError as exc:
            raise ValueError(f"Task row {row.id} has invalid status '{row.status}'") from exc

        return TaskNode(
            task_id=str(row.id),
            task_type=row.task_type,
            status=status,
            priority=row.priority,
            is_critical=row.is_critical,
            retry_count=row.retry_count,
            input_payload=row.input_payload or {},
            output_payload=row.output_payload or {},
        )

class PostgresWorkflowRepository(IWorkflowRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def update_workflow_state(self, workflow_id: str, status: str, metrics: dict[str, Any] | None = None) -> None:
        wf_uuid = _to_uuid(workflow_id)
        result = await self._session.execute(select(WorkflowModel).where(WorkflowModel.id == wf_uuid))
        row = result.scalar_one()
        row.status = status
        now = datetime.now(timezone.utc)
        if status in ("completed", "degraded", "failed", "cancelled"):
            row.completed_at = now
        if metrics and "error" in metrics:
            row.error_summary = str(metrics["error"])
        row.updated_at = now
        await self._session.commit()

    async def get_workflow(self, workflow_id: str) -> WorkflowModel | None:
        wf_uuid = _to_uuid(workflow_id)
        result = await self._session.execute(select(WorkflowModel).where(WorkflowModel.id == wf_uuid))
        return result.scalar_one_or_none()
    
    async def create_workflow(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, original_query: str) -> WorkflowModel:
        now = datetime.now(timezone.utc)
        row = WorkflowModel(
            id=uuid.uuid4(), tenant_id=tenant_id, user_id=user_id, original_query=original_query,
            status="pending", created_at=now, updated_at=now,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row