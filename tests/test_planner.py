"""
Tests for the Planner Agent module.

Uses a FakeLLMProvider instead of any real API -- this is exactly the
payoff of the LLMProvider abstraction: we can unit-test all of the
planner's logic (prompt construction, validation, repair-retry loop)
without an API key, network access, or spending money on LLM calls.
"""

import asyncio
import sys
from pathlib import Path

import pytest

# tests/test_planner.py -> tests/ -> project root -> backend/app/agents
# The planner package lives at backend/app/agents/planner/, so that's the
# directory that needs to be on sys.path for `from planner.x import y` to
# resolve -- not the project root itself.
sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "app" / "agents"))

from planner.llm_provider import LLMProvider, LLMProviderError
from planner.planner_agent import PlannerAgent, PlannerAgentError
from planner.schemas import WorkflowPlan
from planner.validation import validate_plan


class FakeLLMProvider(LLMProvider):
    """Returns a pre-programmed sequence of responses, one per call.
    Lets tests simulate "LLM returns a broken plan, then a fixed one"."""

    def __init__(self, responses: list[dict]):
        self._responses = responses
        self.call_count = 0
        self.last_user_prompt: str | None = None

    async def generate_structured(self, *, system_prompt, user_prompt, json_schema, schema_name):
        self.last_user_prompt = user_prompt
        if self.call_count >= len(self._responses):
            raise LLMProviderError("FakeLLMProvider ran out of programmed responses")
        response = self._responses[self.call_count]
        self.call_count += 1
        return response


VALID_PLAN = {
    "workflow_id": "wf-placeholder",
    "tasks": [
        {
            "task_id": "t1",
            "name": "Research competitor pricing",
            "task_type": "research",
            "description": "Search the web for pricing pages of the top 3 competitors and list their prices.",
            "required_capabilities": ["web_search"],
            "acceptance_criteria": "A list of at least 3 competitor names each with a price.",
            "priority": 5,
            "is_critical": True,
        },
        {
            "task_id": "t2",
            "name": "Summarize findings",
            "task_type": "writing",
            "description": "Using the competitor pricing research provided as input, write a 1-paragraph summary.",
            "required_capabilities": ["summarization"],
            "acceptance_criteria": "A single paragraph mentioning all researched competitors.",
            "priority": 3,
            "is_critical": True,
        },
    ],
    "dependencies": [
        {"task_id": "t2", "depends_on_task_id": "t1", "dependency_type": "data_dependency"},
    ],
}

CYCLIC_PLAN = {
    "workflow_id": "wf-placeholder",
    "tasks": [
        {
            "task_id": "t1", "name": "A", "task_type": "research",
            "description": "x", "required_capabilities": [],
            "acceptance_criteria": "x", "priority": 0, "is_critical": True,
        },
        {
            "task_id": "t2", "name": "B", "task_type": "research",
            "description": "x", "required_capabilities": [],
            "acceptance_criteria": "x", "priority": 0, "is_critical": True,
        },
    ],
    "dependencies": [
        {"task_id": "t1", "depends_on_task_id": "t2", "dependency_type": "finish_to_start"},
        {"task_id": "t2", "depends_on_task_id": "t1", "dependency_type": "finish_to_start"},
    ],
}

DANGLING_REF_PLAN = {
    "workflow_id": "wf-placeholder",
    "tasks": [
        {
            "task_id": "t1", "name": "A", "task_type": "research",
            "description": "x", "required_capabilities": [],
            "acceptance_criteria": "x", "priority": 0, "is_critical": True,
        },
    ],
    "dependencies": [
        {"task_id": "t1", "depends_on_task_id": "t99", "dependency_type": "finish_to_start"},
    ],
}


def test_valid_plan_passes_validation():
    plan = WorkflowPlan.model_validate(VALID_PLAN)
    result = validate_plan(plan)
    assert result.is_valid, result.errors


