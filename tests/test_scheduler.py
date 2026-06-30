"""
Tests for the Dynamic Task Scheduler.

Each test isolates one responsibility from the spec: dependency
resolution, parallel batching, priority ordering, retry/timeout policy
application, and critical-failure skip propagation.
"""

import sys
from pathlib import Path

import pytest

# tests/test_scheduler.py -> tests/ -> project root -> backend/app
# The scheduler package lives at backend/app/scheduler/, so that directory
# needs to be on sys.path for `from scheduler.x import y` to resolve.
sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "app"))

from scheduler.dynamic_scheduler import DynamicTaskScheduler, SchedulerGraphError
from scheduler.models import (
    DependencyEdge,
    RetryPolicy,
    TaskExecutionStatus,
    TaskNode,
)


def node(task_id, task_type="research", status=TaskExecutionStatus.PENDING,
         priority=0, is_critical=True, retry_count=0):
    return TaskNode(
        task_id=task_id, task_type=task_type, status=status,
        priority=priority, is_critical=is_critical, retry_count=retry_count,
    )


# ---------------------------------------------------------------------------
# Dependency resolution / batching
# ---------------------------------------------------------------------------

def test_independent_tasks_form_one_parallel_batch():
    tasks = [node("t1"), node("t2"), node("t3")]
    plan = DynamicTaskScheduler().build_plan(tasks, [])
    batch_ids = {t.task_id for t in plan.current_batch}
    assert batch_ids == {"t1", "t2", "t3"}


def test_chain_dependency_forces_sequential_batches():
    """t1 -> t2 -> t3 (finish_to_start chain): only t1 should be ready
    initially -- t2 and t3 must wait."""
    tasks = [node("t1"), node("t2"), node("t3")]
    deps = [
        DependencyEdge(task_id="t2", depends_on_task_id="t1"),
        DependencyEdge(task_id="t3", depends_on_task_id="t2"),
    ]
    plan = DynamicTaskScheduler().build_plan(tasks, deps)
    assert [t.task_id for t in plan.current_batch] == ["t1"]
    assert set(plan.blocked_task_ids) == {"t2", "t3"}


def test_diamond_dependency_second_batch_after_first_completes():
    """t1 -> {t2, t3} -> t4. After t1 succeeds, t2 and t3 should both
    become ready together (parallel), t4 still blocked."""
    tasks = [
        node("t1", status=TaskExecutionStatus.VERIFIED),
        node("t2"), node("t3"), node("t4"),
    ]
    deps = [
        DependencyEdge(task_id="t2", depends_on_task_id="t1"),
        DependencyEdge(task_id="t3", depends_on_task_id="t1"),
        DependencyEdge(task_id="t4", depends_on_task_id="t2"),
        DependencyEdge(task_id="t4", depends_on_task_id="t3"),
    ]
    plan = DynamicTaskScheduler().build_plan(tasks, deps)
    batch_ids = {t.task_id for t in plan.current_batch}
    assert batch_ids == {"t2", "t3"}
    assert plan.blocked_task_ids == ["t4"]


def test_running_tasks_are_not_rescheduled():
    tasks = [node("t1", status=TaskExecutionStatus.RUNNING)]
    plan = DynamicTaskScheduler().build_plan(tasks, [])
    assert plan.current_batch == []


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------

def test_priority_orders_within_ready_batch():
    tasks = [node("low", priority=1), node("high", priority=9), node("mid", priority=5)]
    plan = DynamicTaskScheduler().build_plan(tasks, [])
    assert [t.task_id for t in plan.current_batch] == ["high", "mid", "low"]


def test_priority_cannot_override_dependency_order():
    """A high-priority task that's blocked by a dependency must NOT jump
    ahead of an unrelated, lower-priority but actually-ready task. This
    locks in the design constraint: priority breaks ties among ready
    tasks, it never promotes a blocked task."""
    tasks = [
        node("t1", priority=0),                       # ready, low priority
        node("blocked_high_priority", priority=10),    # blocked, high priority
        node("dependency_for_blocked", priority=0),
    ]
    deps = [
        DependencyEdge(task_id="blocked_high_priority", depends_on_task_id="dependency_for_blocked"),
    ]
    plan = DynamicTaskScheduler().build_plan(tasks, deps)
    batch_ids = {t.task_id for t in plan.current_batch}
    assert "blocked_high_priority" not in batch_ids
    assert batch_ids == {"t1", "dependency_for_blocked"}


