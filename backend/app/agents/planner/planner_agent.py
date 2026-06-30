"""
The Planner Agent.

Responsibilities (per spec):
  - Understand user intent
  - Break complex requests into executable subtasks
  - Create dependencies
  - Estimate execution order
  - Return JSON only

Architectural note: this class is an AGENT, not a USE CASE. Per the Clean
Architecture layering from the system design, this lives in the
infrastructure/agents layer -- it knows about LLM providers and prompts.
It does NOT touch the database. The Orchestrator's application-layer use
case (e.g. `DecomposeQueryUseCase`) is responsible for calling this agent
and then persisting the result as `tasks` / `task_dependencies` rows. That
boundary is what keeps this class unit-testable with a fake LLMProvider and
zero database mocking.

"Estimate execution order" is satisfied implicitly: the dependency graph
IS the execution order specification -- the Orchestrator's scheduler
(a separate component) topologically sorts it into parallel batches. The
Planner's job is to make sure that graph is genuinely correct, not to
pre-compute batches itself (that's the Scheduler's responsibility, and
duplicating it here would let the two disagree).
"""

from __future__ import annotations

import logging

from .llm_provider import LLMProvider, LLMProviderError
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import WorkflowPlan
from .validation import PlanValidationError, validate_plan

logger = logging.getLogger(__name__)

# Pulled from schemas.WorkflowPlan automatically -- see _build_json_schema().
_MAX_REPAIR_ATTEMPTS = 2


class PlannerAgentError(Exception):
    """Raised when the Planner Agent cannot produce a valid plan even
    after repair attempts. Carries the last set of validation errors so
    the caller (Orchestrator) can decide whether to surface a
    graceful-degradation response to the user, per the lifecycle design's
    Stage 3 failure handling."""

    def __init__(self, message: str, last_errors: list[str] | None = None):
        self.last_errors = last_errors or []
        super().__init__(message)


class PlannerAgent:
    def __init__(self, llm_provider: LLMProvider):
        self._llm = llm_provider

    async def plan(
        self,
        *,
        workflow_id: str,
        query: str,
        parsed_intent: dict | None = None,
    ) -> WorkflowPlan:
        """Produces a validated WorkflowPlan for the given query.

        Raises PlannerAgentError if no valid plan could be produced after
        retrying with the LLM's own validation errors fed back to it.
        """

        user_prompt = build_user_prompt(workflow_id, query, parsed_intent)
        json_schema = self._build_json_schema()

        last_errors: list[str] = []

        for attempt in range(1, _MAX_REPAIR_ATTEMPTS + 2):  # initial try + N repairs
            prompt_for_this_attempt = user_prompt
            if last_errors:
                prompt_for_this_attempt += (
                    "\n\nYour previous plan was INVALID for these reasons:\n"
                    + "\n".join(f"- {e}" for e in last_errors)
                    + "\n\nFix these issues and return a corrected plan."
                )

            try:
                raw = await self._llm.generate_structured(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=prompt_for_this_attempt,
                    json_schema=json_schema,
                    schema_name="workflow_plan",
                )
            except LLMProviderError as exc:
                logger.warning("Planner LLM call failed on attempt %d: %s", attempt, exc)
                # Provider-level failures (timeout, rate limit) are NOT the
                # same failure class as validation errors -- retrying with
                # "fix your errors" text would be nonsensical here. Let the
                # caller's retry policy (Stage 8 of the lifecycle) decide
                # whether to retry the whole call.
                raise PlannerAgentError(f"LLM provider failed: {exc}") from exc

            try:
                plan = WorkflowPlan.model_validate(raw)
            except Exception as exc:  # Pydantic ValidationError
                last_errors = [f"Schema error: {exc}"]
                logger.info(
                    "Planner output failed schema validation on attempt %d: %s",
                    attempt, last_errors,
                )
                continue

            # Force workflow_id to match what we were actually given --
            # never trust the LLM to echo it back correctly.
            plan.workflow_id = workflow_id

            result = validate_plan(plan)
            if result.is_valid:
                logger.info(
                    "Planner produced a valid plan for workflow %s: %d tasks, %d dependencies",
                    workflow_id, len(plan.tasks), len(plan.dependencies),
                )
                return plan

            last_errors = result.errors
            logger.info(
                "Planner output failed graph validation on attempt %d: %s",
                attempt, last_errors,
            )

        raise PlannerAgentError(
            f"Planner could not produce a valid plan after {_MAX_REPAIR_ATTEMPTS + 1} attempts",
            last_errors=last_errors,
        )

    @staticmethod
    def _build_json_schema() -> dict:
        """Hand-written JSON Schema mirroring schemas.WorkflowPlan, in the
        subset of JSON Schema that OpenAI's strict structured-output mode
        accepts (no `$ref` cycles, all fields required when strict=True,
        additionalProperties: false everywhere). Generating this from the
        Pydantic model directly is possible (`WorkflowPlan.model_json_schema()`)
        but strict mode has fussy requirements (every property must be
        listed in `required`, nested objects need their own
        `additionalProperties: false`) that differ slightly across
        provider SDKs -- writing it explicitly here keeps that mismatch
        visible and easy to adjust per-provider, rather than hidden inside
        a generator that may silently produce a shape one provider
        rejects.
        """
        task_schema = {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "name": {"type": "string"},
                "task_type": {
                    "type": "string",
                    "enum": [
                        "research", "coding", "analysis", "writing",
                        "verification", "planning", "custom",
                    ],
                },
                "description": {"type": "string"},
                "required_capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "acceptance_criteria": {"type": "string"},
                "priority": {"type": "integer"},
                "is_critical": {"type": "boolean"},
            },
            "required": [
                "task_id", "name", "task_type", "description",
                "required_capabilities", "acceptance_criteria",
                "priority", "is_critical",
            ],
            "additionalProperties": False,
        }

        dependency_schema = {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "depends_on_task_id": {"type": "string"},
                "dependency_type": {
                    "type": "string",
                    "enum": ["finish_to_start", "data_dependency", "soft"],
                },
            },
            "required": ["task_id", "depends_on_task_id", "dependency_type"],
            "additionalProperties": False,
        }

        return {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string"},
                "tasks": {"type": "array", "items": task_schema},
                "dependencies": {"type": "array", "items": dependency_schema},
            },
            "required": ["workflow_id", "tasks", "dependencies"],
            "additionalProperties": False,
        }
