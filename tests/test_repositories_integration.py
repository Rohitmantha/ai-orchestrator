"""
Integration tests for PostgresTaskRepository / PostgresWorkflowRepository.

Unlike every other test file in this project so far, this one talks to a
REAL Postgres database -- not a fake/mock. This is intentional and new:
the whole point of this module is proving the mapping between SQLAlchemy
rows and TaskNode/DependencyEdge is actually correct, which a mock can
never verify (a mock just returns whatever you tell it to).

Requires a running Postgres reachable via DATABASE_URL (defaults to the
same connection string used by docker-compose.yml). Each test creates its
own workflow/tasks and cleans up via TRUNCATE in a fixture, so tests
don't interfere with each other or leave junk data behind.
"""

import asyncio
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import PostgresTaskRepository, PostgresWorkflowRepository
from app.database.session import AsyncSessionLocal
from app.scheduler.models import DependencyEdge, TaskExecutionStatus, TaskNode


# A single shared event loop for the whole test module, rather than a
# fresh asyncio.run() per test. This matters specifically because
# AsyncSessionLocal's underlying engine/connection-pool is created ONCE
# at import time (module-level in session.py) and gets bound to whichever
# event loop first uses it -- asyncpg connections are not safe to reuse
# across different event loops. asyncio.run() per test creates a NEW
# loop every time, so the second test's loop would try to reuse a
# connection bound to the first test's (now-closed) loop, raising
# "got Future attached to a different loop". A session-scoped shared
# loop is the correct fix; tearing down and recreating the engine per
# test would also work but adds overhead for no benefit here.
@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def run(coro, loop):
    return loop.run_until_complete(coro)


async def _truncate_all(session: AsyncSession):
    # CASCADE handles task_dependencies/tasks referencing workflows.
    await session.execute(text("TRUNCATE TABLE workflows CASCADE"))
    await session.commit()


@pytest.fixture(autouse=True)
def clean_db(event_loop):
    """Runs before AND after every test -- guarantees a clean slate even
    if a previous test crashed mid-way without cleaning up."""
    async def _clean():
        async with AsyncSessionLocal() as session:
            await _truncate_all(session)

    run(_clean(), event_loop)
    yield
    run(_clean(), event_loop)


async def _seed_workflow(session: AsyncSession) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    repo = PostgresWorkflowRepository(session)

    # create_workflow needs a real users row to satisfy the FK in a
    # strict sense -- but workflows.user_id has no NOT VALID/deferred FK
    # bypass in this schema, so we insert a minimal user row directly.
    await session.execute(text(
        "INSERT INTO users (id, tenant_id, email, hashed_password) "
        "VALUES (:id, :tenant_id, :email, 'x')"
    ), {"id": user_id, "tenant_id": tenant_id, "email": f"{user_id}@test.local"})
    await session.commit()

    workflow = await repo.create_workflow(
        tenant_id=tenant_id, user_id=user_id, original_query="integration test query",
    )
    return workflow.id


async def _insert_task(
    session: AsyncSession, workflow_id: uuid.UUID, *, name="t", task_type="research",
    status="pending", priority=0, is_critical=True, tenant_id=None,
) -> uuid.UUID:
    task_id = uuid.uuid4()
    tenant_id = tenant_id or uuid.uuid4()
    await session.execute(text(
        "INSERT INTO tasks (id, tenant_id, workflow_id, name, task_type, status, priority, is_critical, created_at, updated_at) "
        "VALUES (:id, :tenant_id, :workflow_id, :name, :task_type, :status, :priority, :is_critical, now(), now())"
    ), {
        "id": task_id, "tenant_id": tenant_id, "workflow_id": workflow_id,
        "name": name, "task_type": task_type, "status": status,
        "priority": priority, "is_critical": is_critical,
    })
    await session.commit()
    return task_id


async def _insert_dependency(session: AsyncSession, tenant_id: uuid.UUID, task_id: uuid.UUID, depends_on: uuid.UUID):
    await session.execute(text(
        "INSERT INTO task_dependencies (id, tenant_id, task_id, depends_on_task_id, created_at, updated_at) "
        "VALUES (:id, :tenant_id, :task_id, :depends_on, now(), now())"
    ), {"id": uuid.uuid4(), "tenant_id": tenant_id, "task_id": task_id, "depends_on": depends_on})
    await session.commit()


