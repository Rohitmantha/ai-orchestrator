import pytest
from typing import List, Dict, Any, Optional
from app.orchestrator.engine import WorkflowExecutionEngine
from app.orchestrator.ports import ITaskRepository, IWorkflowRepository, IAgentDispatcher
from app.scheduler.dynamic_scheduler import DynamicTaskScheduler
from app.scheduler.models import TaskNode, DependencyEdge, TaskExecutionStatus

# --- FAKES FOR TESTING ---
class FakeTaskRepo(ITaskRepository):
    def __init__(self, tasks: List[TaskNode], deps: List[DependencyEdge]):
        self.tasks = {t.task_id: t for t in tasks}
        self.deps = deps

    async def get_tasks(self, workflow_id: str) -> List[TaskNode]:
        return list(self.tasks.values())

    async def get_dependencies(self, workflow_id: str) -> List[DependencyEdge]:
        return self.deps

    async def update_task_state(self, task_id: str, status: str, output: Optional[Dict[str, Any]] = None, metrics: Optional[Dict[str, Any]] = None):
        task = self.tasks[task_id]
        task.status = status
        if output is not None:
            task.output_payload = output
        if metrics:
            task.retry_count = metrics.get("attempts", task.retry_count)

class FakeWorkflowRepo(IWorkflowRepository):
    def __init__(self):
        self.status = "pending"
        self.metrics = {}

    async def update_workflow_state(self, workflow_id: str, status: str, metrics: Optional[Dict[str, Any]] = None):
        self.status = status
        if metrics:
            self.metrics.update(metrics)

class FakeDispatcher(IAgentDispatcher):
    def __init__(self):
        self.calls = []
        self.fail_tasks = set()

    async def dispatch(self, task, context: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"task_id": task.task_id, "context": context})
        if task.task_id in self.fail_tasks:
            raise ValueError(f"Simulated failure for {task.task_id}")
        return {"result_for": task.task_id, "received_context": context}


# --- TESTS ---

@pytest.mark.asyncio
async def test_engine_happy_path_with_context_passing():
    """Tests full execution of a DAG and verifies output from T1 is passed exactly to T2."""
    t1 = TaskNode(task_id="t1", task_type="research", status=TaskExecutionStatus.PENDING)
    t2 = TaskNode(task_id="t2", task_type="analysis", status=TaskExecutionStatus.PENDING)
    deps = [DependencyEdge(task_id="t2", depends_on_task_id="t1")]
    
    repo = FakeTaskRepo([t1, t2], deps)
    wf_repo = FakeWorkflowRepo()
    dispatcher = FakeDispatcher()
    engine = WorkflowExecutionEngine(repo, wf_repo, dispatcher, DynamicTaskScheduler())
    
    final_status = await engine.run_to_completion("wf-1")
    
    assert final_status == "completed"
    assert wf_repo.status == "completed"
    assert "total_duration_seconds" in wf_repo.metrics
    
    # Verify execution order and context passing
    assert len(dispatcher.calls) == 2
    assert dispatcher.calls[0]["task_id"] == "t1"
    assert dispatcher.calls[1]["task_id"] == "t2"
    
    # T2 should have received T1's output in its context
    t2_context = dispatcher.calls[1]["context"]
    assert "t1" in t2_context
    assert t2_context["t1"]["result_for"] == "t1"

@pytest.mark.asyncio
async def test_engine_checkpoint_recovery():
    """Proves the engine doesn't re-run tasks that already succeeded (Checkpointing)."""
    # T1 already succeeded in a previous run before a crash
    t1 = TaskNode(task_id="t1", task_type="research", status=TaskExecutionStatus.VERIFIED)
    t1.output_payload = {"data": "saved"}
    
    t2 = TaskNode(task_id="t2", task_type="analysis", status=TaskExecutionStatus.PENDING)
    deps = [DependencyEdge(task_id="t2", depends_on_task_id="t1")]
    
    repo = FakeTaskRepo([t1, t2], deps)
    dispatcher = FakeDispatcher()
    engine = WorkflowExecutionEngine(repo, FakeWorkflowRepo(), dispatcher, DynamicTaskScheduler())
    
    await engine.run_to_completion("wf-2")
    
    # T1 should NOT have been dispatched again
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0]["task_id"] == "t2"
    assert dispatcher.calls[0]["context"]["t1"] == {"data": "saved"}

@pytest.mark.asyncio
async def test_engine_handles_task_failure():
    """Tests that a task throwing an exception updates state to FAILED correctly."""
    t1 = TaskNode(task_id="t1", task_type="research", is_critical=True, status=TaskExecutionStatus.PENDING)
    
    repo = FakeTaskRepo([t1], [])
    dispatcher = FakeDispatcher()
    dispatcher.fail_tasks.add("t1")  # Force it to fail
    
    engine = WorkflowExecutionEngine(repo, FakeWorkflowRepo(), dispatcher, DynamicTaskScheduler())
    
    final_status = await engine.run_to_completion("wf-3")
    
    assert final_status == "failed"
    assert repo.tasks["t1"].status == TaskExecutionStatus.FAILED
    assert "error" in repo.tasks["t1"].output_payload