def test_max_parallelism_caps_batch_size_using_priority():
    tasks = [node(f"t{i}", priority=i) for i in range(5)]
    plan = DynamicTaskScheduler(max_parallelism=2).build_plan(tasks, [])
    assert len(plan.current_batch) == 2
    # highest priority ones (t4, t3) should be the ones chosen
    assert {t.task_id for t in plan.current_batch} == {"t4", "t3"}
    assert "t2" in plan.blocked_task_ids


# ---------------------------------------------------------------------------
# Retry / timeout policy application
# ---------------------------------------------------------------------------

def test_scheduled_task_carries_timeout_from_policy():
    tasks = [node("t1", task_type="coding")]
    plan = DynamicTaskScheduler().build_plan(tasks, [])
    assert plan.current_batch[0].timeout_seconds == 180.0  # coding default


def test_retrying_task_is_included_in_next_batch_with_incremented_attempt():
    tasks = [node("t1", status=TaskExecutionStatus.RETRYING, retry_count=1)]
    plan = DynamicTaskScheduler().build_plan(tasks, [])
    assert len(plan.current_batch) == 1
    scheduled = plan.current_batch[0]
    assert scheduled.is_retry is True
    assert scheduled.attempt_number == 2  # retry_count(1) + 1


def test_should_retry_respects_max_retries():
    scheduler = DynamicTaskScheduler(retry_policies={"research": RetryPolicy(max_retries=2)})
    under_limit = node("t1", task_type="research", retry_count=1)
    at_limit = node("t2", task_type="research", retry_count=2)
    assert scheduler.should_retry(under_limit) is True
    assert scheduler.should_retry(at_limit) is False


def test_backoff_seconds_increases_with_attempts():
    scheduler = DynamicTaskScheduler(
        retry_policies={"research": RetryPolicy(base_backoff_seconds=2.0, backoff_multiplier=2.0, max_backoff_seconds=100)}
    )
    t = node("t1", task_type="research", retry_count=0)
    first = scheduler.backoff_seconds(t)
    t2 = node("t1", task_type="research", retry_count=1)
    second = scheduler.backoff_seconds(t2)
    assert first == 2.0
    assert second == 4.0
    assert second > first


def test_backoff_is_capped_at_max():
    scheduler = DynamicTaskScheduler(
        retry_policies={"research": RetryPolicy(base_backoff_seconds=10.0, backoff_multiplier=10.0, max_backoff_seconds=15.0)}
    )
    t = node("t1", task_type="research", retry_count=5)  # would be huge uncapped
    assert scheduler.backoff_seconds(t) == 15.0


# ---------------------------------------------------------------------------
# Skip propagation on critical failure
# ---------------------------------------------------------------------------

def test_critical_failure_skips_downstream_tasks():
    tasks = [
        node("t1", status=TaskExecutionStatus.FAILED, is_critical=True, retry_count=99),
        node("t2"),  # depends on t1
        node("t3"),  # depends on t2 -- transitively skipped
    ]
    deps = [
        DependencyEdge(task_id="t2", depends_on_task_id="t1"),
        DependencyEdge(task_id="t3", depends_on_task_id="t2"),
    ]
    plan = DynamicTaskScheduler().build_plan(tasks, deps)
    skipped_ids = {s.task_id for s in plan.skipped}
    assert skipped_ids == {"t2", "t3"}
    assert plan.current_batch == []


def test_noncritical_failure_does_not_skip_downstream():
    """A non-critical task failing should NOT cascade -- the workflow can
    still produce a degraded-but-useful result. Downstream tasks that
    don't depend on the failed one should proceed normally."""
    tasks = [
        node("t1", status=TaskExecutionStatus.FAILED, is_critical=False, retry_count=99),
        node("t2"),  # independent, unrelated to t1
    ]
    plan = DynamicTaskScheduler().build_plan(tasks, [])
    assert plan.skipped == []
    assert {t.task_id for t in plan.current_batch} == {"t2"}


