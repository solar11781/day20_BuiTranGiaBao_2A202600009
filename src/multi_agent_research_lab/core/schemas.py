"""Public schemas exchanged between CLI, agents, and evaluators."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AgentName(StrEnum):
    """Names of supported agents in the lab workflow."""

    SUPERVISOR = "supervisor"
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    WRITER = "writer"
    CRITIC = "critic"


class ResearchQuery(BaseModel):
    """User request accepted by the research system."""

    query: str = Field(..., min_length=5)
    max_sources: int = Field(default=5, ge=1, le=20)
    audience: str = "technical learners"


class AgentResult(BaseModel):
    """Output produced by one agent turn."""

    agent: AgentName
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceDocument(BaseModel):
    """Small source record used by the local/mock search client."""

    title: str
    url: str | None = None
    snippet: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class BenchmarkMetrics(BaseModel):
    """Metrics collected for one benchmark run."""

    run_name: str
    latency_seconds: float
    estimated_cost_usd: float | None = None
    quality_score: float | None = Field(default=None, ge=0, le=10)
    citation_coverage: float | None = Field(default=None, ge=0, le=1)
    failure_rate: float | None = Field(default=None, ge=0, le=1)
    trace_events: int = 0
    source_count: int = 0
    error_count: int = 0
    notes: str = ""
    answer_word_count: int = 0
    cited_source_count: int = 0
    citation_reference_count: int = 0
    distinct_agent_count: int = 0
    fallback_used: bool = False
    api_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
