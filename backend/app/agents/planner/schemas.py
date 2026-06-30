"""
Output schemas for the Planner Agent.

These define the EXACT shape the LLM must return. Using Pydantic models
(rather than trusting raw LLM JSON) gives us two things for free:
  1. The LLM provider's structured-output / function-calling mode can be
     handed this schema directly, which is far more reliable than asking
     for JSON in plain prose.
  2. Anything that doesn't match this shape fails loudly at the boundary,
     before it ever reaches dependency-graph validation or the database.

Field names intentionally match the schema columns from the SQL design
(task_type, priority, acceptance_criteria, etc.) so the Orchestrator can
map this straight onto `tasks` / `task_dependencies` rows without a
translation layer.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TaskType(str, Enum):
    """Mirrors the `task_type` Postgres ENUM. Kept in sync manually since
    the agent layer and DB layer are deliberately decoupled (Clean
    Architecture: domain doesn't import infrastructure)."""

    RESEARCH = "research"
    CODING = "coding"
    ANALYSIS = "analysis"
    WRITING = "writing"
    VERIFICATION = "verification"
    PLANNING = "planning"
    CUSTOM = "custom"


class DependencyType(str, Enum):
    """Mirrors the `dependency_type` Postgres ENUM."""

    FINISH_TO_START = "finish_to_start"
    DATA_DEPENDENCY = "data_dependency"
    SOFT = "soft"


class PlannedTask(BaseModel):
    """A single executable subtask produced by decomposition.

    `task_id` is a small string the LLM invents (e.g. "t1", "t2") purely to
    let `dependencies` reference tasks within this same response. It is NOT
    a database UUID -- the Orchestrator generates real UUIDs at persistence
    time and remaps these local IDs. Conflating the two would mean trusting
    an LLM to generate globally-unique primary keys, which we don't.
    """

    task_id: str = Field(
        ...,
        description="Local identifier unique within this plan only, e.g. 't1'.",
        min_length=1,
        max_length=50,
    )
    name: str = Field(..., min_length=1, max_length=500)
    task_type: TaskType
    description: str = Field(
        ...,
        description="Self-contained instructions for the agent that executes this task. "
        "Must include enough context to run independently -- assume the executor "
        "has NOT seen the original user query.",
    )
    required_capabilities: list[str] = Field(
        default_factory=list,
        description="Capability tags this task needs from an agent, e.g. ['web_search'].",
    )
    acceptance_criteria: str = Field(
        ...,
        description="Concrete, checkable statement of what a correct result looks like. "
        "Consumed later by the Verification Agent.",
    )
    priority: int = Field(default=0, ge=0, le=10)
    is_critical: bool = Field(
        default=True,
        description="If True, this task failing permanently fails the whole workflow. "
        "If False, the workflow may still complete in a 'degraded' state without it.",
    )

    @field_validator("task_id")
    @classmethod
    def task_id_no_whitespace(cls, v: str) -> str:
        if not v.strip() or " " in v:
            raise ValueError("task_id must be a single token with no spaces")
        return v.strip()


class PlannedDependency(BaseModel):
    """A single DAG edge: `task_id` depends on `depends_on_task_id`."""

    task_id: str
    depends_on_task_id: str
    dependency_type: DependencyType = DependencyType.FINISH_TO_START

    @field_validator("depends_on_task_id")
    @classmethod
    def no_self_dependency(cls, v: str, info: Any) -> str:
        task_id = info.data.get("task_id")
        if task_id is not None and v == task_id:
            raise ValueError("a task cannot depend on itself")
        return v


class WorkflowPlan(BaseModel):
    """Top-level output contract -- matches the shape requested in the prompt."""

    workflow_id: str
    tasks: list[PlannedTask] = Field(..., min_length=1)
    dependencies: list[PlannedDependency] = Field(default_factory=list)

    model_config = {"extra": "forbid"}  # reject unexpected fields from the LLM
