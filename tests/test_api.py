"""
API-layer tests for the workflows router.

Rewritten from the original version, which predated the router's real
wiring (Prompt 12's actual implementation) and tested against hardcoded
mock responses using a fake ID like "wf-123". That ID was never a valid
UUID -- harmless against the old mocks, which never validated it, but
the REAL router (see workflows.py) does a genuine `uuid.UUID(workflow_id)`
lookup against Postgres, and correctly rejects non-UUID input. These
tests reflect that real behavior instead of the obsolete mocked one.

Distinct from test_e2e_wiring.py: this file focuses on HTTP-layer
concerns specifically (status codes, request validation, 404 handling,
response shape) using fast, targeted setups -- not the full multi-agent
pipeline. test_e2e_wiring.py is the one proving the whole pipeline
reaches a terminal state; this file is the one proving the API contract
itself (REST conventions, error handling) is correct.
"""

import asyncio
import sys
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
            "name": "Research something",
            "task_type": "research",
            "description": "Find information.",
            "required_capabilities": [],
            "acceptance_criteria": "At least one data point found.",
            "priority": 5,
            "is_critical": True,
        }
    ],
    "dependencies": [],
}


class FakeLLMProvider(LLMProvider):
    async def generate_structured(self, *, system_prompt, user_prompt, json_schema, schema_name):
        if schema_name == "workflow_plan":
            return FAKE_PLAN_RESPONSE
        if schema_name == "research_summary":
            return {"summary": "Fake summary."}
        raise ValueError(f"No canned response for schema '{schema_name}'")


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


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


# ---------------------------------------------------------------------------
# POST /workflows -- creation contract
# ---------------------------------------------------------------------------

def test_create_workflow_returns_202_with_real_uuid(client):
    response = client.post("/api/v1/workflows", json={"query": "Analyze Q3 tech trends"})
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "pending"
    assert data["query"] == "Analyze Q3 tech trends"

    # The returned workflow_id must be a real UUID -- the whole point of
    # the rewrite is that this is no longer a fake placeholder string.
    parsed = uuid.UUID(data["workflow_id"])  # raises if not a real UUID
    assert str(parsed) == data["workflow_id"]


def test_create_workflow_rejects_missing_query(client):
    response = client.post("/api/v1/workflows", json={})
    assert response.status_code == 422  # FastAPI/Pydantic validation error


# ---------------------------------------------------------------------------
# GET /workflows/{id} -- real lookups, real 404s
# ---------------------------------------------------------------------------

def test_get_workflow_returns_real_data_after_creation(client):
    create_resp = client.post("/api/v1/workflows", json={"query": "test query"})
    workflow_id = create_resp.json()["workflow_id"]

    get_resp = client.get(f"/api/v1/workflows/{workflow_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["workflow_id"] == workflow_id
    assert get_resp.json()["query"] == "test query"


def test_get_workflow_404_for_well_formed_but_unknown_uuid(client):
    unknown_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/workflows/{unknown_id}")
    assert response.status_code == 404


def test_get_workflow_400_for_malformed_id():
    """A non-UUID path param like the old test suite's 'wf-123' must be
    a clean 400 Bad Request -- the actual regression this rewrite
    guards against. Before the fix, this hit an unhandled ValueError
    deep in repository code and surfaced as a bare 500, which is wrong:
    a malformed client-supplied ID is a CLIENT error, not a server
    failure."""
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/workflows/not-a-real-uuid")
        assert response.status_code == 400
        assert "not a valid workflow ID" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /workflows/{id}/tasks and /logs
# ---------------------------------------------------------------------------

def test_get_workflow_tasks_returns_list(client):
    create_resp = client.post("/api/v1/workflows", json={"query": "test"})
    workflow_id = create_resp.json()["workflow_id"]

    response = client.get(f"/api/v1/workflows/{workflow_id}/tasks")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_workflow_logs_returns_list(client):
    create_resp = client.post("/api/v1/workflows", json={"query": "test"})
    workflow_id = create_resp.json()["workflow_id"]

    response = client.get(f"/api/v1/workflows/{workflow_id}/logs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# POST /workflows/{id}/cancel and /retry
# ---------------------------------------------------------------------------

def test_cancel_workflow_on_real_workflow(client):
    create_resp = client.post("/api/v1/workflows", json={"query": "test"})
    workflow_id = create_resp.json()["workflow_id"]

    response = client.post(f"/api/v1/workflows/{workflow_id}/cancel")
    assert response.status_code == 200
    assert "cancel" in response.json()["message"].lower()

    # Confirm it actually persisted -- not just an HTTP 200 with no effect.
    get_resp = client.get(f"/api/v1/workflows/{workflow_id}")
    assert get_resp.json()["status"] == "cancelled"


def test_cancel_workflow_404_for_unknown_id(client):
    response = client.post(f"/api/v1/workflows/{uuid.uuid4()}/cancel")
    assert response.status_code == 404


def test_retry_workflow_on_real_workflow(client):
    create_resp = client.post("/api/v1/workflows", json={"query": "test"})
    workflow_id = create_resp.json()["workflow_id"]

    response = client.post(f"/api/v1/workflows/{workflow_id}/retry")
    assert response.status_code == 200
    assert "retry" in response.json()["message"].lower()


def test_retry_workflow_404_for_unknown_id(client):
    response = client.post(f"/api/v1/workflows/{uuid.uuid4()}/retry")
    assert response.status_code == 404


def test_cancel_workflow_400_for_malformed_id():
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/workflows/not-a-real-uuid/cancel")
        assert response.status_code == 400


def test_retry_workflow_400_for_malformed_id():
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/workflows/not-a-real-uuid/retry")
        assert response.status_code == 400


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
