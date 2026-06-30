from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.schemas.workflow import (
    WorkflowCreateRequest,
    WorkflowCreateResponse,
    WorkflowStatusResponse,
    BasicResponse
)
from app.orchestrator.engine import WorkflowExecutionEngine
from app.registry.registry import AgentRegistry
import uuid

router = APIRouter()
registry = AgentRegistry()
engine = WorkflowExecutionEngine(registry)


@router.post("/workflow", response_model=WorkflowCreateResponse, tags=["Workflows"])
async def create_workflow(request: WorkflowCreateRequest, background_tasks: BackgroundTasks):
    """
    Submit a query. Returns a workflow_id IMMEDIATELY (<100ms).
    Planning and execution happen fully in the background.
    The client should poll GET /workflow/{id} for status updates.
    """
    workflow_id = str(uuid.uuid4())

    # Register workflow immediately so polling works right away
    engine.register_pending(workflow_id, request.intent)

    # All heavy work (planning + execution) runs in background
    background_tasks.add_task(engine.plan_and_run, workflow_id, request.intent)

    return WorkflowCreateResponse(
        workflow_id=workflow_id,
        status="pending",
        message="Workflow accepted. Planning and execution in progress."
    )


@router.get("/workflow/{id}", response_model=WorkflowStatusResponse, tags=["Workflows"])
async def get_workflow_status(id: str):
    """Poll for current workflow status and result."""
    state = engine.get_state(id)
    if state is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return WorkflowStatusResponse(
        workflow_id=id,
        status=state["status"],
        tasks=[{
            "task_id": t["task_id"], 
            "status": t["status"],
            "name": t.get("name", t["task_id"]),
            "task_type": t.get("task_type", "unknown"),
            "result": t.get("result"),
            "error_message": t.get("error_message"),
            "agent_name": t.get("agent_name"),
        } for t in state.get("tasks", [])],
        result=state.get("result"),
        logs=state.get("logs", [])
    )


@router.get("/workflow/{id}/tasks", tags=["Workflows"])
async def get_workflow_tasks(id: str):
    """Get detailed task list for a workflow."""
    state = engine.get_state(id)
    if state is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"workflow_id": id, "tasks": state.get("tasks", [])}


@router.get("/workflow/{id}/logs", tags=["Workflows"])
async def get_workflow_logs(id: str):
    """Get execution logs for a workflow."""
    state = engine.get_state(id)
    if state is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"workflow_id": id, "logs": state.get("logs", [])}


@router.post("/workflow/{id}/cancel", response_model=BasicResponse, tags=["Workflows"])
async def cancel_workflow(id: str):
    state = engine.get_state(id)
    if state is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    engine.cancel(id)
    return BasicResponse(message=f"Workflow {id} cancellation requested.")


@router.post("/workflow/{id}/retry", response_model=BasicResponse, tags=["Workflows"])
async def retry_workflow(id: str, background_tasks: BackgroundTasks):
    state = engine.get_state(id)
    if state is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if state["status"] != "failed":
        raise HTTPException(status_code=400, detail="Only failed workflows can be retried")
    intent = state.get("intent", "")
    engine.register_pending(id, intent)
    background_tasks.add_task(engine.plan_and_run, id, intent)
    return BasicResponse(message=f"Workflow {id} retry initiated.")
