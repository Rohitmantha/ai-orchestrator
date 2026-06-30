"""
Validation for LLM-produced plans.

An LLM can return syntactically valid JSON that is still a semantically
broken plan: a dependency pointing at a task_id that doesn't exist, or a
genuine cycle (A depends on B depends on A). Pydantic in schemas.py catches
shape errors; this module catches graph-correctness errors.

This deliberately duplicates the cycle-prevention invariant that also lives
as a Postgres trigger on `task_dependencies` (see schema.sql). That is not
redundant by accident -- defense in depth, same principle the trigger was
built on: a malformed DAG should never be allowed to reach the next stage,
and we'd rather catch it here (cheap, no DB round-trip, clearer error
message tied to the LLM's local task_ids) than rely solely on the DB
rejecting it later with a UUID-based error that's harder to debug.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import WorkflowPlan


class PlanValidationError(Exception):
    """Raised when a plan fails structural validation. Carries a list of
    every problem found, not just the first, so a caller (or a retry
    prompt back to the LLM) gets a complete picture in one pass."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)


def validate_plan(plan: WorkflowPlan) -> ValidationResult:
    errors: list[str] = []

    task_ids = [t.task_id for t in plan.tasks]
    task_id_set = set(task_ids)

    # 1. Duplicate task_ids -- would make dependency edges ambiguous.
    duplicates = {tid for tid in task_ids if task_ids.count(tid) > 1}
    if duplicates:
        errors.append(f"Duplicate task_id(s) found: {sorted(duplicates)}")

    # 2. Referential integrity: every edge must point at real, declared tasks.
    for dep in plan.dependencies:
        if dep.task_id not in task_id_set:
            errors.append(
                f"Dependency references unknown task_id '{dep.task_id}' "
                f"(not declared in tasks list)"
            )
        if dep.depends_on_task_id not in task_id_set:
            errors.append(
                f"Dependency references unknown depends_on_task_id "
                f"'{dep.depends_on_task_id}' (not declared in tasks list)"
            )

    # If referential integrity already failed, cycle detection on a graph
    # with dangling edges would produce confusing secondary errors -- stop here.
    if errors:
        return ValidationResult(is_valid=False, errors=errors)

    # 3. Cycle detection via DFS. Mirrors the recursive-CTE trigger logic
    # in Postgres, just expressed as a graph walk instead of a query.
    adjacency: dict[str, list[str]] = {tid: [] for tid in task_id_set}
    for dep in plan.dependencies:
        # edge direction: depends_on_task_id -> task_id
        # (the dependency must finish before the dependent task can start)
        adjacency[dep.depends_on_task_id].append(dep.task_id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {tid: WHITE for tid in task_id_set}
    cycle_path: list[str] = []

    def visit(node: str, path: list[str]) -> bool:
        color[node] = GRAY
        path.append(node)
        for neighbor in adjacency[node]:
            if color[neighbor] == GRAY:
                cycle_path.extend(path[path.index(neighbor):] + [neighbor])
                return True
            if color[neighbor] == WHITE and visit(neighbor, path):
                return True
        path.pop()
        color[node] = BLACK
        return False

    for tid in task_id_set:
        if color[tid] == WHITE:
            if visit(tid, []):
                errors.append(
                    f"Cycle detected in task dependencies: "
                    f"{' -> '.join(cycle_path)}"
                )
                break

    # 4. Orphan critical tasks: a critical task with an impossible
    # dependency on itself transitively already caught above; here we just
    # sanity-check there's at least one task with no incoming dependency
    # ("ready" candidates) -- if every task depends on something, nothing
    # can ever start, which would otherwise pass cycle detection if e.g.
    # the graph is empty of edges. This guards a degenerate case.
    if plan.tasks and plan.dependencies:
        dependent_ids = {dep.task_id for dep in plan.dependencies}
        if dependent_ids == task_id_set:
            # every single task has at least one dependency -- only a
            # problem if that also means none of them are satisfiable
            # at depth 0. Re-check directly: is there ANY task with zero
            # predecessors?
            depends_on_map = {dep.task_id for dep in plan.dependencies}
            no_predecessor = task_id_set - depends_on_map
            if not no_predecessor:
                errors.append(
                    "No task has zero dependencies -- the DAG has no valid "
                    "starting point (every task waits on another)."
                )

    return ValidationResult(is_valid=len(errors) == 0, errors=errors)


def validate_plan_or_raise(plan: WorkflowPlan) -> None:
    result = validate_plan(plan)
    if not result.is_valid:
        raise PlanValidationError(result.errors)
