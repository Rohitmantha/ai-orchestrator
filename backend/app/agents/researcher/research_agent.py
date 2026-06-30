"""
The Research Agent.

Responsibilities (per spec):
  - Web Search
  - Document Search
  - Knowledge Retrieval
  - Summarization
  - Return structured JSON
  - Handle failures
  - Log execution

Architectural note: same layering as the Planner. This class lives in the
infrastructure/agents layer (it calls tools and an LLM), but does NOT
persist anything to Postgres -- it returns (ResearchFindings, list[LogEvent])
and the Orchestrator is responsible for writing those as `tasks.output_payload`
and `execution_logs` rows respectively.

Failure handling philosophy: the three retrieval tools are independent --
a web search timeout should not prevent document search or knowledge
retrieval from still contributing to the result. Each tool call is
isolated in its own try/except, and the agent proceeds with whatever
succeeded. Only if EVERY attempted tool fails (or the LLM summarization
call itself fails) does this agent's execute() raise -- a partial result
is success with caveats, not failure, and is returned as a normal
ResearchFindings with `is_partial_success=True`, not as an exception.
"""

from __future__ import annotations

from app.llm_providers.llm_provider import LLMProvider, LLMProviderError

from .logging_events import ExecutionLogger, LogEventType
from .schemas import (
    DocumentSearchResultModel,
    KnowledgeRetrievalResultModel,
    ResearchFindings,
    SourceError,
    SourceType,
    WebSearchResultModel,
)
from .tools import DocumentSearchTool, KnowledgeRetrievalTool, ToolError, WebSearchTool

SUMMARIZATION_SYSTEM_PROMPT = """You are the summarization component of a Research Agent inside a \
multi-agent AI orchestration platform.

You will be given a research query and a set of findings gathered from \
up to three sources: web search, internal document search, and a \
knowledge base. Some sources may have failed to return anything -- you \
will be told which.

Write a clear, well-organized summary that:
1. Directly addresses the research query.
2. Synthesizes information ACROSS sources rather than listing them \
separately -- if multiple sources agree or disagree, say so.
3. Is honest about gaps: if a source failed or returned nothing, do not \
pretend the topic wasn't covered -- note that this aspect couldn't be \
verified from available sources, if relevant.
4. Contains no information that isn't present in the provided findings -- \
do not introduce outside knowledge as if it came from these sources.

If ALL sources failed and there are no findings at all, say so plainly \
and do not fabricate a summary."""


class ResearchAgentError(Exception):
    """Raised only when the agent cannot produce ANY usable output --
    i.e. every tool failed AND the summarization call itself also
    failed (so there isn't even a way to report "everything failed").
    A partial or even total-source-failure-but-summarized-as-such result
    is NOT an exception; it's a normal ResearchFindings with the failure
    state encoded in its fields."""


