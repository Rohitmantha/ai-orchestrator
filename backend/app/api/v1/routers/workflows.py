"""
Real workflow router -- replaces the mocked handlers with calls into the
actual Orchestrator engine and Postgres-backed repositories.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.workflows import (
    ActionResponse,
    LogResponse,
    TaskResponse,
    WorkflowCreateRequest,
    WorkflowResponse,
)
from app.database.orm_models import ExecutionLogModel, TaskDependencyModel, TaskModel
from app.database.repositories import PostgresTaskRepository, PostgresWorkflowRepository
from app.database.session import get_session
from app.orchestrator.wiring import build_engine_for_request

router = APIRouter(prefix="/workflows", tags=["Workflows"])

_PLACEHOLDER_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_PLACEHOLDER_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def valid_workflow_id(workflow_id: str) -> str:
    try:
        uuid.UUID(workflow_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"'{workflow_id}' is not a valid workflow ID")
    return workflow_id


async def _ensure_placeholder_user_exists(session: AsyncSession) -> None:
    await session.execute(text(
        "INSERT INTO users (id, tenant_id, email, hashed_password) "
        "VALUES (:id, :tenant_id, 'system@placeholder.local', 'x') "
        "ON CONFLICT (tenant_id, email) DO NOTHING"
    ), {"id": _PLACEHOLDER_USER_ID, "tenant_id": _PLACEHOLDER_TENANT_ID})
    await session.commit()


@router.post("/", response_model=WorkflowResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_workflow(
    request: WorkflowCreateRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    await _ensure_placeholder_user_exists(session)

    workflow_repo = PostgresWorkflowRepository(session)
    workflow = await workflow_repo.create_workflow(
        tenant_id=_PLACEHOLDER_TENANT_ID,
        user_id=_PLACEHOLDER_USER_ID,
        original_query=request.query,
    )

    background_tasks.add_task(_run_workflow_in_background, str(workflow.id), request.query)

    return WorkflowResponse(
        workflow_id=str(workflow.id),
        status=workflow.status,
        query=workflow.original_query,
        created_at=workflow.created_at,
    )


async def _run_workflow_in_background(workflow_id: str, query: str) -> None:
    import logging
    logger = logging.getLogger(__name__)

    try:
        engine, planner, session = await build_engine_for_request()
        try:
            plan = await planner.plan(workflow_id=workflow_id, query=query)
            await _persist_plan(session, workflow_id, plan)
            await engine.run_to_completion(workflow_id)
        finally:
            await session.close()
    except Exception:
        logger.exception("Workflow %s failed during background execution", workflow_id)
        try:
            engine2, _, session2 = await build_engine_for_request()
            workflow_repo = PostgresWorkflowRepository(session2)
            await workflow_repo.update_workflow_state(
                workflow_id, "failed", metrics={"error": "Unhandled exception during execution"}
            )
            await session2.close()
        except Exception:
            logger.exception("Workflow %s ALSO failed while recording its own failure", workflow_id)


async def _persist_plan(session: AsyncSession, workflow_id: str, plan) -> None:
    local_id_to_uuid: dict[str, uuid.UUID] = {}
    now = datetime.now(timezone.utc)

    for planned_task in plan.tasks:
        real_id = uuid.uuid4()
        local_id_to_uuid[planned_task.task_id] = real_id
        await session.execute(text(
            "INSERT INTO tasks (id, tenant_id, workflow_id, name, task_type, status, "
            "priority, is_critical, input_payload, acceptance_criteria, created_at, updated_at) "
            "VALUES (:id, :tenant_id, :workflow_id, :name, :task_type, 'pending', "
            ":priority, :is_critical, :input_payload, :acceptance_criteria, :now, :now)"
        ), {
            "id": real_id,
            "tenant_id": _PLACEHOLDER_TENANT_ID,
            "workflow_id": uuid.UUID(workflow_id),
            "name": planned_task.name,
            "task_type": planned_task.task_type.value,
            "priority": planned_task.priority,
            "is_critical": planned_task.is_critical,
            "input_payload": __import__("json").dumps({"description": planned_task.description}),
            "acceptance_criteria": __import__("json").dumps({"text": planned_task.acceptance_criteria}),
            "now": now,
        })

    for dep in plan.dependencies:
        await session.execute(text(
            "INSERT INTO task_dependencies (id, tenant_id, task_id, depends_on_task_id, dependency_type, created_at, updated_at) "
            "VALUES (:id, :tenant_id, :task_id, :depends_on, :dep_type, :now, :now)"
        ), {
            "id": uuid.uuid4(),
            "tenant_id": _PLACEHOLDER_TENANT_ID,
            "task_id": local_id_to_uuid[dep.task_id],
            "depends_on": local_id_to_uuid[dep.depends_on_task_id],
            "dep_type": dep.dependency_type.value,
            "now": now,
        })

    await session.execute(text(
        "UPDATE workflows SET total_tasks = :n, status = 'scheduled', updated_at = :now WHERE id = :id"
    ), {"n": len(plan.tasks), "id": uuid.UUID(workflow_id), "now": now})
    await session.commit()


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str = Depends(valid_workflow_id),
    session: AsyncSession = Depends(get_session),
):
    workflow_repo = PostgresWorkflowRepository(session)
    workflow = await workflow_repo.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")

    return WorkflowResponse(
        workflow_id=str(workflow.id),
        status=workflow.status,
        query=workflow.original_query,
        created_at=workflow.created_at,
        completed_at=workflow.completed_at,
        result=workflow.result if hasattr(workflow, "result") else None,
        error_message=workflow.error_summary if hasattr(workflow, "error_summary") else None,
    )


@router.get("/{workflow_id}/tasks", response_model=List[TaskResponse])
async def get_workflow_tasks(
    workflow_id: str = Depends(valid_workflow_id),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(TaskModel).where(
            TaskModel.workflow_id == uuid.UUID(workflow_id),
            TaskModel.deleted_at.is_(None),
        )
    )
    rows = result.scalars().all()

    task_ids = [row.id for row in rows]
    dep_map: dict[str, list[str]] = {}

    if task_ids:
        dep_result = await session.execute(
            select(TaskDependencyModel).where(
                TaskDependencyModel.task_id.in_(task_ids),
                TaskDependencyModel.deleted_at.is_(None),
            )
        )
        for d in dep_result.scalars().all():
            dep_map.setdefault(str(d.task_id), []).append(str(d.depends_on_task_id))

    return [
        TaskResponse(
            task_id=str(row.id),
            name=row.name or row.task_type,
            task_type=row.task_type,
            status=row.status,
            priority=row.priority,
            output_payload=row.output_payload,
            dependencies=dep_map.get(str(row.id), []),
            result=(row.output_payload or {}).get("result"),
            agent_name=(
                str(row.assigned_agent_id)
                if hasattr(row, "assigned_agent_id") and row.assigned_agent_id
                else None
            ),
            execution_order=row.priority,
        )
        for row in rows
    ]


@router.get("/{workflow_id}/logs", response_model=List[LogResponse])
async def get_workflow_logs(
    workflow_id: str = Depends(valid_workflow_id),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(ExecutionLogModel)
        .where(ExecutionLogModel.workflow_id == uuid.UUID(workflow_id))
        .order_by(ExecutionLogModel.created_at)
    )
    rows = result.scalars().all()
    return [
        LogResponse(event_type=row.event_type, timestamp=row.created_at, details=row.details)
        for row in rows
    ]


@router.post("/{workflow_id}/cancel", response_model=ActionResponse)
async def cancel_workflow(
    workflow_id: str = Depends(valid_workflow_id),
    session: AsyncSession = Depends(get_session),
):
    workflow_repo = PostgresWorkflowRepository(session)
    workflow = await workflow_repo.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")

    await workflow_repo.update_workflow_state(workflow_id, "cancelled")
    return ActionResponse(workflow_id=workflow_id, message="Workflow cancellation requested.")


@router.post("/{workflow_id}/retry", response_model=ActionResponse)
async def retry_workflow(
    workflow_id: str = Depends(valid_workflow_id),
    background_tasks: BackgroundTasks = None,
    session: AsyncSession = Depends(get_session),
):
    workflow_repo = PostgresWorkflowRepository(session)
    workflow = await workflow_repo.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")

    background_tasks.add_task(_resume_workflow_in_background, workflow_id)
    return ActionResponse(workflow_id=workflow_id, message="Workflow retry initiated.")


async def _resume_workflow_in_background(workflow_id: str) -> None:
    import logging
    logger = logging.getLogger(__name__)
    try:
        engine, _, session = await build_engine_for_request()
        try:
            await engine.run_to_completion(workflow_id)
        finally:
            await session.close()
    except Exception:
        logger.exception("Workflow %s failed during retry", workflow_id)