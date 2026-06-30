"""
Tests for the Agent Registry.

Specifically probes the interactions that are easy to get subtly wrong:
  - capability filtering as a hard gate vs. score input
  - at-capacity agents always ranked after available ones, even when
    their raw weighted score would otherwise win
  - deterministic tie-breaking
  - diagnostic specificity when nothing matches
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "app"))

from registry.agent_registry import (
    AgentRegistry,
    DuplicateAgentError,
    NoEligibleAgentError,
)
from registry.models import AgentProfile, HealthStatus, TaskRequirements
from registry.scoring import WeightedAgentScoringStrategy


def make_agent(
    agent_id, capabilities=(), task_types=("research",), tools=(),
    priority=5, max_concurrency=5, current_load=0,
    health_status=HealthStatus.ACTIVE,
):
    return AgentProfile(
        agent_id=agent_id,
        name=agent_id,
        description=f"test agent {agent_id}",
        capabilities=frozenset(capabilities),
        supported_tools=frozenset(tools),
        supported_task_types=frozenset(task_types),
        priority=priority,
        max_concurrency=max_concurrency,
        current_load=current_load,
        health_status=health_status,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_register_and_get():
    registry = AgentRegistry()
    agent = make_agent("a1")
    registry.register(agent)
    assert registry.get("a1") is agent


def test_duplicate_registration_rejected():
    registry = AgentRegistry()
    registry.register(make_agent("a1"))
    with pytest.raises(DuplicateAgentError):
        registry.register(make_agent("a1"))


def test_invalid_priority_rejected_at_construction():
    with pytest.raises(ValueError, match="priority"):
        make_agent("a1", priority=11)


def test_negative_load_rejected_at_construction():
    with pytest.raises(ValueError, match="current_load"):
        make_agent("a1", current_load=-1)


# ---------------------------------------------------------------------------
# Eligibility filtering (the hard gate)
# ---------------------------------------------------------------------------

def test_agent_missing_task_type_is_not_eligible():
    registry = AgentRegistry()
    registry.register(make_agent("a1", task_types=("coding",)))
    reqs = TaskRequirements(task_type="research")
    assert registry.find_eligible_agents(reqs) == []


def test_agent_missing_required_capability_is_not_eligible():
    registry = AgentRegistry()
    registry.register(make_agent("a1", task_types=("research",), capabilities=("web_search",)))
    reqs = TaskRequirements(task_type="research", required_capabilities=frozenset({"sql_generation"}))
    assert registry.find_eligible_agents(reqs) == []


def test_agent_with_superset_of_capabilities_is_eligible():
    registry = AgentRegistry()
    registry.register(make_agent(
        "a1", task_types=("research",),
        capabilities=("web_search", "summarization", "translation"),
    ))
    reqs = TaskRequirements(task_type="research", required_capabilities=frozenset({"web_search"}))
    assert len(registry.find_eligible_agents(reqs)) == 1


def test_disabled_agent_is_never_eligible_regardless_of_fit():
    registry = AgentRegistry()
    registry.register(make_agent(
        "perfect_but_disabled", task_types=("research",), capabilities=("web_search",),
        priority=10, current_load=0, health_status=HealthStatus.DISABLED,
    ))
    reqs = TaskRequirements(task_type="research", required_capabilities=frozenset({"web_search"}))
    assert registry.find_eligible_agents(reqs) == []


def test_maintenance_and_deprecated_are_also_not_selectable():
    for status in (HealthStatus.MAINTENANCE, HealthStatus.DEPRECATED):
        registry = AgentRegistry()
        registry.register(make_agent("a1", task_types=("research",), health_status=status))
        reqs = TaskRequirements(task_type="research")
        assert registry.find_eligible_agents(reqs) == [], f"failed for {status}"


def test_required_tools_also_gate_eligibility():
    registry = AgentRegistry()
    registry.register(make_agent("a1", task_types=("coding",), tools=("python_repl",)))
    reqs = TaskRequirements(task_type="coding", required_tools=frozenset({"sql_executor"}))
    assert registry.find_eligible_agents(reqs) == []


# ---------------------------------------------------------------------------
# Ranking / selection -- the "no hardcoded if-else" scoring behavior
# ---------------------------------------------------------------------------

def test_higher_priority_wins_when_load_and_availability_tie():
    registry = AgentRegistry()
    registry.register(make_agent("low_priority", priority=2, task_types=("research",)))
    registry.register(make_agent("high_priority", priority=9, task_types=("research",)))
    reqs = TaskRequirements(task_type="research")
    best = registry.select_best(reqs)
    assert best.agent_id == "high_priority"


def test_lower_load_wins_when_priority_ties():
    registry = AgentRegistry()
    registry.register(make_agent("busy", priority=5, max_concurrency=10, current_load=8, task_types=("research",)))
    registry.register(make_agent("idle", priority=5, max_concurrency=10, current_load=0, task_types=("research",)))
    reqs = TaskRequirements(task_type="research")
    best = registry.select_best(reqs)
    assert best.agent_id == "idle"


def test_at_capacity_agent_always_ranked_after_available_agent_even_with_lower_priority():
    """The critical interaction: an available agent with LOW priority
    must still outrank an at-capacity agent with MAX priority. If
    availability were just one more additive score component, a large
    enough priority gap could let an at-capacity agent win -- this test
    locks in that it cannot, by design (see scoring.py + agent_registry.py
    docstrings on why at-capacity is a sort-order gate, not just a
    score penalty)."""
    registry = AgentRegistry()
    registry.register(make_agent(
        "maxed_out_vip", priority=10, max_concurrency=1, current_load=1, task_types=("research",),
    ))
    registry.register(make_agent(
        "available_low_priority", priority=1, max_concurrency=10, current_load=5, task_types=("research",),
    ))
    reqs = TaskRequirements(task_type="research")
    best = registry.select_best(reqs)
    assert best.agent_id == "available_low_priority"


def test_select_best_falls_back_to_at_capacity_agent_if_nothing_else_eligible():
    """If EVERY eligible agent is at capacity, select_best should still
    return the best-scored one among them (with a warning) rather than
    raising -- the caller (Orchestrator) decides whether to queue, not
    the Registry. Only a total absence of eligible agents should raise."""
    registry = AgentRegistry()
    registry.register(make_agent(
        "only_option", priority=5, max_concurrency=1, current_load=1, task_types=("research",),
    ))
    reqs = TaskRequirements(task_type="research")
    best = registry.select_best(reqs)
    assert best.agent_id == "only_option"


def test_ranking_is_deterministic_on_exact_ties():
    registry = AgentRegistry()
    registry.register(make_agent("z_agent", priority=5, task_types=("research",)))
    registry.register(make_agent("a_agent", priority=5, task_types=("research",)))
    reqs = TaskRequirements(task_type="research")
    ranked_once = [a.agent_id for a, _ in registry.rank_eligible_agents(reqs)]
    ranked_twice = [a.agent_id for a, _ in registry.rank_eligible_agents(reqs)]
    assert ranked_once == ranked_twice
    assert ranked_once[0] == "a_agent"  # alphabetical tiebreak on exact score tie


def test_scoring_uses_only_declared_attributes_not_agent_identity():
    """Spot-check that the registry never branches on agent_id/name --
    two agents with identical declared attributes but different names
    must score identically."""
    registry = AgentRegistry()
    registry.register(make_agent("agent_alpha", priority=7, max_concurrency=10, current_load=3, task_types=("research",)))
    registry.register(make_agent("agent_beta", priority=7, max_concurrency=10, current_load=3, task_types=("research",)))
    reqs = TaskRequirements(task_type="research")
    ranked = registry.rank_eligible_agents(reqs)
    scores = {agent_id: score.total_score for (agent, score) in ranked for agent_id in [agent.agent_id]}
    assert scores["agent_alpha"] == scores["agent_beta"]


# ---------------------------------------------------------------------------
# Custom scoring strategy injection
# ---------------------------------------------------------------------------

def test_custom_scoring_strategy_is_used():
    """Confirms the Strategy pattern actually works end to end -- a
    strategy that weights load at 100% should let a low-priority, idle
    agent beat a high-priority, busy one."""
    registry = AgentRegistry(
        scoring_strategy=WeightedAgentScoringStrategy(
            priority_weight=0.0, availability_weight=0.0, load_weight=1.0,
        )
    )
    registry.register(make_agent("idle_low_priority", priority=1, max_concurrency=10, current_load=0, task_types=("research",)))
    registry.register(make_agent("busy_high_priority", priority=10, max_concurrency=10, current_load=9, task_types=("research",)))
    reqs = TaskRequirements(task_type="research")
    best = registry.select_best(reqs)
    assert best.agent_id == "idle_low_priority"


# ---------------------------------------------------------------------------
# No-match diagnostics
# ---------------------------------------------------------------------------

def test_no_eligible_agent_raises_with_task_type_diagnosis():
    registry = AgentRegistry()
    registry.register(make_agent("a1", task_types=("coding",)))
    with pytest.raises(NoEligibleAgentError) as exc_info:
        registry.select_best(TaskRequirements(task_type="research"))
    assert "no registered agent declares support for task_type" in exc_info.value.reason


def test_no_eligible_agent_raises_with_capability_diagnosis():
    registry = AgentRegistry()
    registry.register(make_agent("a1", task_types=("research",), capabilities=("web_search",)))
    with pytest.raises(NoEligibleAgentError) as exc_info:
        registry.select_best(
            TaskRequirements(task_type="research", required_capabilities=frozenset({"sql_generation"}))
        )
    assert "none have all required capabilities" in exc_info.value.reason


def test_no_eligible_agent_raises_with_health_diagnosis():
    registry = AgentRegistry()
    registry.register(make_agent("a1", task_types=("research",), health_status=HealthStatus.MAINTENANCE))
    with pytest.raises(NoEligibleAgentError) as exc_info:
        registry.select_best(TaskRequirements(task_type="research"))
    assert "not in a selectable health state" in exc_info.value.reason


def test_empty_registry_raises_not_crashes():
    registry = AgentRegistry()
    with pytest.raises(NoEligibleAgentError):
        registry.select_best(TaskRequirements(task_type="research"))


# ---------------------------------------------------------------------------
# Live state updates (health / load reported in)
# ---------------------------------------------------------------------------

def test_update_health_changes_eligibility_immediately():
    registry = AgentRegistry()
    registry.register(make_agent("a1", task_types=("research",)))
    reqs = TaskRequirements(task_type="research")
    assert len(registry.find_eligible_agents(reqs)) == 1

    registry.update_health("a1", HealthStatus.MAINTENANCE)
    assert registry.find_eligible_agents(reqs) == []

    registry.update_health("a1", HealthStatus.ACTIVE)
    assert len(registry.find_eligible_agents(reqs)) == 1


def test_increment_load_affects_ranking():
    registry = AgentRegistry()
    registry.register(make_agent("a1", priority=5, max_concurrency=2, current_load=0, task_types=("research",)))
    registry.register(make_agent("a2", priority=5, max_concurrency=2, current_load=0, task_types=("research",)))
    reqs = TaskRequirements(task_type="research")

    # a1 wins the tiebreak alphabetically while both are idle
    assert registry.select_best(reqs).agent_id == "a1"

    registry.increment_load("a1", 2)  # a1 now at capacity (2/2)
    assert registry.select_best(reqs).agent_id == "a2"

    registry.increment_load("a1", -2)  # back to idle
    assert registry.select_best(reqs).agent_id == "a1"


def test_increment_load_clamped_at_zero():
    registry = AgentRegistry()
    registry.register(make_agent("a1", current_load=0))
    registry.increment_load("a1", -5)
    assert registry.get("a1").current_load == 0


def test_agent_profile_is_immutable():
    agent = make_agent("a1")
    with pytest.raises(Exception):
        agent.current_load = 99  # frozen dataclass -- direct mutation must fail


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
