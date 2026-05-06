"""Analyst agent."""

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.schemas import AgentName
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.llm_client import LLMClient


class AnalystAgent(BaseAgent):
    """Turns research notes into structured insights."""

    name = "analyst"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def run(self, state: ResearchState) -> ResearchState:
        """Populate ``state.analysis_notes`` with claims, gaps, and risks."""

        if not state.research_notes:
            state.add_error("Analyst received no research notes; using empty-evidence fallback.")

        source_lines = [
            f"- [S{index}] {source.title}: {source.snippet}"
            for index, source in enumerate(state.sources, start=1)
        ]
        if not source_lines:
            source_lines = ["- No sources were available; answer must be explicit about limits."]

        fallback_present = any(
            source.metadata.get("source_type") in {"fallback", "openai_model_fallback"}
            for source in state.sources
        )
        limitation = (
            "OpenAI web search was unavailable or fell back to model-only output. "
            "Do not claim current sourced evidence beyond what is in the provided state."
            if fallback_present
            else "Evidence is limited to the sources returned by the configured OpenAI search call."
        )
        response = self.llm_client.complete(
            "You are the Analyst in a multi-agent research workflow.",
            "\n".join(
                [
                    f"User query: {state.request.query}",
                    "Research notes:",
                    state.research_notes or "No research notes were available.",
                    "Sources:",
                    *source_lines,
                    "Write structured analysis notes with: key evidence, implications, gaps, risks, and recommended final-answer structure.",
                    "Keep source IDs such as [S1] attached to claims.",
                    f"Limitation to preserve: {limitation}",
                ]
            ),
        )
        state.analysis_notes = response.content
        state.add_result(
            AgentName.ANALYST,
            state.analysis_notes,
            {
                "fallback_present": fallback_present,
                "provider": response.provider,
                "model": response.model,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": response.cost_usd,
                "llm_fallback_used": response.fallback_used,
            },
        )
        state.add_trace_event(
            "agent.analyst.completed",
            {
                "source_count": len(state.sources),
                "fallback_present": fallback_present,
                "provider": response.provider,
            },
        )
        return state
