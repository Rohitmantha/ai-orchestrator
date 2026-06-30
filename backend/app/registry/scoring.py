"""
Scoring strategies for ranking agents that have already passed the
capability/health eligibility filter.

This is the "Strategy pattern" half of the no-hardcoded-if-else
requirement: WHICH eligible agent wins is determined by a pluggable
scoring function operating uniformly over every agent's declared
attributes (priority, load), never by special-casing specific agents or
task types in branching code. Swapping how "best" is defined later (e.g.
weighting load more heavily once the system is under heavier concurrency
pressure) means writing a new strategy class, not editing the Registry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import AgentProfile, AgentScore, TaskRequirements


class AgentScoringStrategy(ABC):
    """Port: anything that can rank one already-eligible agent for one
    task. The Registry calls this once per eligible candidate and sorts
    by the result -- it never inspects task_type or agent identity itself
    to decide how to score; all of that lives inside the strategy,
    operating on the same generic fields for every agent."""

    @abstractmethod
    def score(self, agent: AgentProfile, requirements: TaskRequirements) -> AgentScore:
        raise NotImplementedError


class WeightedAgentScoringStrategy(AgentScoringStrategy):
    """Default strategy: a weighted sum of three normalized components.

      - priority_component:      agent.priority / 10           (0.0 - 1.0)
      - availability_component:  1.0 if not at capacity else 0.0
      - load_component:          1.0 - load_ratio, clamped to >= 0
                                  (lower current load -> higher score)

    Availability is intentionally close to a hard gate rather than a
    smooth curve: a non-zero score for an at-capacity agent would let
    enough priority "buy through" capacity, defeating the point of
    max_concurrency as a real limit. An agent at or over capacity gets
    availability_component = 0, which a sufficiently large priority
    weight could in principle still outscore on priority + load alone --
    so the Registry additionally treats at-capacity agents as listed
    LAST regardless of score (see registry.py), rather than relying on
    weights alone to enforce that ordering.
    """

    def __init__(
        self,
        priority_weight: float = 0.4,
        availability_weight: float = 0.3,
        load_weight: float = 0.3,
    ):
        total = priority_weight + availability_weight + load_weight
        if total <= 0:
            raise ValueError("at least one weight must be positive")
        # Normalize so weights always sum to 1.0 regardless of what was
        # passed in -- keeps total_score in a predictable 0.0-1.0 range.
        self._priority_weight = priority_weight / total
        self._availability_weight = availability_weight / total
        self._load_weight = load_weight / total

    def score(self, agent: AgentProfile, requirements: TaskRequirements) -> AgentScore:
        priority_component = agent.priority / 10.0
        availability_component = 0.0 if agent.is_at_capacity else 1.0
        load_component = max(0.0, 1.0 - agent.load_ratio)

        total = (
            priority_component * self._priority_weight
            + availability_component * self._availability_weight
            + load_component * self._load_weight
        )

        return AgentScore(
            agent_id=agent.agent_id,
            total_score=total,
            priority_component=priority_component,
            availability_component=availability_component,
            load_component=load_component,
        )
