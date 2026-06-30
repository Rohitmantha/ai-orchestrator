import pytest
import asyncio
from unittest.mock import MagicMock
from app.orchestrator.engine import WorkflowExecutionEngine
from app.registry.registry import AgentRegistry

@pytest.mark.asyncio
async def test_execution_engine_workflow(mocker):
    """Ensure the execution engine properly manages a full workflow lifecycle asynchronously."""
    registry = AgentRegistry()
    engine = WorkflowExecutionEngine(registry)
    
    # Mocking planner to prevent LLM calls
    mock_plan = MagicMock()
    mock_plan.model_dump.return_value = {
        "workflow_id": "wf-123",
        "tasks": [{"task_id": "A", "description": "T1", "required_capabilities": [], "dependencies": []}]
    }
    engine.planner.generate_plan = MagicMock(return_value=mock_plan)
    
    # Initialize workflow
    await engine.initialize_workflow("wf-123", "Run test")
    assert "wf-123" in engine.active_workflows
    
    # Mock agent execution to simulate task completion without LLMs
    engine.writer.execute_task = MagicMock()
    mock_output = MagicMock()
    mock_output.model_dump_json.return_value = '{"success": true}'
    engine.writer.execute_task.return_value = mock_output
    
    # Mock verifier to always PASS
    engine.verifier.execute_task = MagicMock()
    mock_verification = MagicMock()
    mock_verification.decision = "PASS"
    engine.verifier.execute_task.return_value = mock_verification
    
    # For testing, we mock asyncio.sleep so the test doesn't actually wait
    mocker.patch("asyncio.sleep", return_value=None)
    
    # Run Workflow
    result = await engine.run_workflow("wf-123")
    
    # Assertions
    assert result is not None
    assert "A" in result
    assert engine.active_workflows["wf-123"].get_workflow_status() == "COMPLETED"