def test_cyclic_plan_fails_validation():
    plan = WorkflowPlan.model_validate(CYCLIC_PLAN)
    result = validate_plan(plan)
    assert not result.is_valid
    assert any("Cycle detected" in e for e in result.errors)


def test_dangling_dependency_fails_validation():
    plan = WorkflowPlan.model_validate(DANGLING_REF_PLAN)
    result = validate_plan(plan)
    assert not result.is_valid
    assert any("unknown depends_on_task_id" in e for e in result.errors)


def test_self_dependency_rejected_at_schema_level():
    bad = {
        "workflow_id": "wf-1",
        "tasks": [
            {
                "task_id": "t1", "name": "A", "task_type": "research",
                "description": "x", "required_capabilities": [],
                "acceptance_criteria": "x", "priority": 0, "is_critical": True,
            },
        ],
        "dependencies": [
            {"task_id": "t1", "depends_on_task_id": "t1", "dependency_type": "finish_to_start"},
        ],
    }
    with pytest.raises(Exception):
        WorkflowPlan.model_validate(bad)


def test_planner_agent_returns_valid_plan_on_first_try():
    async def run():
        provider = FakeLLMProvider(responses=[VALID_PLAN])
        agent = PlannerAgent(provider)
        plan = await agent.plan(workflow_id="wf-real-123", query="Compare competitor pricing")
        assert provider.call_count == 1
        assert plan.workflow_id == "wf-real-123"  # forced to match caller's ID, not the LLM's echo
        assert len(plan.tasks) == 2
        assert len(plan.dependencies) == 1

    asyncio.run(run())


def test_planner_agent_repairs_after_cycle_then_succeeds():
    async def run():
        provider = FakeLLMProvider(responses=[CYCLIC_PLAN, VALID_PLAN])
        agent = PlannerAgent(provider)
        plan = await agent.plan(workflow_id="wf-2", query="anything")
        assert provider.call_count == 2
        assert len(plan.tasks) == 2
        # the second prompt should include the validation error feedback
        assert "Cycle detected" in provider.last_user_prompt

    asyncio.run(run())


def test_planner_agent_gives_up_after_max_attempts():
    async def run():
        # 3 broken responses in a row -- exceeds _MAX_REPAIR_ATTEMPTS (2 repairs + 1 initial = 3 tries)
        provider = FakeLLMProvider(responses=[CYCLIC_PLAN, CYCLIC_PLAN, CYCLIC_PLAN])
        agent = PlannerAgent(provider)
        with pytest.raises(PlannerAgentError) as exc_info:
            await agent.plan(workflow_id="wf-3", query="anything")
        assert provider.call_count == 3
        assert any("Cycle detected" in e for e in exc_info.value.last_errors)

    asyncio.run(run())


def test_planner_agent_propagates_provider_error_without_retrying_as_repair():
    async def run():
        class AlwaysFailsProvider(LLMProvider):
            async def generate_structured(self, **kwargs):
                raise LLMProviderError("simulated timeout")

        agent = PlannerAgent(AlwaysFailsProvider())
        with pytest.raises(PlannerAgentError):
            await agent.plan(workflow_id="wf-4", query="anything")

    asyncio.run(run())


def test_json_schema_is_well_formed_for_strict_mode():
    """Every property referenced in a 'properties' block must also appear
    in that same level's 'required' list -- this is what OpenAI's
    strict structured-output mode demands. Catching a mismatch here is
    much cheaper than discovering it via a 400 from the API."""
    schema = PlannerAgent._build_json_schema()

    def check(node):
        if node.get("type") == "object":
            props = set(node.get("properties", {}).keys())
            required = set(node.get("required", []))
            assert props == required, f"properties/required mismatch: {props} vs {required}"
            assert node.get("additionalProperties") is False
            for v in node.get("properties", {}).values():
                check(v)
        elif node.get("type") == "array":
            check(node["items"])

    check(schema)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
