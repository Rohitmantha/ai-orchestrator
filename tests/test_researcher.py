"""
Tests for the Research Agent.

Uses fake tools and a fake LLM provider -- no network calls. Specifically
stresses every combination of which sources succeed/fail, since "handle
failures" is the core requirement being tested here, not a side effect.
"""

import asyncio
import sys
from pathlib import Path

import pytest

_backend = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(_backend))
sys.path.insert(0, str(_backend / "app" / "agents"))

from app.llm_providers.llm_provider import LLMProvider, LLMProviderError
from researcher.logging_events import LogEventType
from researcher.research_agent import ResearchAgent, ResearchAgentError
from researcher.tools import (
    DocumentSearchResult,
    DocumentSearchTool,
    KnowledgeRetrievalResult,
    KnowledgeRetrievalTool,
    ToolError,
    WebSearchResult,
    WebSearchTool,
)


class FakeWebSearchTool(WebSearchTool):
    def __init__(self, results=None, should_fail=False, fail_message="web search down"):
        self._results = results or []
        self._should_fail = should_fail
        self._fail_message = fail_message
        self.call_count = 0

    async def search(self, query, max_results=5):
        self.call_count += 1
        if self._should_fail:
            raise ToolError(self._fail_message)
        return self._results[:max_results]


class FakeDocumentSearchTool(DocumentSearchTool):
    def __init__(self, results=None, should_fail=False):
        self._results = results or []
        self._should_fail = should_fail
        self.call_count = 0

    async def search(self, query, max_results=5):
        self.call_count += 1
        if self._should_fail:
            raise ToolError("document store unreachable")
        return self._results[:max_results]


class FakeKnowledgeRetrievalTool(KnowledgeRetrievalTool):
    def __init__(self, results=None, should_fail=False):
        self._results = results or []
        self._should_fail = should_fail
        self.call_count = 0

    async def retrieve(self, query, max_results=5):
        self.call_count += 1
        if self._should_fail:
            raise ToolError("knowledge base timeout")
        return self._results[:max_results]


class FakeLLMProvider(LLMProvider):
    def __init__(self, summary="A synthesized summary.", should_fail=False):
        self._summary = summary
        self._should_fail = should_fail
        self.call_count = 0
        self.last_user_prompt = None

    async def generate_structured(self, *, system_prompt, user_prompt, json_schema, schema_name):
        self.call_count += 1
        self.last_user_prompt = user_prompt
        if self._should_fail:
            raise LLMProviderError("simulated LLM outage")
        return {"summary": self._summary}


SAMPLE_WEB = [WebSearchResult(title="Article A", url="https://example.com/a", snippet="some content")]
SAMPLE_DOCS = [DocumentSearchResult(document_id="doc1", title="Internal Memo", excerpt="some excerpt", page_number=3)]
SAMPLE_KNOWLEDGE = [KnowledgeRetrievalResult(memory_id="mem1", content="prior finding", confidence=0.8, memory_type="semantic")]


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# All sources succeed
# ---------------------------------------------------------------------------

def test_all_sources_succeed():
    agent = ResearchAgent(
        llm_provider=FakeLLMProvider(),
        web_search_tool=FakeWebSearchTool(results=SAMPLE_WEB),
        document_search_tool=FakeDocumentSearchTool(results=SAMPLE_DOCS),
        knowledge_retrieval_tool=FakeKnowledgeRetrievalTool(results=SAMPLE_KNOWLEDGE),
    )
    findings, events = run(agent.execute(task_id="t1", query="What is the pricing model?"))

    assert findings.is_complete_success
    assert not findings.is_partial_success
    assert not findings.is_total_failure
    assert len(findings.web_results) == 1
    assert len(findings.document_results) == 1
    assert len(findings.knowledge_results) == 1
    assert findings.summary == "A synthesized summary."
    assert findings.errors == []


# ---------------------------------------------------------------------------
# Partial failure -- every combination of one source down
# ---------------------------------------------------------------------------

def test_web_search_fails_others_succeed():
    agent = ResearchAgent(
        llm_provider=FakeLLMProvider(),
        web_search_tool=FakeWebSearchTool(should_fail=True),
        document_search_tool=FakeDocumentSearchTool(results=SAMPLE_DOCS),
        knowledge_retrieval_tool=FakeKnowledgeRetrievalTool(results=SAMPLE_KNOWLEDGE),
    )
    findings, events = run(agent.execute(task_id="t1", query="q"))

    assert findings.is_partial_success
    assert findings.web_results == []
    assert len(findings.document_results) == 1
    assert len(findings.knowledge_results) == 1
    assert len(findings.errors) == 1
    assert findings.errors[0].source.value == "web_search"
    # Summarization should still have been attempted with the partial data
    assert findings.summary == "A synthesized summary."


def test_document_search_fails_others_succeed():
    agent = ResearchAgent(
        llm_provider=FakeLLMProvider(),
        web_search_tool=FakeWebSearchTool(results=SAMPLE_WEB),
        document_search_tool=FakeDocumentSearchTool(should_fail=True),
        knowledge_retrieval_tool=FakeKnowledgeRetrievalTool(results=SAMPLE_KNOWLEDGE),
    )
    findings, events = run(agent.execute(task_id="t1", query="q"))

    assert findings.is_partial_success
    assert findings.document_results == []
    assert len(findings.errors) == 1
    assert findings.errors[0].source.value == "document_search"


