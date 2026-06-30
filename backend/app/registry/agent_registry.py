"""
The Agent Registry.

Responsibilities (per spec):
  - Every agent registers: name, description, capabilities, priority,
    supported tools, supported task types, health status, current load
  - The scheduler dynamically selects the best agent based on:
    capabilities, availability, priority, load
  - No hardcoded if-else logic

Selection is a two-phase process, and the two phases are deliberately NOT
collapsed into one scoring pass:

  Phase 1 -- ELIGIBILITY (hard filter, boolean, no scoring involved):
    an agent is eligible for a task iff its health is selectable AND it
    has every capability/tool the task requires AND it supports the
    task's type. None of this is negotiable via score -- an incapable or
    unhealthy agent is never a candidate, full stop.

  Phase 2 -- RANKING (soft, via AgentScoringStrategy):
    among the eligible survivors, rank by score (priority/availability/
    load), with at-capacity agents always sorted after available ones
    regardless of score, since "available" is closer to a second
    eligibility gate than a scoring input (see scoring.py docstring).

Keeping these phases separate is what actually satisfies "no hardcoded
if-else logic" in spirit, not just in letter: eligibility is a uniform
set-membership check evaluated identically for every (agent, task)
pair -- there is nowhere in this file that branches on a specific
task_type string or a specific agent name.
"""

from __future__ import annotations

import logging

from .models import AgentProfile, AgentScore, HealthStatus, TaskRequirements
from .scoring import AgentScoringStrategy, WeightedAgentScoringStrategy

logger = logging.getLogger(__name__)


class AgentRegistryError(Exception):
    """Base class for registry errors."""


class DuplicateAgentError(AgentRegistryError):
    pass


class AgentNotFoundError(AgentRegistryError):
    pass


class NoEligibleAgentError(AgentRegistryError):
    """Raised when no registered agent can handle a task at all. Carries
    enough detail for the caller to produce a useful error rather than a
    generic failure -- this is the case flagged back in the lifecycle
    design (Stage 6) that should trigger graceful degradation, not a
    silent stall."""

    def __init__(self, requirements: TaskRequirements, reason: str):
        self.requirements = requirements
        self.reason = reason
        super().__init__(
            f"No eligible agent for task_type='{requirements.task_type}' "
            f"capabilities={sorted(requirements.required_capabilities)}: {reason}"
        )