# ---------------------------------------------------------------------------
# get_tasks: real round-trip from Postgres rows to TaskNode
# ---------------------------------------------------------------------------

def test_get_tasks_returns_empty_list_for_unknown_workflow(event_loop):
    async def scenario():
        async with AsyncSessionLocal() as session:
            repo = PostgresTaskRepository(session)
            tasks = await repo.get_tasks(str(uuid.uuid4()))
            assert tasks == []
    run(scenario(), event_loop)


def test_get_tasks_maps_real_row_fields_correctly(event_loop):
    """The core mapping test: insert a row with specific values, read it
    back through the repository, and confirm EVERY field that matters to
    the Scheduler survived the round trip correctly -- not just that
    something came back."""
    async def scenario():
        async with AsyncSessionLocal() as session:
            wf_id = await _seed_workflow(session)
            await _insert_task(
                session, wf_id, name="Research pricing", task_type="research",
                status="ready", priority=7, is_critical=False,
            )

            repo = PostgresTaskRepository(session)
            tasks = await repo.get_tasks(str(wf_id))

            assert len(tasks) == 1
            t = tasks[0]
            assert isinstance(t, TaskNode)
            assert t.task_type == "research"
            assert t.status == TaskExecutionStatus.READY
            assert t.priority == 7
            assert t.is_critical is False  # the migration-002 field, specifically verified
            assert t.retry_count == 0

    run(scenario(), event_loop)


def test_get_tasks_only_returns_tasks_for_the_requested_workflow(event_loop):
    """Guards against a query bug that would leak another workflow's
    tasks -- a real risk if the WHERE clause were ever loosened."""
    async def scenario():
        async with AsyncSessionLocal() as session:
            wf_a = await _seed_workflow(session)
            wf_b = await _seed_workflow(session)
            await _insert_task(session, wf_a, name="belongs to A")
            await _insert_task(session, wf_b, name="belongs to B")

            repo = PostgresTaskRepository(session)
            tasks_a = await repo.get_tasks(str(wf_a))
            assert len(tasks_a) == 1

    run(scenario(), event_loop)


def test_get_tasks_excludes_soft_deleted_rows(event_loop):
    async def scenario():
        async with AsyncSessionLocal() as session:
            wf_id = await _seed_workflow(session)
            task_id = await _insert_task(session, wf_id)
            await session.execute(text("UPDATE tasks SET deleted_at = now() WHERE id = :id"), {"id": task_id})
            await session.commit()

            repo = PostgresTaskRepository(session)
            tasks = await repo.get_tasks(str(wf_id))
            assert tasks == []

    run(scenario(), event_loop)


# ---------------------------------------------------------------------------
# get_dependencies: real edges, scoped correctly to one workflow
# ---------------------------------------------------------------------------

def test_get_dependencies_round_trips_edge_correctly(event_loop):
    async def scenario():
        async with AsyncSessionLocal() as session:
            wf_id = await _seed_workflow(session)
            t1 = await _insert_task(session, wf_id, name="t1")
            t2 = await _insert_task(session, wf_id, name="t2")

            # fetch tenant_id used for t2's row to satisfy FK/tenant scoping
            result = await session.execute(text("SELECT tenant_id FROM tasks WHERE id = :id"), {"id": t2})
            tenant_id = result.scalar_one()
            await _insert_dependency(session, tenant_id, t2, t1)

            repo = PostgresTaskRepository(session)
            deps = await repo.get_dependencies(str(wf_id))

            assert len(deps) == 1
            assert isinstance(deps[0], DependencyEdge)
            assert deps[0].task_id == str(t2)
            assert deps[0].depends_on_task_id == str(t1)

    run(scenario(), event_loop)


def test_get_dependencies_scoped_to_requested_workflow_only(event_loop):
    async def scenario():
        async with AsyncSessionLocal() as session:
            wf_a = await _seed_workflow(session)
            wf_b = await _seed_workflow(session)

            a1 = await _insert_task(session, wf_a, name="a1")
            a2 = await _insert_task(session, wf_a, name="a2")
            b1 = await _insert_task(session, wf_b, name="b1")
            b2 = await _insert_task(session, wf_b, name="b2")

            result = await session.execute(text("SELECT tenant_id FROM tasks WHERE id = :id"), {"id": a2})
            tenant_a = result.scalar_one()
            result = await session.execute(text("SELECT tenant_id FROM tasks WHERE id = :id"), {"id": b2})
            tenant_b = result.scalar_one()

            await _insert_dependency(session, tenant_a, a2, a1)
            await _insert_dependency(session, tenant_b, b2, b1)

            repo = PostgresTaskRepository(session)
            deps_a = await repo.get_dependencies(str(wf_a))

            assert len(deps_a) == 1
            assert deps_a[0].task_id == str(a2)

    run(scenario(), event_loop)


