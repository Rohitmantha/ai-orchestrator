"""
Tool ports for the Research Agent.

Same Clean Architecture discipline as llm_provider.py in the planner
module: the agent depends only on these abstract interfaces, never on a
concrete search API / vector DB / document store SDK. Each capability
(web search, document search, knowledge retrieval) gets its own port
rather than one generic "search" interface, because they genuinely
return different shapes of result (a web result has a URL; a knowledge
base hit has a confidence score and a source memory_id; a document
search hit has a file path/page) and collapsing them into one interface
would mean lossy generic fields or constant None-checking downstream.

Concrete adapters (e.g. a Tavily/Bing web search adapter, a pgvector-
backed knowledge retriever hitting the `memories` table) are NOT included
here -- this module defines the contract; wiring in a real search API is
an infrastructure-layer concern for whoever assembles the running system,
matching how OpenAIProvider was the one concrete LLMProvider implementation
provided while the interface stayed generic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ToolError(Exception):
    """Raised when a tool call fails (timeout, unreachable, rate limited,
    malformed response from the underlying service). Each tool's own
    failure does not necessarily mean the Research Agent's task fails --
    see ResearchAgent's partial-failure handling."""


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class DocumentSearchResult:
    document_id: str
    title: str
    excerpt: str
    page_number: int | None = None


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    memory_id: str
    content: str
    confidence: float  # 0.0-1.0, mirrors `memories.importance_score` semantics
    memory_type: str    # mirrors the `memory_type` ENUM: episodic/semantic/procedural/summary


class WebSearchTool(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[WebSearchResult]:
        raise NotImplementedError


class DocumentSearchTool(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[DocumentSearchResult]:
        raise NotImplementedError


class KnowledgeRetrievalTool(ABC):
    @abstractmethod
    async def retrieve(self, query: str, max_results: int = 5) -> list[KnowledgeRetrievalResult]:
        raise NotImplementedError