class AgentRegistry:
    def __init__(self, scoring_strategy: AgentScoringStrategy | None = None):
        self._agents: dict[str, AgentProfile] = {}
        self._scoring_strategy = scoring_strategy or WeightedAgentScoringStrategy()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, agent: AgentProfile) -> None:
        """Registers a new agent. Re-registering the same agent_id is an
        error -- use update_health/update_load for routine state changes,
        or deregister() + register() for an intentional replacement, so
        that an accidental double-register (e.g. two startup scripts
        both registering the same agent) is loud rather than silently
        overwriting state."""
        if agent.agent_id in self._agents:
            raise DuplicateAgentError(
                f"Agent '{agent.agent_id}' is already registered. "
                f"Use update_health()/update_load() to change its state, "
                f"or deregister() first to replace it."
            )
        self._agents[agent.agent_id] = agent
        logger.info(
            "Registered agent '%s' (%s): capabilities=%s, task_types=%s, priority=%d",
            agent.agent_id, agent.name, sorted(agent.capabilities),
            sorted(agent.supported_task_types), agent.priority,
        )

    def deregister(self, agent_id: str) -> None:
        if agent_id not in self._agents:
            raise AgentNotFoundError(f"Agent '{agent_id}' is not registered")
        del self._agents[agent_id]
        logger.info("Deregistered agent '%s'", agent_id)

    def get(self, agent_id: str) -> AgentProfile:
        if agent_id not in self._agents:
            raise AgentNotFoundError(f"Agent '{agent_id}' is not registered")
        return self._agents[agent_id]

    def list_all(self) -> list[AgentProfile]:
        return list(self._agents.values())

    # ------------------------------------------------------------------
    # State updates (health / load reported in by the Orchestrator)
    # ------------------------------------------------------------------

    def update_health(self, agent_id: str, health_status: HealthStatus) -> None:
        agent = self.get(agent_id)
        self._agents[agent_id] = _replace_frozen(agent, health_status=health_status)
        logger.info("Agent '%s' health -> %s", agent_id, health_status.value)

    def update_load(self, agent_id: str, current_load: int) -> None:
        agent = self.get(agent_id)
        if current_load < 0:
            raise ValueError("current_load cannot be negative")
        self._agents[agent_id] = _replace_frozen(agent, current_load=current_load)

    def increment_load(self, agent_id: str, delta: int = 1) -> None:
        """Convenience for the common case: Orchestrator calls this with
        +1 when dispatching a task to this agent, -1 when it completes.
        Clamped at 0 so a delayed/duplicate -1 (e.g. from a retry race)
        can't push load negative."""
        agent = self.get(agent_id)
        new_load = max(0, agent.current_load + delta)
        self._agents[agent_id] = _replace_frozen(agent, current_load=new_load)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def is_eligible(self, agent: AgentProfile, requirements: TaskRequirements) -> bool:
        """The hard filter. Pure set-membership / equality checks --
        deliberately uniform across every agent and task_type, which is
        what keeps this free of per-case branching. `frozenset.issubset`
        is the mechanism: "does this task's requirement set fit inside
        what the agent declares it supports", evaluated the same way no
        matter what's in either set."""
        if not agent.health_status.is_selectable:
            return False
        if requirements.task_type not in agent.supported_task_types:
            return False
        if not requirements.required_capabilities.issubset(agent.capabilities):
            return False
        if not requirements.required_tools.issubset(agent.supported_tools):
            return False
        return True

    def find_eligible_agents(self, requirements: TaskRequirements) -> list[AgentProfile]:
        return [a for a in self._agents.values() if self.is_eligible(a, requirements)]

    def rank_eligible_agents(
        self, requirements: TaskRequirements
    ) -> list[tuple[AgentProfile, AgentScore]]:
        """Returns eligible agents paired with their score, best first.
        Exposed separately from select_best() so callers (or tests, or a
        future admin UI) can see the full ranking and the reasoning
        behind it, not just the winner -- this is the "auditable" part
        of avoiding hardcoded logic: you can answer "why wasn't agent Y
        chosen" by inspecting its score breakdown, not by reading
        if-else branches."""
        eligible = self.find_eligible_agents(requirements)
        scored = [(a, self._scoring_strategy.score(a, requirements)) for a in eligible]

        # At-capacity agents sort after available ones, regardless of
        # score -- see scoring.py's docstring for why this isn't left to
        # weights alone. Stable secondary sort key after that is the
        # score itself; tertiary is agent_id, purely so the ordering is
        # deterministic when two agents tie exactly (avoids the result
        # depending on dict iteration order, which Python does guarantee
        # as insertion order, but relying on that implicitly would be
        # fragile and surprising to a future reader).
        scored.sort(
            key=lambda pair: (
                pair[0].is_at_capacity,       # False (available) sorts before True
                -pair[1].total_score,
                pair[0].agent_id,
            )
        )
        return scored

    def select_best(self, requirements: TaskRequirements) -> AgentProfile:
        """The main entry point the Scheduler/Orchestrator calls: given
        what a task needs, return the single best-fit agent.

        Raises NoEligibleAgentError if nothing qualifies -- this is a
        signal to the caller, not a state to swallow silently (per the
        lifecycle design's Stage 6 failure handling)."""
        ranked = self.rank_eligible_agents(requirements)
        if not ranked:
            reason = self._diagnose_no_match(requirements)
            raise NoEligibleAgentError(requirements, reason)

        best_agent, best_score = ranked[0]
        if best_agent.is_at_capacity:
            logger.warning(
                "Selected agent '%s' for task_type='%s' but it is AT CAPACITY "
                "(%d/%d) -- no available agent existed; caller should queue "
                "rather than dispatch immediately.",
                best_agent.agent_id, requirements.task_type,
                best_agent.current_load, best_agent.max_concurrency,
            )
        logger.info(
            "Selected agent '%s' for task_type='%s' (score=%.3f, priority=%d, load=%d/%d)",
            best_agent.agent_id, requirements.task_type, best_score.total_score,
            best_agent.priority, best_agent.current_load, best_agent.max_concurrency,
        )
        return best_agent

    def _diagnose_no_match(self, requirements: TaskRequirements) -> str:
        """Produces a specific reason for why nothing matched, so a
        NoEligibleAgentError is actionable rather than a generic "no
        agent found". Checks in order: any agent support this task_type
        at all? any agent (regardless of type) have the capabilities?
        is everything just unhealthy right now?"""
        by_task_type = [a for a in self._agents.values() if requirements.task_type in a.supported_task_types]
        if not by_task_type:
            return f"no registered agent declares support for task_type '{requirements.task_type}'"

        by_capability = [a for a in by_task_type if requirements.required_capabilities.issubset(a.capabilities)]
        if not by_capability:
            return (
                f"agents support task_type '{requirements.task_type}' but none have "
                f"all required capabilities {sorted(requirements.required_capabilities)}"
            )

        healthy = [a for a in by_capability if a.health_status.is_selectable]
        if not healthy:
            return (
                "a capable agent exists but is not in a selectable health state "
                f"(statuses: {sorted({a.health_status.value for a in by_capability})})"
            )

        return "no agent satisfied all eligibility checks simultaneously"


def _replace_frozen(agent: AgentProfile, **changes) -> AgentProfile:
    """AgentProfile is frozen (immutable) by design -- registered agent
    state should never be mutated in place while something else might be
    mid-read of it (e.g. mid-ranking). Updates always produce a new
    instance; the Registry swaps the dict entry atomically."""
    from dataclasses import replace

    return replace(agent, **changes)
