from __future__ import annotations

import logging
from typing import Any

from app.registry.agent_registry import AgentRegistry, NoEligibleAgentError
from app.registry.models import TaskRequirements
from app.scheduler.models import TaskNode

logger = logging.getLogger(__name__)

class DispatchError(Exception):
    """Raised when no agent could be resolved, or the resolved agent's
    execute() call itself raised."""

class AgentDispatcher:
    def __init__(self, registry: AgentRegistry, agent_instances: dict[str, Any]):
        self._registry = registry
        self._agents = agent_instances

    async def dispatch(self, task: TaskNode, context: dict[str, Any]) -> dict[str, Any]:
        requirements = TaskRequirements(task_type=task.task_type)

        try:
            agent_profile = self._registry.select_best(requirements)
        except NoEligibleAgentError as exc:
            raise DispatchError(f"No agent available for task_type='{task.task_type}': {exc}") from exc

        agent_instance = self._agents.get(task.task_type)
        if agent_instance is None:
            raise DispatchError(
                f"Registry selected agent '{agent_profile.agent_id}' for task_type="
                f"'{task.task_type}', but no agent instance is wired up for that "
                f"task_type in this dispatcher's agent_instances map."
            )

        self._registry.increment_load(agent_profile.agent_id, +1)
        try:
            output = await self._call_execute(agent_instance, task, context)
        except Exception as exc:  # noqa: BLE001
            raise DispatchError(f"Agent execution failed for task '{task.task_id}': {exc}") from exc
        finally:
            self._registry.increment_load(agent_profile.agent_id, -1)

        return output

    @staticmethod
    async def _call_execute(agent_instance: Any, task: TaskNode, context: dict[str, Any]) -> dict[str, Any]:
        task_input: dict[str, Any] = {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "description": task.description or f"Execute task {task.task_id}",
            "context": context,
        }
        
        result = await agent_instance.execute(task.task_id, task_input)

        if isinstance(result, tuple) and len(result) == 2:
            output_model, _log_events = result
        else:
            output_model = result

        if hasattr(output_model, "model_dump"):
            return output_model.model_dump(mode="json")
        if isinstance(output_model, dict):
            return output_model
        return {"result": str(output_model)}