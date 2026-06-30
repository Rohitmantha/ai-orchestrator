"""
The Dynamic Task Scheduler.

Responsibilities (per spec):
  - Read planner output
  - Resolve dependencies
  - Determine executable tasks
  - Support: sequential execution, parallel execution, retries, timeouts,
    priority scheduling
  - Return an execution plan

Design note on "sequential vs parallel": this is NOT two separate code
paths. A task with no unresolved dependencies is "ready"; all ready tasks
at a given moment form one batch and are intended to run in parallel.
Sequential execution falls out naturally when the DAG forces it (a chain
of finish_to_start dependencies produces batches of size 1, one after
another) -- there's no separate "sequential mode" to implement, which is
also why a bolted-on boolean flag for "run sequentially" would be the
wrong shape: it would let the caller override what the DAG's actual
ordering constraints require.
"""

from __future__ import annotations
from .models import (
    DEFAULT_RETRY_POLICIES,
    DEFAULT_TIMEOUT_POLICIES,
    DependencyEdge,
    ExecutionPlan,
    RetryPolicy,
    ScheduledTask,
    SkippedTask,
    TaskExecutionStatus,
    TaskNode,
    TimeoutPolicy,
)


class SchedulerGraphError(Exception):
    """Raised when the graph handed to the Scheduler is structurally
    invalid. The Scheduler assumes the Planner's own validation (cycle
    detection, referential integrity) already ran -- this is a defensive
    second check, not a replacement for it, in case the Scheduler is ever
    called with a graph that bypassed the Planner (e.g. constructed
    directly from a DB query after a service restart)."""


