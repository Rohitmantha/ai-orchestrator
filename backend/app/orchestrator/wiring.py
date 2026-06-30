"""
Wiring helper -- assembles one fully-configured WorkflowExecutionEngine
(plus a PlannerAgent and a fresh DB session) per call.
"""

from __future__ import annotations

import os

from app.agents.planner.planner_agent import PlannerAgent
from app.agents.planner.llm_provider import GeminiProvider
from app.agents.researcher.research_agent import ResearchAgent
from app.agents.writer.agent import WriterAgent
from app.agents.analysis.agent import AnalysisAgent
from app.agents.verifier.agent import VerificationAgent

from app.api_wiring.dispatcher import AgentDispatcher
from app.database.repositories import PostgresTaskRepository, PostgresWorkflowRepository
from app.database.session import AsyncSessionLocal
from app.orchestrator.engine import WorkflowExecutionEngine
from app.registry.agent_registry import AgentRegistry
from app.registry.models import AgentProfile, HealthStatus
from app.scheduler.dynamic_scheduler import DynamicTaskScheduler

_shared_registry: AgentRegistry | None = None


def _get_shared_registry() -> AgentRegistry:
    global _shared_registry
    if _shared_registry is not None:
        return _shared_registry

    registry = AgentRegistry()

    registry.register(AgentProfile(
        agent_id="researcher-1", name="Researcher", description="Web/document/knowledge research",
        capabilities=frozenset({"web_search", "summarization", "research"}), supported_tools=frozenset(),
        supported_task_types=frozenset({"research"}), priority=5, max_concurrency=5,
        health_status=HealthStatus.ACTIVE, current_load=0,
    ))

    registry.register(AgentProfile(
        agent_id="writer-1", name="Writer", description="Content writing and aggregation",
        capabilities=frozenset({"writing", "drafting"}), supported_tools=frozenset(),
        supported_task_types=frozenset({"writing"}), priority=5, max_concurrency=5,
        health_status=HealthStatus.ACTIVE, current_load=0,
    ))

    registry.register(AgentProfile(
        agent_id="analyzer-1", name="Analyzer", description="Data and text analysis",
        capabilities=frozenset({"analysis", "data_extraction"}), supported_tools=frozenset(),
        supported_task_types=frozenset({"analysis"}), priority=5, max_concurrency=5,
        health_status=HealthStatus.ACTIVE, current_load=0,
    ))

    registry.register(AgentProfile(
        agent_id="verifier-1", name="Verifier", description="Quality assurance and validation",
        capabilities=frozenset({"verification", "qa"}), supported_tools=frozenset(),
        supported_task_types=frozenset({"verification"}), priority=5, max_concurrency=5,
        health_status=HealthStatus.ACTIVE, current_load=0,
    ))

    # No dedicated agent classes exist for coding/planning/custom task
    # types (only research/writer/analysis/verifier are implemented as
    # .execute()-based agents -- PlannerAgent only exposes .plan(), not
    # .execute(), so it cannot be wired through the dispatcher). These
    # three task types are routed to the Research agent as the closest
    # general-purpose fit so workflows don't fail outright.
    registry.register(AgentProfile(
        agent_id="coder-1", name="Coder (fallback: Research)", description="Code generation tasks (routed to research agent)",
        capabilities=frozenset({"coding", "implementation"}), supported_tools=frozenset(),
        supported_task_types=frozenset({"coding"}), priority=5, max_concurrency=5,
        health_status=HealthStatus.ACTIVE, current_load=0,
    ))

    registry.register(AgentProfile(
        agent_id="planning-fallback-1", name="Planning (fallback: Research)", description="Planning subtasks (routed to research agent)",
        capabilities=frozenset({"planning"}), supported_tools=frozenset(),
        supported_task_types=frozenset({"planning"}), priority=5, max_concurrency=5,
        health_status=HealthStatus.ACTIVE, current_load=0,
    ))

    registry.register(AgentProfile(
        agent_id="custom-1", name="Custom (fallback: Research)", description="Custom/misc tasks (routed to research agent)",
        capabilities=frozenset({"custom", "general"}), supported_tools=frozenset(),
        supported_task_types=frozenset({"custom"}), priority=5, max_concurrency=5,
        health_status=HealthStatus.ACTIVE, current_load=0,
    ))

    _shared_registry = registry
    return registry


def _build_llm_provider():
    if _llm_provider_override is not None:
        return _llm_provider_override
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. The Planner Agent needs a real LLM "
            "provider to decompose queries -- set this in your .env file."
        )
    return GeminiProvider(api_key=api_key)


_llm_provider_override = None


def set_llm_provider_override(provider) -> None:
    global _llm_provider_override
    _llm_provider_override = provider


async def build_engine_for_request():
    session = AsyncSessionLocal()

    llm_provider = _build_llm_provider()
    planner = PlannerAgent(llm_provider)

    registry = _get_shared_registry()

    research_agent = ResearchAgent(llm_provider=llm_provider)
    writer_agent = WriterAgent(llm_provider=llm_provider)
    analysis_agent = AnalysisAgent(llm_provider=llm_provider)
    verification_agent = VerificationAgent(llm_provider=llm_provider)

    dispatcher = AgentDispatcher(
        registry,
        agent_instances={
            "research":     research_agent,
            "writing":      writer_agent,
            "analysis":     analysis_agent,
            "verification": verification_agent,
            "coding":       research_agent,
            "planning":     research_agent,
            "custom":       research_agent,
        }
    )

    task_repo = PostgresTaskRepository(session)
    workflow_repo = PostgresWorkflowRepository(session)
    scheduler = DynamicTaskScheduler()

    engine = WorkflowExecutionEngine(task_repo, workflow_repo, dispatcher, scheduler)
    return engine, planner, session