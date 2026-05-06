"""Researcher agent."""

from typing import Any

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.schemas import AgentName, SourceDocument
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.search_client import SearchClient


class ResearcherAgent(BaseAgent):
    """Collects OpenAI search results and creates concise research notes."""

    name = "researcher"

    def __init__(self, search_client: SearchClient | None = None) -> None:
        self.search_client = search_client or SearchClient()

    def run(self, state: ResearchState) -> ResearchState:
        """Populate ``state.sources`` and ``state.research_notes``."""

        try:
            sources = self.search_client.search(
                state.request.query,
                max_results=state.request.max_sources,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            state.add_error(f"Researcher search failed; using fallback source: {exc}")
            sources = [self._fallback_source(state.request.query, str(exc))]

        if not sources:
            sources = [self._fallback_source(state.request.query, "search returned no results")]

        state.sources = sources
        notes = ["Research notes:"]
        for index, source in enumerate(sources, start=1):
            url = source.url or "no-url"
            provider = source.metadata.get("provider", "unknown")
            notes.append(f"[S{index}] {source.title} ({url}, provider={provider}): {source.snippet}")
        state.research_notes = "\n".join(notes)
        metadata = self._usage_metadata(sources)
        metadata["source_count"] = len(sources)
        metadata["fallback"] = self._used_fallback(sources)
        metadata["used_web_search"] = any(
            bool(source.metadata.get("used_web_search")) for source in sources
        )
        state.add_result(
            AgentName.RESEARCHER,
            state.research_notes,
            metadata,
        )
        state.add_trace_event(
            "agent.researcher.completed",
            {
                "source_count": len(sources),
                "fallback": self._used_fallback(sources),
                "used_web_search": metadata["used_web_search"],
                "provider": metadata.get("provider"),
            },
        )
        return state

    def _fallback_source(self, query: str, reason: str) -> SourceDocument:
        return SourceDocument(
            title="Researcher fallback source",
            url=None,
            snippet=(
                "OpenAI search failed or returned no usable result. The final response must "
                f"disclose that only fallback evidence is available. Reason: {reason}. "
                f"Query: {query}"
            ),
            metadata={"source_type": "fallback", "provider": "none", "cost_usd": 0.0},
        )

    def _used_fallback(self, sources: list[SourceDocument]) -> bool:
        return any(
            source.metadata.get("source_type") in {"fallback", "openai_model_fallback"}
            for source in sources
        )

    def _usage_metadata(self, sources: list[SourceDocument]) -> dict[str, Any]:
        input_tokens = sum(
            int(value)
            for value in (source.metadata.get("input_tokens") for source in sources)
            if isinstance(value, int)
        )
        output_tokens = sum(
            int(value)
            for value in (source.metadata.get("output_tokens") for source in sources)
            if isinstance(value, int)
        )
        costs = [source.metadata.get("cost_usd") for source in sources]
        numeric_costs = [float(cost) for cost in costs if isinstance(cost, int | float)]
        providers = sorted(
            {str(source.metadata.get("provider")) for source in sources if source.metadata.get("provider")}
        )
        models = sorted(
            {str(source.metadata.get("model")) for source in sources if source.metadata.get("model")}
        )
        return {
            "provider": ",".join(providers) if providers else None,
            "model": ",".join(models) if models else None,
            "input_tokens": input_tokens or None,
            "output_tokens": output_tokens or None,
            "cost_usd": sum(numeric_costs) if numeric_costs else None,
        }
