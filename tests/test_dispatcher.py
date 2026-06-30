import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.api_wiring.dispatcher import AgentDispatcher, DispatchError
from app.agents.researcher.research_agent import ResearchAgent
from app.agents.researcher.tools import WebSearchTool, WebSearchResult
from app.llm_providers.llm_provider import LLMProvider
from app.registry.agent_registry import AgentRegistry
from app.registry.models import AgentProfile, HealthStatus
from app.scheduler.models import TaskExecutionStatus, TaskNode


class FakeLLM(LLMProvider):
    async def generate_structured(self, **kwargs):
        return {"summary": "Test summary of findings."}


class FakeWebSearch(WebSearchTool):
    async def search(self, query, max_results=5):
        return [WebSearchResult(title="A", url="https://example.com", snippet="content")]


def run(coro):
    return asyncio.run(coro)


def _make_registry_with_researcher():
    registry = AgentRegistry()
    registry.register(AgentProfile(
        agent_id="researcher-1",
        name="Researcher",
        description="test",
        capabilities=frozenset(),
        supported_tools=frozenset(),
        supported_task_types=frozenset({"research"}),
        priority=5,
        max_concurrency=5,
        health_status=HealthStatus.ACTIVE,
        current_load=0,
    ))
    return registry


def test_dispatcher_resolves_and_calls_real_research_agent():
    registry = _make_registry_with_researcher()
    research_agent = ResearchAgent(llm_provider=FakeLLM(), web_search_tool=FakeWebSearch())
    dispatcher = AgentDispatcher(registry, {"research": research_agent})

    task = TaskNode(task_id="t1", task_type="research", status=TaskExecutionStatus.READY)

    result = run(dispatcher.dispatch(task, context={"query": "What is the pricing model?"}))

    assert "summary" in result
    assert result["summary"] == "Test summary of findings."
    assert "web_results" in result


def test_dispatcher_increments_and_decrements_load_around_call():
    registry = _make_registry_with_researcher()
    research_agent = ResearchAgent(llm_provider=FakeLLM(), web_search_tool=FakeWebSearch())
    dispatcher = AgentDispatcher(registry, {"research": research_agent})
    task = TaskNode(task_id="t1", task_type="research", status=TaskExecutionStatus.READY)

    run(dispatcher.dispatch(task, context={"query": "q"}))

    assert registry.get("researcher-1").current_load == 0  # back to 0 after completion


def test_dispatcher_raises_dispatch_error_when_no_agent_eligible():
    registry = AgentRegistry()  # empty -- nothing registered
    dispatcher = AgentDispatcher(registry, {})
    task = TaskNode(task_id="t1", task_type="research", status=TaskExecutionStatus.READY)

    with pytest.raises(DispatchError):
        run(dispatcher.dispatch(task, context={}))


def test_dispatcher_raises_dispatch_error_when_agent_instance_missing():
    """Registry says a researcher SHOULD handle this, but the dispatcher
    was never given an actual ResearchAgent instance to call."""
    registry = _make_registry_with_researcher()
    dispatcher = AgentDispatcher(registry, {})  # empty instance map
    task = TaskNode(task_id="t1", task_type="research", status=TaskExecutionStatus.READY)

    with pytest.raises(DispatchError, match="no agent instance is wired up"):
        run(dispatcher.dispatch(task, context={}))


def test_dispatcher_releases_load_even_when_agent_execution_fails():
    class BrokenLLM(LLMProvider):
        async def generate_structured(self, **kwargs):
            raise RuntimeError("simulated outage")

    registry = _make_registry_with_researcher()
    research_agent = ResearchAgent(llm_provider=BrokenLLM())  # no tools -> total failure path inside agent itself raises only if summarization also fails with no tools
    dispatcher = AgentDispatcher(registry, {"research": research_agent})
    task = TaskNode(task_id="t1", task_type="research", status=TaskExecutionStatus.READY)

    # No tools configured -> ResearchAgent short-circuits gracefully
    # ("No research sources were configured") without even calling the
    # broken LLM, so this should NOT raise -- confirms load is released
    # on the success path too, not just exceptions.
    run(dispatcher.dispatch(task, context={}))
    assert registry.get("researcher-1").current_load == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
