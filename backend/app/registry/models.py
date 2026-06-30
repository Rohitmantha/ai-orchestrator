"""
Domain models for the Agent Registry.

Pure data, zero I/O -- consistent with every other domain-layer component
built so far (Planner, Scheduler). The Registry is bookkeeping + selection
logic over these models; it does not poll agents or manage their
lifecycle. Health and load are REPORTED IN by whatever owns agent
lifecycle (the Orchestrator, or a heartbeat process not yet built) via
`update_health` / `update_load` -- the Registry trusts what it's told,
the same way the Scheduler trusts the task statuses it's given.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class HealthStatus(str, Enum):
    """Mirrors the `agent_status` Postgres ENUM (schema.sql), renamed
    here to HealthStatus because in the Registry's vocabulary this is
    specifically about "can this agent currently take work" -- a
    narrower question than the DB column's full lifecycle (which also
    covers 'deprecated', a soft-retirement state the Registry treats
    the same as DISABLED for selection purposes)."""

    ACTIVE = "active"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"
    MAINTENANCE = "maintenance"

    @property
    def is_selectable(self) -> bool:
        """Only ACTIVE agents can ever be selected. This is a hard filter,
        not something a high score can override -- a 'maintenance' agent
        with priority 10 and zero load must never be chosen over an
        'active' agent with priority 1 and high load. Selectability and
        ranking are deliberately different axes."""
        return self == HealthStatus.ACTIVE


@dataclass(frozen=True)
class AgentProfile:
    """Everything the Registry needs to know about one agent in order to
    register it and later consider it for selection. Maps directly onto
    the `agents` table columns from schema.sql, plus `current_load` which
    is intentionally NOT a DB column (DB has `avg_latency_ms`/
    `success_rate` as rolling historical metrics; `current_load` is live,
    in-memory, changes every time a task starts/finishes -- persisting
    that to Postgres on every change would be pure write amplification
    for a number with the lifetime of a single process)."""

    agent_id: str
    name: str
    description: str
    capabilities: frozenset[str]
    supported_tools: frozenset[str]
    supported_task_types: frozenset[str]
    priority: int = 5  # 0-10, higher = more preferred all else equal
    max_concurrency: int = 5
    health_status: HealthStatus = HealthStatus.ACTIVE
    current_load: int = 0  # number of tasks this agent is currently executing

    def __post_init__(self) -> None:
        if not (0 <= self.priority <= 10):
            raise ValueError(f"priority must be 0-10, got {self.priority}")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if self.current_load < 0:
            raise ValueError("current_load cannot be negative")

    @property
    def is_at_capacity(self) -> bool:
        return self.current_load >= self.max_concurrency

    @property
    def load_ratio(self) -> float:
        """0.0 (idle) to 1.0+ (at or over capacity). A ratio rather than
        a raw count is what makes load comparable ACROSS agents with
        different max_concurrency -- an agent with 4/5 tasks running is
        more loaded than one with 4/20, even though the raw counts tie."""
        return self.current_load / self.max_concurrency


@dataclass(frozen=True)
class TaskRequirements:
    """What a task needs from whichever agent executes it -- the input
    side of selection. Built by the caller (Orchestrator) from a
    PlannedTask / `tasks` row, not constructed by the Registry itself."""

    task_type: str
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    required_tools: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class AgentScore:
    """One candidate agent's score for one task, plus the breakdown that
    produced it. Keeping the breakdown (not just the final float) is what
    makes the "no hardcoded if-else" selection auditable -- you can see
    WHY agent X beat agent Y without re-running the scoring function by
    hand, which matters a lot when this gets wired into execution_logs
    later for observability."""

    agent_id: str
    total_score: float
    priority_component: float
    availability_component: float
    load_component: float
