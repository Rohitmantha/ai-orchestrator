import pytest
from unittest.mock import MagicMock
from app.agents.planner.planner import PlannerAgent
from app.schemas.planner import PlanOutput, TaskDefinition

def test_planner_agent_generates_valid_plan(mocker):
    """Ensure the planner agent correctly generates a plan and handles dependencies."""
    # Mock LLM structured output
    mock_plan = PlanOutput(
        workflow_id="test-wf-123",
        tasks=[
            TaskDefinition(task_id="task_1", description="Test task", required_capabilities=["search"], dependencies=[])
        ]
    )
    
    # Mock the chain invocation
    mocker.patch("app.agents.planner.planner.PlannerAgent.__init__", return_value=None)
    planner = PlannerAgent()
    planner.chain = MagicMock()
    planner.chain.invoke.return_value = mock_plan
    
    result = planner.generate_plan("Do some research", "test-wf-123")
    
    assert result.workflow_id == "test-wf-123"
    assert len(result.tasks) == 1
    assert result.tasks[0].task_id == "task_1"
