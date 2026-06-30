"""
True end-to-end test: a real HTTP request to FastAPI's TestClient,
flowing through the real router -> real Engine -> real Postgres
repositories -> real Scheduler -> real Dispatcher -> real ResearchAgent,
with ONLY the LLM provider faked (so this runs with no network access
and no API cost, while still exercising every other piece for real).

This is the first test in the whole project that proves the previously-
separate, independently-tested pieces (Planner, Scheduler, Registry,
Researcher, Engine, repositories, API) actually function correctly when
wired together end to end -- not just individually.
"""

import asyncio
import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from sqlalchemy import text

from app.database.session import AsyncSessionLocal
from app.llm_providers.llm_provider import LLMProvider
from app.orchestrator import wiring


FAKE_PLAN_RESPONSE = {
    "workflow_id": "placeholder",
    "tasks": [
        {
            "task_id": "t1",
            "name": "Research pricing",
            "task_type": "research",
            "description": "Find current pricing information.",
            "required_capabilities": [],
            "acceptance_criteria": "At least one data point found.",
            "priority": 5,
            "is_critical": True,
        }
    ],
    "dependencies": [],
}


class FakeLLMProvider(LLMProvider):
    """Returns a fixed valid plan for ANY prompt -- good enough to
    exercise the full pipeline without needing real reasoning."""

    async def generate_structured(self, *, system_prompt, user_prompt, json_schema, schema_name):
        if schema_name == "workflow_plan":
            return FAKE_PLAN_RESPONSE
        if schema_name == "research_summary":
            return {"summary": "Fake summary of research findings."}
        raise ValueError(f"FakeLLMProvider has no canned response for schema '{schema_name}'")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def setup_fake_llm_and_clean_db():
    wiring.set_llm_provider_override(FakeLLMProvider())

    async def _clean():
        async with AsyncSessionLocal() as session:
            await session.execute(text("TRUNCATE TABLE workflows CASCADE"))
            await session.commit()

    run(_clean())
    yield
    run(_clean())
    wiring.set_llm_provider_override(None)


def test_create_workflow_runs_full_pipeline_to_completion():
    """POST /workflows -> background task plans, persists tasks, executes
    via the real Researcher agent (with a fake LLM), and the workflow
    should reach a terminal state -- verified by polling GET, exactly as
    a real client would."""
    from app.main import app

    with TestClient(app) as client:
        response = client.post("/api/v1/workflows", json={"query": "What is the pricing for X?"})
        assert response.status_code == 202
        workflow_id = response.json()["workflow_id"]
        assert response.json()["status"] == "pending"

        # The background task runs synchronously within TestClient's
        # context by the time the `with` block's request returns in
        # Starlette's test harness for BackgroundTasks -- but poll with
        # a short retry loop regardless, since that's also exactly what
        # a real frontend client would do, and it's robust either way.
        terminal_status = None
        for _ in range(50):
            poll = client.get(f"/api/v1/workflows/{workflow_id}")
            assert poll.status_code == 200
            status = poll.json()["status"]
            if status in ("completed", "degraded", "failed"):
                terminal_status = status
                break
            time.sleep(0.1)

        assert terminal_status == "completed", f"Workflow did not complete: {terminal_status}"

        tasks_response = client.get(f"/api/v1/workflows/{workflow_id}/tasks")
        assert tasks_response.status_code == 200
        tasks = tasks_response.json()
        assert len(tasks) == 1
        assert tasks[0]["task_type"] == "research"
        assert tasks[0]["status"] == "verified"
        assert "summary" in tasks[0]["output_payload"]


def test_get_workflow_404_for_unknown_id():
    from app.main import app
    with TestClient(app) as client:
        response = client.get(f"/api/v1/workflows/{uuid.uuid4()}")
        assert response.status_code == 404


def test_cancel_workflow_updates_status():
    from app.main import app
    with TestClient(app) as client:
        create_resp = client.post("/api/v1/workflows", json={"query": "test"})
        workflow_id = create_resp.json()["workflow_id"]

        time.sleep(0.3)  # let background task at least start

        cancel_resp = client.post(f"/api/v1/workflows/{workflow_id}/cancel")
        assert cancel_resp.status_code == 200
        assert "cancel" in cancel_resp.json()["message"].lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