def test_real_dependent_of_noncritical_failure_is_skipped_not_stuck_forever():
    """Regression test for a bug found during manual review: a task whose
    ACTUAL predecessor (not just an unrelated sibling) is non-critical and
    permanently failed must be SKIPPED, not left in 'blocked' forever.
    Before the fix, this task could never become ready (its predecessor
    will never reach SUCCEEDED) and was never explicitly skipped either
    (skip propagation only fired for critical failures) -- a silent
    permanent stall where workflow_is_complete would never become True."""
    tasks = [
        node("t1", status=TaskExecutionStatus.FAILED, is_critical=False, retry_count=99),
        node("t2"),  # genuinely depends on t1's output
    ]
    deps = [DependencyEdge(task_id="t2", depends_on_task_id="t1")]
    plan = DynamicTaskScheduler().build_plan(tasks, deps)

    assert plan.current_batch == []
    assert plan.blocked_task_ids == []  # must NOT be stuck in limbo
    assert {s.task_id for s in plan.skipped} == {"t2"}
    assert plan.workflow_is_complete is True
    assert plan.workflow_terminal_state == "degraded"  # non-critical chain -> degraded, not failed
    assert plan.workflow_can_progress is True


def test_workflow_completion_state_all_succeeded():
    tasks = [node("t1", status=TaskExecutionStatus.VERIFIED), node("t2", status=TaskExecutionStatus.VERIFIED)]
    plan = DynamicTaskScheduler().build_plan(tasks, [])
    assert plan.workflow_is_complete is True
    assert plan.workflow_terminal_state == "completed"


def test_workflow_completion_state_degraded_on_noncritical_failure():
    tasks = [
        node("t1", status=TaskExecutionStatus.VERIFIED),
        node("t2", status=TaskExecutionStatus.FAILED, is_critical=False, retry_count=99),
    ]
    plan = DynamicTaskScheduler().build_plan(tasks, [])
    assert plan.workflow_is_complete is True
    assert plan.workflow_terminal_state == "degraded"


def test_workflow_completion_state_failed_on_critical_failure():
    tasks = [
        node("t1", status=TaskExecutionStatus.VERIFIED),
        node("t2", status=TaskExecutionStatus.FAILED, is_critical=True, retry_count=99),
    ]
    plan = DynamicTaskScheduler().build_plan(tasks, [])
    assert plan.workflow_is_complete is True
    assert plan.workflow_terminal_state == "failed"


def test_workflow_not_complete_while_tasks_pending():
    tasks = [node("t1", status=TaskExecutionStatus.VERIFIED), node("t2", status=TaskExecutionStatus.PENDING)]
    plan = DynamicTaskScheduler().build_plan(tasks, [])
    assert plan.workflow_is_complete is False
    assert plan.workflow_terminal_state is None


# ---------------------------------------------------------------------------
# Graph integrity defense-in-depth
# ---------------------------------------------------------------------------

def test_rejects_cyclic_graph():
    tasks = [node("t1"), node("t2")]
    deps = [
        DependencyEdge(task_id="t1", depends_on_task_id="t2"),
        DependencyEdge(task_id="t2", depends_on_task_id="t1"),
    ]
    with pytest.raises(SchedulerGraphError, match="Cycle detected"):
        DynamicTaskScheduler().build_plan(tasks, deps)


def test_rejects_dangling_dependency_reference():
    tasks = [node("t1")]
    deps = [DependencyEdge(task_id="t1", depends_on_task_id="ghost")]
    with pytest.raises(SchedulerGraphError, match="unknown depends_on_task_id"):
        DynamicTaskScheduler().build_plan(tasks, deps)


def test_rejects_duplicate_task_ids():
    tasks = [node("t1"), node("t1")]
    with pytest.raises(SchedulerGraphError, match="Duplicate"):
        DynamicTaskScheduler().build_plan(tasks, [])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
