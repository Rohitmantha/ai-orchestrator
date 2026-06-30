import logging
import asyncio
from typing import Dict, Any, Optional

from app.agents.planner.planner import PlannerAgent
from app.agents.universal.agent import UniversalAgent
from app.scheduler.scheduler import DynamicTaskScheduler, TaskStatus
from app.registry.registry import AgentRegistry

logger = logging.getLogger(__name__)


class WorkflowExecutionEngine:
    """
    Manages the full lifecycle of AI workflows:
      1. register_pending()  → stores intent, marks 'pending'
      2. plan_and_run()      → background: plan → execute → complete
      3. get_state()         → returns current snapshot for polling

    POST /workflow returns in <100ms.
    All LLM work is async-safe via run_in_executor.
    """

    def __init__(self, registry: AgentRegistry):
        self.registry = registry
        self.planner = PlannerAgent()
        self.agent = UniversalAgent()

        # workflow_id → state dict
        self._states: Dict[str, Dict[str, Any]] = {}

    # ─────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────

    def register_pending(self, workflow_id: str, intent: str) -> None:
        """Called by the endpoint immediately — no LLM, no blocking."""
        self._states[workflow_id] = {
            "status": "pending",
            "intent": intent,
            "tasks": [],
            "result": None,
            "error": None,
            "logs": [{"message": "Workflow accepted, planning will begin shortly.", "level": "INFO"}],
        }
        logger.info(f"[{workflow_id}] Registered as pending.")

    def get_state(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        return self._states.get(workflow_id)

    def cancel(self, workflow_id: str) -> None:
        if workflow_id in self._states:
            self._states[workflow_id]["status"] = "cancelled"

    async def plan_and_run(self, workflow_id: str, intent: str) -> None:
        """Full background execution: plan → run DAG → store result."""
        self._log(workflow_id, f"Starting planning for: {intent!r}")
        self._set_status(workflow_id, "planning")

        try:
            # ── 1. Plan ──────────────────────────────────────────────────────
            loop = asyncio.get_event_loop()
            
            def plan_cb(msg, lvl):
                self._log(workflow_id, f"[Planner] {msg}", level=lvl)
                
            plan = await loop.run_in_executor(
                None, lambda: self.planner.generate_plan(intent, workflow_id, log_cb=plan_cb)
            )
            self._log(workflow_id, f"Plan created: {[t.task_id for t in plan.tasks]}")

            # ── 2. Build task state entries ──────────────────────────────────
            task_meta: Dict[str, Any] = {}
            for td in plan.tasks:
                task_meta[td.task_id] = td.model_dump()
                self._upsert_task(workflow_id, {
                    "task_id": td.task_id,
                    "name": td.name,
                    "task_type": ", ".join(td.required_capabilities),
                    "status": "pending",
                    "result": None,
                    "error_message": None,
                    "agent_name": None,
                    "execution_order": list(task_meta.keys()).index(td.task_id),
                    "dependencies": [],  # filled after scheduler loads
                })

            # ── 3. Build scheduler ───────────────────────────────────────────
            scheduler = DynamicTaskScheduler()
            scheduler.load_from_planner(plan.model_dump())

            # Patch in real dependency data
            for td_id, task_node in scheduler.tasks.items():
                self._patch_task(workflow_id, td_id, {
                    "dependencies": list(task_node.dependencies)
                })

            self._set_status(workflow_id, "running")
            task_outputs: Dict[str, str] = {}

            # ── 4. Execute DAG ───────────────────────────────────────────────
            max_iters = 60
            for _ in range(max_iters):
                wf_status = scheduler.get_workflow_status()
                if wf_status not in ["PENDING", "RUNNING"]:
                    break

                scheduler.check_timeouts()
                executable = scheduler.get_executable_tasks()

                if not executable:
                    running = any(t.status == TaskStatus.RUNNING for t in scheduler.tasks.values())
                    if not running:
                        logger.warning(f"[{workflow_id}] No runnable tasks, breaking.")
                        break
                    await asyncio.sleep(1)
                    continue

                self._log(workflow_id, f"Executing {len(executable)} task(s) in parallel: {[t.task_id for t in executable]}")

                await asyncio.gather(*[
                    self._run_task(workflow_id, task_node, task_meta, task_outputs, scheduler)
                    for task_node in executable
                ])

            # ── 5. Finalize ──────────────────────────────────────────────────
            final_status = scheduler.get_workflow_status()
            result = self._extract_result(scheduler, task_outputs)

            self._set_status(workflow_id, final_status.lower(), result=result)
            self._log(workflow_id, f"Workflow finished: {final_status}")

        except Exception as e:
            logger.error(f"[{workflow_id}] plan_and_run crashed: {e}", exc_info=True)
            self._set_status(workflow_id, "failed", error=str(e))
            self._log(workflow_id, f"FATAL: {e}", level="ERROR")

    # ─────────────────────────────────────────────
    #  Internal helpers
    # ─────────────────────────────────────────────

    async def _run_task(self, workflow_id: str, task_node,
                        task_meta: Dict, task_outputs: Dict, scheduler) -> None:
        """Executes a single task node asynchronously."""
        tid = task_node.task_id
        meta = task_meta.get(tid, {})
        capabilities = meta.get("required_capabilities", ["text_generation"])
        description = meta.get("description", tid)

        # Build plain-text context from dependency outputs
        context_parts = []
        for dep_id in task_node.dependencies:
            if dep_id in task_outputs:
                dep_name = task_meta.get(dep_id, {}).get("name", dep_id)
                context_parts.append(f"### {dep_name} output:\n{task_outputs[dep_id]}")
        context = "\n\n".join(context_parts) if context_parts else ""

        scheduler.mark_task_running(tid)
        self._patch_task(workflow_id, tid, {"status": "running"})
        self._log(workflow_id, f"Task '{tid}' started → {capabilities}")

        try:
            loop = asyncio.get_event_loop()
            
            def cb(msg, lvl):
                self._log(workflow_id, f"[{tid}] {msg}", level=lvl)
                
            output = await loop.run_in_executor(
                None, lambda: self.agent.execute(
                    meta.get("name", tid), description, capabilities, context, log_cb=cb
                )
            )
            task_outputs[tid] = output
            scheduler.mark_task_completed(tid)
            self._patch_task(workflow_id, tid, {
                "status": "completed",
                "result": output[:2000],  # truncate for UI display
                "agent_name": self.agent._pick_agent(capabilities, description).name,
            })
            self._log(workflow_id, f"Task '{tid}' completed ({len(output)} chars)")

        except Exception as e:
            logger.error(f"[{workflow_id}] Task '{tid}' failed: {e}", exc_info=True)
            error_msg = str(e)
            task_outputs[tid] = f"Error: {error_msg}"
            scheduler.mark_task_completed(tid)  # unblock dependents
            self._patch_task(workflow_id, tid, {
                "status": "failed",
                "error_message": error_msg[:500],
            })
            self._log(workflow_id, f"Task '{tid}' failed: {error_msg[:200]}", level="ERROR")

    def _extract_result(self, scheduler, task_outputs: Dict[str, str]) -> Optional[str]:
        """Returns the leaf-node task output (final result of the DAG)."""
        if not task_outputs:
            return None
        all_ids = set(scheduler.tasks.keys())
        depended_on = set()
        for t in scheduler.tasks.values():
            depended_on.update(t.dependencies)
        leaf_ids = all_ids - depended_on
        for lid in leaf_ids:
            if lid in task_outputs:
                return task_outputs[lid]
        return list(task_outputs.values())[-1]

    def _set_status(self, wf_id: str, status: str, result: str = None, error: str = None):
        if wf_id in self._states:
            self._states[wf_id]["status"] = status
            if result is not None:
                self._states[wf_id]["result"] = result
            if error is not None:
                self._states[wf_id]["error"] = error

    def _upsert_task(self, wf_id: str, task_dict: dict):
        if wf_id not in self._states:
            return
        tasks = self._states[wf_id]["tasks"]
        for i, t in enumerate(tasks):
            if t["task_id"] == task_dict["task_id"]:
                tasks[i] = task_dict
                return
        tasks.append(task_dict)

    def _patch_task(self, wf_id: str, task_id: str, updates: dict):
        if wf_id not in self._states:
            return
        for task in self._states[wf_id]["tasks"]:
            if task["task_id"] == task_id:
                task.update(updates)
                return

    def _log(self, wf_id: str, message: str, level: str = "INFO"):
        if wf_id in self._states:
            self._states[wf_id]["logs"].append({"message": message, "level": level})