class ResearchAgent:
    def __init__(
        self,
        llm_provider: LLMProvider,
        web_search_tool: WebSearchTool | None = None,
        document_search_tool: DocumentSearchTool | None = None,
        knowledge_retrieval_tool: KnowledgeRetrievalTool | None = None,
    ):
        """Each tool is optional -- a deployment might not have a
        document store configured, for instance. Capability declaration
        (what this agent CAN do) lives in the Agent Registry, built
        separately; this constructor just reflects "what's actually
        wired up for this instance." If a tool is None, it's simply not
        attempted, and is absent from `sources_attempted` entirely
        (distinct from being attempted and failing)."""
        self._llm = llm_provider
        self._web_search = web_search_tool
        self._document_search = document_search_tool
        self._knowledge_retrieval = knowledge_retrieval_tool

    async def execute(self, task_id: str, task_input: dict) -> dict:
        """Dispatcher-facing entrypoint -- matches the shared
        execute(task_id, task_input) contract every agent uses. Wraps
        the rich internal implementation (which returns a typed
        ResearchFindings + log events) into the plain dict shape the
        dispatcher/database layer expects."""
        query = task_input.get("description") or str(task_input)
        findings, _log_events = await self._execute_internal(task_id=task_id, query=query)
        return {
            "result": findings.summary,
            "status": "completed" if findings.sources_succeeded else "completed_no_sources",
            "sources_attempted": [s.value for s in findings.sources_attempted],
            "sources_succeeded": [s.value for s in findings.sources_succeeded],
        }
        
    async def _execute_internal(
        self,
        *,
        task_id: str,
        query: str,
        max_results_per_source: int = 5,
    ) -> tuple[ResearchFindings, list]:
        """Runs all configured retrieval tools, summarizes what succeeded,
        and returns (findings, log_events).

        Raises ResearchAgentError only in the genuinely unrecoverable
        case: every configured tool failed AND the summarization LLM
        call also failed, leaving nothing to return at all -- not even an
        honest "nothing was found" summary.
        """
        logger = ExecutionLogger()
        logger.info(
            LogEventType.AGENT_INVOKED,
            f"Research Agent starting task '{task_id}'",
            task_id=task_id, query=query,
        )

        sources_attempted: list[SourceType] = []
        sources_succeeded: list[SourceType] = []
        errors: list[SourceError] = []

        web_results = await self._run_web_search(query, max_results_per_source, logger, sources_attempted, sources_succeeded, errors)
        document_results = await self._run_document_search(query, max_results_per_source, logger, sources_attempted, sources_succeeded, errors)
        knowledge_results = await self._run_knowledge_retrieval(query, max_results_per_source, logger, sources_attempted, sources_succeeded, errors)

        summary = await self._summarize(
            query=query,
            web_results=web_results,
            document_results=document_results,
            knowledge_results=knowledge_results,
            errors=errors,
            sources_attempted=sources_attempted,
            sources_succeeded=sources_succeeded,
            logger=logger,
        )

        findings = ResearchFindings(
            task_id=task_id,
            query=query,
            web_results=web_results,
            document_results=document_results,
            knowledge_results=knowledge_results,
            summary=summary,
            sources_attempted=sources_attempted,
            sources_succeeded=sources_succeeded,
            errors=errors,
        )

        logger.info(
            LogEventType.AGENT_RESPONSE_RECEIVED,
            f"Research Agent finished task '{task_id}'",
            task_id=task_id,
            sources_attempted=[s.value for s in sources_attempted],
            sources_succeeded=[s.value for s in sources_succeeded],
            error_count=len(errors),
        )

        return findings, logger.events

    # ------------------------------------------------------------------
    # Per-tool execution, each isolated so one failing tool doesn't take
    # down the others.
    # ------------------------------------------------------------------

    async def _run_web_search(self, query, max_results, logger, sources_attempted, sources_succeeded, errors):
        if self._web_search is None:
            return []
        sources_attempted.append(SourceType.WEB_SEARCH)
        try:
            results = await self._web_search.search(query, max_results=max_results)
            sources_succeeded.append(SourceType.WEB_SEARCH)
            logger.info(LogEventType.AGENT_RESPONSE_RECEIVED, "Web search succeeded", result_count=len(results))
            return [WebSearchResultModel.from_domain(r) for r in results]
        except ToolError as exc:
            logger.error(LogEventType.ERROR, f"Web search failed: {exc}", source="web_search")
            errors.append(SourceError(source=SourceType.WEB_SEARCH, error_message=str(exc)))
            return []
        except Exception as exc:  # noqa: BLE001 -- isolate unexpected tool failures too
            logger.error(LogEventType.ERROR, f"Web search failed unexpectedly: {exc}", source="web_search")
            errors.append(SourceError(source=SourceType.WEB_SEARCH, error_message=f"Unexpected error: {exc}"))
            return []

    async def _run_document_search(self, query, max_results, logger, sources_attempted, sources_succeeded, errors):
        if self._document_search is None:
            return []
        sources_attempted.append(SourceType.DOCUMENT_SEARCH)
        try:
            results = await self._document_search.search(query, max_results=max_results)
            sources_succeeded.append(SourceType.DOCUMENT_SEARCH)
            logger.info(LogEventType.AGENT_RESPONSE_RECEIVED, "Document search succeeded", result_count=len(results))
            return [DocumentSearchResultModel.from_domain(r) for r in results]
        except ToolError as exc:
            logger.error(LogEventType.ERROR, f"Document search failed: {exc}", source="document_search")
            errors.append(SourceError(source=SourceType.DOCUMENT_SEARCH, error_message=str(exc)))
            return []
        except Exception as exc:  # noqa: BLE001
            logger.error(LogEventType.ERROR, f"Document search failed unexpectedly: {exc}", source="document_search")
            errors.append(SourceError(source=SourceType.DOCUMENT_SEARCH, error_message=f"Unexpected error: {exc}"))
            return []

    async def _run_knowledge_retrieval(self, query, max_results, logger, sources_attempted, sources_succeeded, errors):
        if self._knowledge_retrieval is None:
            return []
        sources_attempted.append(SourceType.KNOWLEDGE_RETRIEVAL)
        try:
            results = await self._knowledge_retrieval.retrieve(query, max_results=max_results)
            sources_succeeded.append(SourceType.KNOWLEDGE_RETRIEVAL)
            logger.info(LogEventType.AGENT_RESPONSE_RECEIVED, "Knowledge retrieval succeeded", result_count=len(results))
            return [KnowledgeRetrievalResultModel.from_domain(r) for r in results]
        except ToolError as exc:
            logger.error(LogEventType.ERROR, f"Knowledge retrieval failed: {exc}", source="knowledge_retrieval")
            errors.append(SourceError(source=SourceType.KNOWLEDGE_RETRIEVAL, error_message=str(exc)))
            return []
        except Exception as exc:  # noqa: BLE001
            logger.error(LogEventType.ERROR, f"Knowledge retrieval failed unexpectedly: {exc}", source="knowledge_retrieval")
            errors.append(SourceError(source=SourceType.KNOWLEDGE_RETRIEVAL, error_message=f"Unexpected error: {exc}"))
            return []

    # ------------------------------------------------------------------
    # Summarization
    # ------------------------------------------------------------------

    async def _summarize(
        self, *, query, web_results, document_results, knowledge_results,
        errors, sources_attempted, sources_succeeded, logger,
    ) -> str:
        if sources_attempted and not sources_succeeded:
            # Total failure across every attempted source -- skip the LLM
            # call entirely. There's nothing to summarize, and calling an
            # LLM with "summarize this empty set of findings" risks it
            # fabricating content to fill the gap, which is exactly the
            # dishonesty the system prompt tells it not to do. Easier and
            # more reliable to construct this message directly.
            failed_sources = ", ".join(s.value for s in sources_attempted)
            return (
                f"No findings are available for this query. All attempted "
                f"sources ({failed_sources}) failed. See errors for details."
            )

        if not sources_attempted:
            return "No research sources were configured for this task; nothing was retrieved."

        user_prompt = self._build_summary_prompt(
            query, web_results, document_results, knowledge_results, errors, sources_attempted, sources_succeeded,
        )

        try:
            raw = await self._llm.generate_structured(
                system_prompt=SUMMARIZATION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                json_schema=_SUMMARY_JSON_SCHEMA,
                schema_name="research_summary",
            )
            summary = raw.get("summary", "").strip()
            if not summary:
                raise LLMProviderError("LLM returned an empty summary field")
            logger.info(LogEventType.AGENT_RESPONSE_RECEIVED, "Summarization succeeded")
            return summary
        except LLMProviderError as exc:
            logger.error(LogEventType.ERROR, f"Summarization failed: {exc}", source="summarization_llm")
            if sources_succeeded:
                # We have real findings but couldn't synthesize them --
                # better to surface the raw findings honestly than to
                # claim total failure when data IS present.
                return (
                    "Summarization failed, but raw findings were retrieved successfully "
                    "from: " + ", ".join(s.value for s in sources_succeeded) +
                    ". See web_results/document_results/knowledge_results for raw data."
                )
            raise ResearchAgentError(
                f"All sources failed and summarization also failed: {exc}"
            ) from exc

    @staticmethod
    def _build_summary_prompt(
        query, web_results, document_results, knowledge_results, errors, sources_attempted, sources_succeeded,
    ) -> str:
        parts = [f"Research query: {query}\n"]

        if web_results:
            parts.append("Web search results:")
            for r in web_results:
                parts.append(f"- {r.title} ({r.url}): {r.snippet}")
        if document_results:
            parts.append("\nDocument search results:")
            for r in document_results:
                page_info = f", page {r.page_number}" if r.page_number else ""
                parts.append(f"- {r.title}{page_info}: {r.excerpt}")
        if knowledge_results:
            parts.append("\nKnowledge base results:")
            for r in knowledge_results:
                parts.append(f"- ({r.memory_type}, confidence {r.confidence:.2f}): {r.content}")

        failed = [s for s in sources_attempted if s not in sources_succeeded]
        if failed:
            parts.append(f"\nNote: these sources were attempted but FAILED and contributed nothing: "
                          f"{', '.join(s.value for s in failed)}.")

        return "\n".join(parts)


_SUMMARY_JSON_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}