def test_knowledge_retrieval_fails_others_succeed():
    agent = ResearchAgent(
        llm_provider=FakeLLMProvider(),
        web_search_tool=FakeWebSearchTool(results=SAMPLE_WEB),
        document_search_tool=FakeDocumentSearchTool(results=SAMPLE_DOCS),
        knowledge_retrieval_tool=FakeKnowledgeRetrievalTool(should_fail=True),
    )
    findings, events = run(agent.execute(task_id="t1", query="q"))

    assert findings.is_partial_success
    assert findings.knowledge_results == []
    assert len(findings.errors) == 1
    assert findings.errors[0].source.value == "knowledge_retrieval"


def test_one_tool_failing_does_not_prevent_other_tools_from_being_called():
    """The core 'isolated failure' guarantee: even though web search
    fails, the other two tools must still actually be INVOKED, not
    short-circuited."""
    web = FakeWebSearchTool(should_fail=True)
    docs = FakeDocumentSearchTool(results=SAMPLE_DOCS)
    knowledge = FakeKnowledgeRetrievalTool(results=SAMPLE_KNOWLEDGE)
    agent = ResearchAgent(llm_provider=FakeLLMProvider(), web_search_tool=web, document_search_tool=docs, knowledge_retrieval_tool=knowledge)
    run(agent.execute(task_id="t1", query="q"))
    assert web.call_count == 1
    assert docs.call_count == 1
    assert knowledge.call_count == 1


# ---------------------------------------------------------------------------
# Total failure across all attempted sources
# ---------------------------------------------------------------------------

def test_all_sources_fail_llm_not_called_returns_honest_summary():
    """When everything fails, the agent should NOT call the LLM to
    'summarize nothing' (risk of fabrication) -- it should construct an
    honest failure message directly."""
    llm = FakeLLMProvider()
    agent = ResearchAgent(
        llm_provider=llm,
        web_search_tool=FakeWebSearchTool(should_fail=True),
        document_search_tool=FakeDocumentSearchTool(should_fail=True),
        knowledge_retrieval_tool=FakeKnowledgeRetrievalTool(should_fail=True),
    )
    findings, events = run(agent.execute(task_id="t1", query="q"))

    assert findings.is_total_failure
    assert len(findings.errors) == 3
    assert "No findings are available" in findings.summary
    assert llm.call_count == 0  # never called -- confirmed, not assumed


def test_no_tools_configured_returns_graceful_empty_result():
    agent = ResearchAgent(llm_provider=FakeLLMProvider())
    findings, events = run(agent.execute(task_id="t1", query="q"))
    assert findings.sources_attempted == []
    assert "No research sources were configured" in findings.summary


# ---------------------------------------------------------------------------
# Summarization LLM call itself failing
# ---------------------------------------------------------------------------

def test_summarization_fails_but_data_exists_returns_raw_findings_notice():
    agent = ResearchAgent(
        llm_provider=FakeLLMProvider(should_fail=True),
        web_search_tool=FakeWebSearchTool(results=SAMPLE_WEB),
    )
    findings, events = run(agent.execute(task_id="t1", query="q"))
    assert len(findings.web_results) == 1  # raw data still present
    assert "Summarization failed" in findings.summary
    assert "web_search" in findings.summary


def test_summarization_fails_and_no_data_raises():
    """The one genuinely unrecoverable case: nothing succeeded AND we
    can't even summarize that fact."""
    agent = ResearchAgent(
        llm_provider=FakeLLMProvider(should_fail=True),
        web_search_tool=FakeWebSearchTool(should_fail=True),
    )
    # All sources failed -> summarization is skipped entirely (per the
    # total-failure short-circuit), so this should NOT raise -- it
    # returns the honest "no findings" message without ever touching
    # the (also-broken) LLM.
    findings, events = run(agent.execute(task_id="t1", query="q"))
    assert findings.is_total_failure
    assert "No findings are available" in findings.summary


def test_summarization_fails_with_no_tools_configured_does_not_raise():
    """No tools attempted at all -> short-circuits before ever reaching
    the LLM, regardless of whether the LLM is broken."""
    agent = ResearchAgent(llm_provider=FakeLLMProvider(should_fail=True))
    findings, events = run(agent.execute(task_id="t1", query="q"))
    assert "No research sources were configured" in findings.summary


# ---------------------------------------------------------------------------
# Execution logging
# ---------------------------------------------------------------------------

def test_logs_invocation_and_completion():
    agent = ResearchAgent(llm_provider=FakeLLMProvider(), web_search_tool=FakeWebSearchTool(results=SAMPLE_WEB))
    findings, events = run(agent.execute(task_id="t1", query="q"))
    event_types = [e.event_type for e in events]
    assert LogEventType.AGENT_INVOKED in event_types
    assert LogEventType.AGENT_RESPONSE_RECEIVED in event_types


def test_logs_error_event_on_tool_failure():
    agent = ResearchAgent(llm_provider=FakeLLMProvider(), web_search_tool=FakeWebSearchTool(should_fail=True, fail_message="boom"))
    findings, events = run(agent.execute(task_id="t1", query="q"))
    error_events = [e for e in events if e.event_type == LogEventType.ERROR]
    assert len(error_events) == 1
    assert "boom" in error_events[0].message


def test_unexpected_exception_in_tool_is_caught_not_propagated():
    """Even a non-ToolError exception from a misbehaving tool adapter
    must not crash the whole agent -- isolation applies to ANY exception
    from a tool call, not just the well-behaved ToolError case."""
    class BrokenTool(WebSearchTool):
        async def search(self, query, max_results=5):
            raise RuntimeError("adapter bug, not a ToolError")

    agent = ResearchAgent(llm_provider=FakeLLMProvider(), web_search_tool=BrokenTool())
    findings, events = run(agent.execute(task_id="t1", query="q"))
    assert findings.errors[0].source.value == "web_search"
    assert "Unexpected error" in findings.errors[0].error_message


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