class DynamicTaskScheduler:
    def __init__(
        self,
        retry_policies: dict[str, RetryPolicy] | None = None,
        timeout_policies: dict[str, TimeoutPolicy] | None = None,
        max_parallelism: int | None = None,
    ):
        """
        retry_policies / timeout_policies: task_type -> policy. Falls back
        to DEFAULT_*_POLICIES for any task_type not explicitly given.

        max_parallelism: caps how many tasks can appear in a single batch
        regardless of how many are graph-ready. Without this, a wide DAG
        (e.g. 50 independent research tasks) would all fire in one batch
        and could exhaust LLM provider rate limits or agent concurrency
        limits -- this is the scheduler-level safety valve the
        architecture doc flagged under Scalability Considerations.
        """
        self._retry_policies = retry_policies or DEFAULT_RETRY_POLICIES
        self._timeout_policies = timeout_policies or DEFAULT_TIMEOUT_POLICIES
        self._max_parallelism = max_parallelism

    def build_plan(
        self,
        tasks: list[TaskNode],
        dependencies: list[DependencyEdge],
    ) -> ExecutionPlan:
        """The core entry point. Call this once per scheduling pass:
        initially with all tasks PENDING, then again after every batch
        completes with updated statuses. Each call is a fresh snapshot --
        the Scheduler holds no state between calls, which is what makes
        it safe to call from multiple places (e.g. after a service
        restart, you can rebuild the plan purely from current DB state).
        """
        self._validate_graph_integrity(tasks, dependencies)

        task_by_id = {t.task_id: t for t in tasks}

        # predecessors[x] = set of task_ids that must reach a terminal
        # SUCCEEDED state before x can run.
        predecessors: dict[str, set[str]] = {t.task_id: set() for t in tasks}
        # dependents[x] = set of task_ids that are waiting on x.
        dependents: dict[str, set[str]] = {t.task_id: set() for t in tasks}
        for edge in dependencies:
            predecessors[edge.task_id].add(edge.depends_on_task_id)
            dependents[edge.depends_on_task_id].add(edge.task_id)

        # --- Step 1: propagate skips from permanently-failed predecessors ---
        # ANY permanently-failed predecessor (critical or not) skips its
        # dependents -- a dependent task generally cannot run meaningfully
        # without its predecessor's output regardless of whether that
        # predecessor was "critical" to the *workflow's* success. What
        # `is_critical` actually controls is whether the failure escalates
        # to the *workflow* as 'failed' (critical) vs 'degraded'
        # (non-critical) -- that distinction is applied below, in Step 5,
        # not here. Conflating the two (as an earlier version of this
        # logic did) leaves a task with a non-critical failed predecessor
        # stuck forever in 'blocked', since it can never become ready
        # (its predecessor will never reach SUCCEEDED) and is never
        # explicitly skipped either -- a silent permanent stall.
        skipped: dict[str, str] = {}  # task_id -> reason

        def propagate_skip(failed_task_id: str, failed_task_name_for_msg: str) -> None:
            stack = list(dependents.get(failed_task_id, ()))
            while stack:
                dependent_id = stack.pop()
                if dependent_id in skipped:
                    continue
                node = task_by_id[dependent_id]
                if node.status.is_terminal:
                    continue  # already finished (e.g. SUCCEEDED before this failure was known) -- leave it
                skipped[dependent_id] = (
                    f"Skipped because dependency '{failed_task_name_for_msg}' failed permanently"
                )
                stack.extend(dependents.get(dependent_id, ()))

        for node in tasks:
            if node.status == TaskExecutionStatus.FAILED:
                propagate_skip(node.task_id, node.task_id)

        # --- Step 2: determine what's READY right now --------------------
        ready: list[TaskNode] = []
        blocked: list[str] = []

        for node in tasks:
            if node.task_id in skipped:
                continue
            if node.status.is_terminal:
                continue
            if node.status == TaskExecutionStatus.RUNNING:
                continue  # already in flight, not re-scheduled

            preds = predecessors[node.task_id]
            # Note: we don't need to special-case "predecessor is skipped"
            # here -- skip propagation above is transitive, so if any
            # predecessor were skipped, `node.task_id` would already be in
            # `skipped` and we'd have hit the `continue` above. A
            # predecessor can only be in one of: SUCCEEDED, or some
            # non-terminal/failed state that keeps this node out of
            # `preds_satisfied` (correctly leaving it blocked, not ready).
            preds_satisfied = all(
                task_by_id[p].status.is_successful_terminal for p in preds
            )

            if node.status == TaskExecutionStatus.RETRYING:
                # A retrying task is ready again once it's actually time
                # to retry -- the Scheduler itself doesn't track wall-clock
                # time (that's the executor's job, using the backoff value
                # the Scheduler already handed it); from the Scheduler's
                # perspective, RETRYING means "the executor will re-submit
                # this, treat it as ready to be included in the next batch."
                ready.append(node)
            elif preds_satisfied and node.status in (TaskExecutionStatus.PENDING, TaskExecutionStatus.READY):
                ready.append(node)
            else:
                blocked.append(node.task_id)

        # --- Step 3: order the ready set by priority, apply parallelism cap ---
        # Priority breaks ties WITHIN the ready set only -- it can never
        # promote a task ahead of one still blocked by a real dependency.
        # This is the deliberate constraint from the design: priority is a
        # scheduling preference, not an override of correctness.
        ready.sort(key=lambda n: (-n.priority, n.task_id))

        if self._max_parallelism is not None and len(ready) > self._max_parallelism:
            deferred = ready[self._max_parallelism:]
            ready = ready[: self._max_parallelism]
            for node in deferred:
                blocked.append(node.task_id)

        # --- Step 4: build ScheduledTask entries with retry/timeout info ---
        current_batch = [self._to_scheduled_task(node) for node in ready]

        # --- Step 5: assess overall workflow state -----------------------
        all_terminal = all(
            task_by_id[t.task_id].status.is_terminal or t.task_id in skipped
            for t in tasks
        )
        any_critical_failed = any(
            t.status == TaskExecutionStatus.FAILED and t.is_critical for t in tasks
        )
        any_noncritical_failed = any(
            t.status == TaskExecutionStatus.FAILED and not t.is_critical for t in tasks
        )

        workflow_is_complete = all_terminal and not current_batch
        terminal_state = None
        if workflow_is_complete:
            if any_critical_failed:
                terminal_state = "failed"
            elif any_noncritical_failed or skipped:
                terminal_state = "degraded"
            else:
                terminal_state = "completed"

        # Can the workflow still progress? False only if nothing is
        # running, nothing is ready, and we're not complete -- that
        # combination means the workflow is stuck (should not happen if
        # the Planner's graph validation ran, but worth surfacing rather
        # than silently returning an empty plan forever).
        anything_in_flight = any(n.status == TaskExecutionStatus.RUNNING for n in tasks)
        workflow_can_progress = bool(current_batch) or anything_in_flight or workflow_is_complete

        return ExecutionPlan(
            current_batch=current_batch,
            skipped=[SkippedTask(task_id=tid, reason=reason) for tid, reason in skipped.items()],
            blocked_task_ids=blocked,
            workflow_can_progress=workflow_can_progress,
            workflow_is_complete=workflow_is_complete,
            workflow_terminal_state=terminal_state,
        )

    def _to_scheduled_task(self, node: TaskNode) -> ScheduledTask:
        retry_policy = self._retry_policies.get(node.task_type, RetryPolicy())
        timeout_policy = self._timeout_policies.get(node.task_type, TimeoutPolicy())
        is_retry = node.status == TaskExecutionStatus.RETRYING
        attempt_number = node.retry_count + 1
        return ScheduledTask(
            task_id=node.task_id,
            task_type=node.task_type,
            priority=node.priority,
            attempt_number=attempt_number,
            timeout_seconds=timeout_policy.execution_timeout_seconds,
            is_retry=is_retry,
        )

    def should_retry(self, node: TaskNode) -> bool:
        """Called by the Orchestrator when a task execution fails, BEFORE
        marking it FAILED -- decides whether this should become RETRYING
        instead. Separate method (not folded into build_plan) because this
        decision happens at failure time, not at plan-building time."""
        policy = self._retry_policies.get(node.task_type, RetryPolicy())
        return node.retry_count < policy.max_retries

    def backoff_seconds(self, node: TaskNode) -> float:
        policy = self._retry_policies.get(node.task_type, RetryPolicy())
        return policy.backoff_for_attempt(node.retry_count + 1)

    @staticmethod
    def _validate_graph_integrity(tasks: list[TaskNode], dependencies: list[DependencyEdge]) -> None:
        task_ids = {t.task_id for t in tasks}
        if len(task_ids) != len(tasks):
            raise SchedulerGraphError("Duplicate task_id values in tasks list")

        for edge in dependencies:
            if edge.task_id not in task_ids:
                raise SchedulerGraphError(f"Dependency edge references unknown task_id '{edge.task_id}'")
            if edge.depends_on_task_id not in task_ids:
                raise SchedulerGraphError(
                    f"Dependency edge references unknown depends_on_task_id '{edge.depends_on_task_id}'"
                )

        # Cycle check (DFS) -- defense in depth, mirrors the Planner's own
        # validation and the DB trigger. Cheap relative to the cost of a
        # scheduler silently deadlocking on a cyclic graph it trusted.
        adjacency: dict[str, list[str]] = {tid: [] for tid in task_ids}
        for edge in dependencies:
            adjacency[edge.depends_on_task_id].append(edge.task_id)

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in task_ids}

        def visit(node_id: str) -> bool:
            color[node_id] = GRAY
            for neighbor in adjacency[node_id]:
                if color[neighbor] == GRAY:
                    return True
                if color[neighbor] == WHITE and visit(neighbor):
                    return True
            color[node_id] = BLACK
            return False

        for tid in task_ids:
            if color[tid] == WHITE and visit(tid):
                raise SchedulerGraphError("Cycle detected in task dependency graph")
