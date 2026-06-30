"""
Output schema for the Research Agent.

Designed so partial failure is representable IN the shape itself, not
just mentioned in a free-text field. A caller (Verification Agent,
Aggregator) can check `sources_attempted` vs the populated result lists
and `errors` without parsing prose -- this is the same principle as the
Planner's structured output: make the failure mode a first-class field,
not a string you have to grep.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .tools import DocumentSearchResult, KnowledgeRetrievalResult, WebSearchResult


class SourceType(str, Enum):
    WEB_SEARCH = "web_search"
    DOCUMENT_SEARCH = "document_search"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"


class SourceError(BaseModel):
    source: SourceType
    error_message: str


class ResearchFindings(BaseModel):
    """The structured result of one research task."""

    task_id: str
    query: str

    web_results: list[WebSearchResultModel] = Field(default_factory=list)
    document_results: list[DocumentSearchResultModel] = Field(default_factory=list)
    knowledge_results: list[KnowledgeRetrievalResultModel] = Field(default_factory=list)

    summary: str = Field(
        ...,
        description="LLM-generated synthesis of all successfully retrieved sources. "
        "If every source failed, this explains that no findings were available "
        "rather than being left empty.",
    )

    sources_attempted: list[SourceType] = Field(default_factory=list)
    sources_succeeded: list[SourceType] = Field(default_factory=list)
    errors: list[SourceError] = Field(default_factory=list)

    @property
    def is_complete_success(self) -> bool:
        return len(self.sources_succeeded) == len(self.sources_attempted) and len(self.sources_attempted) > 0

    @property
    def is_total_failure(self) -> bool:
        return len(self.sources_attempted) > 0 and len(self.sources_succeeded) == 0

    @property
    def is_partial_success(self) -> bool:
        return not self.is_complete_success and not self.is_total_failure and len(self.sources_attempted) > 0


# Pydantic-friendly mirrors of the frozen dataclasses in tools.py.
# Kept separate from the dataclasses themselves (rather than making
# WebSearchResult etc. Pydantic models directly) so tools.py stays a pure
# domain-port module with no Pydantic dependency -- a tool adapter
# shouldn't need to import Pydantic just to satisfy this agent's
# serialization needs.

class WebSearchResultModel(BaseModel):
    title: str
    url: str
    snippet: str

    @classmethod
    def from_domain(cls, r: WebSearchResult) -> "WebSearchResultModel":
        return cls(title=r.title, url=r.url, snippet=r.snippet)


class DocumentSearchResultModel(BaseModel):
    document_id: str
    title: str
    excerpt: str
    page_number: int | None = None

    @classmethod
    def from_domain(cls, r: DocumentSearchResult) -> "DocumentSearchResultModel":
        return cls(document_id=r.document_id, title=r.title, excerpt=r.excerpt, page_number=r.page_number)


class KnowledgeRetrievalResultModel(BaseModel):
    memory_id: str
    content: str
    confidence: float
    memory_type: str

    @classmethod
    def from_domain(cls, r: KnowledgeRetrievalResult) -> "KnowledgeRetrievalResultModel":
        return cls(memory_id=r.memory_id, content=r.content, confidence=r.confidence, memory_type=r.memory_type)


ResearchFindings.model_rebuild()
