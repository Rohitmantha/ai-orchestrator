import pytest
from app.scheduler.scheduler import DynamicTaskScheduler, TaskStatus

def test_scheduler_dependency_resolution():
    """Ensure tasks with dependencies are not executable until dependencies are met."""
    scheduler = DynamicTaskScheduler()
    plan_data = {
        "workflow_id": "test",
        "tasks": [
            {"task_id": "A", "description": "T1", "required_capabilities": [], "dependencies": []},
            {"task_id": "B", "description": "T2", "required_capabilities": [], "dependencies": ["A"]}
        ]
    }
    
    scheduler.load_from_planner(plan_data)
    
    # A should be executable, B should not
    executable = scheduler.get_executable_tasks()
    assert len(executable) == 1
    assert executable[0].task_id == "A"
    
    # Complete A
    scheduler.mark_task_running("A")
    scheduler.mark_task_completed("A")
    
    # B should now be executable
    executable_after_a = scheduler.get_executable_tasks()
    assert len(executable_after_a) == 1
    assert executable_after_a[0].task_id == "B"

def test_scheduler_retry_logic():
    """Ensure the scheduler retries tasks up to the limit and then fails the workflow."""
    scheduler = DynamicTaskScheduler()
    plan_data = {
        "workflow_id": "test",
        "tasks": [
            {"task_id": "A", "description": "T1", "required_capabilities": [], "dependencies": []}
        ]
    }
    
    scheduler.load_from_planner(plan_data)
    scheduler.mark_task_running("A")
    
    # Fail A once
    scheduler.mark_task_failed("A")
    assert scheduler.tasks["A"].status == TaskStatus.PENDING
    assert scheduler.tasks["A"].retries_count == 1
    
    # Fail A to max limit (assuming default is 3)
    scheduler.mark_task_running("A")
    scheduler.mark_task_failed("A")
    scheduler.mark_task_running("A")
    scheduler.mark_task_failed("A")
    
    # This 4th failure exceeds the limit
    scheduler.mark_task_running("A")
    scheduler.mark_task_failed("A")  
    
    assert scheduler.tasks["A"].status == TaskStatus.FAILED
    assert scheduler.get_workflow_status() == "FAILED"
