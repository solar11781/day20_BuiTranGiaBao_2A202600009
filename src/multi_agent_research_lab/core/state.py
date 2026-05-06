"""Shared state for the multi-agent workflow."""

from typing import Any

from pydantic import BaseModel, Field

from multi_agent_research_lab.core.schemas import (
    AgentName,
    AgentResult,
    ResearchQuery,
    SourceDocument,
)


class ResearchState(BaseModel):
    """Single source of truth passed through the workflow.

    The fields are intentionally compact for a two-hour lab, but they cover the handoff
    needs from the lab guide: routing, sources, notes, final output, trace, and failures.
    """

    request: ResearchQuery
    iteration: int = 0
    route_history: list[str] = Field(default_factory=list)

    sources: list[SourceDocument] = Field(default_factory=list)
    research_notes: str | None = None
    analysis_notes: str | None = None
    final_answer: str | None = None

    agent_results: list[AgentResult] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def record_route(self, route: str) -> None:
        """Record a supervisor route decision and increment the workflow iteration."""

        self.route_history.append(route)
        self.iteration += 1

    def add_trace_event(self, name: str, payload: dict[str, Any]) -> None:
        """Append a trace event in a JSON-serialisable format."""

        self.trace.append({"name": name, "payload": payload})

    def add_result(
        self,
        agent: AgentName,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append one structured agent result."""

        self.agent_results.append(
            AgentResult(agent=agent, content=content, metadata=metadata or {})
        )

    def add_error(self, message: str) -> None:
        """Record an error and mirror it into the trace for easier debugging."""

        self.errors.append(message)
        self.add_trace_event("error", {"message": message})

    def latest_route(self) -> str | None:
        """Return the last supervisor route, if present."""

        if not self.route_history:
            return None
        return self.route_history[-1]

    def mark_complete(self) -> None:
        """Mark the workflow as completed."""

        self.metadata["completed"] = True

    @property
    def is_complete(self) -> bool:
        """Whether the workflow reached a terminal state."""

        return bool(self.metadata.get("completed"))