# ---------------------------------------------------------------------------
# update_task_state: writes actually persist and are read back correctly
# ---------------------------------------------------------------------------

def test_update_task_state_persists_status_and_output(event_loop):
    async def scenario():
        async with AsyncSessionLocal() as session:
            wf_id = await _seed_workflow(session)
            task_id = await _insert_task(session, wf_id, status="running")

            repo = PostgresTaskRepository(session)
            await repo.update_task_state(
                str(task_id), TaskExecutionStatus.VERIFIED,
                output={"result": "found 3 sources"},
                metrics={"attempts": 1},
            )

        # Open a FRESH session to prove the write was actually committed
        # to the database, not just held in this session's identity map.
        async with AsyncSessionLocal() as fresh_session:
            repo2 = PostgresTaskRepository(fresh_session)
            tasks = await repo2.get_tasks(str(wf_id))
            assert len(tasks) == 1
            assert tasks[0].status == TaskExecutionStatus.VERIFIED
            assert tasks[0].output_payload == {"result": "found 3 sources"}
            assert tasks[0].retry_count == 0  # attempts=1 -> retry_count=0

    run(scenario(), event_loop)


def test_update_task_state_records_retry_count_from_attempts(event_loop):
    async def scenario():
        async with AsyncSessionLocal() as session:
            wf_id = await _seed_workflow(session)
            task_id = await _insert_task(session, wf_id)

            repo = PostgresTaskRepository(session)
            await repo.update_task_state(
                str(task_id), TaskExecutionStatus.FAILED,
                output={"error": "timeout"},
                metrics={"attempts": 3},
            )

        async with AsyncSessionLocal() as fresh_session:
            repo2 = PostgresTaskRepository(fresh_session)
            tasks = await repo2.get_tasks(str(wf_id))
            assert tasks[0].retry_count == 2  # attempts=3 -> retry_count=2
            assert tasks[0].status == TaskExecutionStatus.FAILED

    run(scenario(), event_loop)


def test_update_task_state_sets_error_message_on_failure(event_loop):
    async def scenario():
        async with AsyncSessionLocal() as session:
            wf_id = await _seed_workflow(session)
            task_id = await _insert_task(session, wf_id)

            repo = PostgresTaskRepository(session)
            await repo.update_task_state(
                str(task_id), TaskExecutionStatus.FAILED, output={"error": "connection refused"},
            )

            result = await session.execute(text("SELECT error_message FROM tasks WHERE id = :id"), {"id": task_id})
            assert result.scalar_one() == "connection refused"

    run(scenario(), event_loop)


# ---------------------------------------------------------------------------
# Workflow repository
# ---------------------------------------------------------------------------

def test_create_and_update_workflow_state(event_loop):
    async def scenario():
        async with AsyncSessionLocal() as session:
            wf_id = await _seed_workflow(session)

            repo = PostgresWorkflowRepository(session)
            await repo.update_workflow_state(str(wf_id), "completed", metrics={"total_duration_seconds": 4.2})

        async with AsyncSessionLocal() as fresh_session:
            repo2 = PostgresWorkflowRepository(fresh_session)
            wf = await repo2.get_workflow(str(wf_id))
            assert wf.status == "completed"
            assert wf.completed_at is not None

    run(scenario(), event_loop)


def test_update_workflow_state_records_error_summary_on_failure(event_loop):
    async def scenario():
        async with AsyncSessionLocal() as session:
            wf_id = await _seed_workflow(session)
            repo = PostgresWorkflowRepository(session)
            await repo.update_workflow_state(str(wf_id), "failed", metrics={"error": "Deadlock detected"})

            wf = await repo.get_workflow(str(wf_id))
            assert wf.error_summary == "Deadlock detected"

    run(scenario(), event_loop)


def test_get_workflow_returns_none_for_unknown_id(event_loop):
    async def scenario():
        async with AsyncSessionLocal() as session:
            repo = PostgresWorkflowRepository(session)
            wf = await repo.get_workflow(str(uuid.uuid4()))
            assert wf is None

    run(scenario(), event_loop)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
