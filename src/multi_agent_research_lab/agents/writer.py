"""Writer agent."""

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.schemas import AgentName
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.llm_client import LLMClient


class WriterAgent(BaseAgent):
    """Produces final answer from research and analysis notes."""

    name = "writer"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def run(self, state: ResearchState) -> ResearchState:
        """Populate ``state.final_answer`` with source-aware synthesis."""

        if not state.analysis_notes:
            state.add_error(
                "Writer received no analysis notes; generating guarded fallback answer."
            )

        evidence = self._render_evidence(state)
        limitations = self._render_limitations(state)
        response = self.llm_client.complete(
            "You are the Writer in a multi-agent research workflow.",
            "\n".join(
                [
                    f"User query: {state.request.query}",
                    "Research notes:",
                    state.research_notes or "No research notes were available.",
                    "Analysis notes:",
                    state.analysis_notes or "No analysis notes were available.",
                    "Evidence list:",
                    evidence,
                    "Write the final answer in markdown.",
                    "Requirements:",
                    "- Answer the user query directly.",
                    "- Cite source IDs like [S1] for source-backed claims.",
                    "- Include a short 'Guardrails and fallbacks' section explaining max iterations, timeout, retry, fallback, and critic validation.",
                    "- Include a 'Limitations' section.",
                    f"Limitations to disclose: {limitations}",
                    "Do not claim that repository docs were used as the knowledge base.",
                ]
            ),
        )
        state.final_answer = self._ensure_source_block(response.content, state)
        state.add_result(
            AgentName.WRITER,
            state.final_answer,
            {
                "character_count": len(state.final_answer),
                "provider": response.provider,
                "model": response.model,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": response.cost_usd,
                "llm_fallback_used": response.fallback_used,
            },
        )
        state.add_trace_event(
            "agent.writer.completed",
            {
                "has_final_answer": bool(state.final_answer),
                "source_count": len(state.sources),
                "provider": response.provider,
            },
        )
        return state

    def _render_evidence(self, state: ResearchState) -> str:
        if not state.sources:
            return "No source documents were available."
        return "\n".join(
            f"- [S{index}] {source.title}: {source.snippet}"
            for index, source in enumerate(state.sources, start=1)
        )

    def _render_limitations(self, state: ResearchState) -> str:
        if not state.sources:
            return "The answer is a fallback because no sources were available."
        if any(source.metadata.get("source_type") == "fallback" for source in state.sources):
            return "OpenAI search was not executed, so no external evidence is claimed."
        if any(
            source.metadata.get("source_type") == "openai_model_fallback"
            for source in state.sources
        ):
            return "OpenAI web search failed and the Researcher used model-only fallback output."
        if not any(bool(source.metadata.get("used_web_search")) for source in state.sources):
            return "The OpenAI response did not expose a completed web-search call or citations."
        return "The answer is limited to the sources returned by the OpenAI search call."

    def _ensure_source_block(self, content: str, state: ResearchState) -> str:
        if not state.sources:
            return content
        if all(f"[S{index}]" in content for index in range(1, len(state.sources) + 1)):
            return content
        return "\n".join(
            [
                content.rstrip(),
                "",
                "## Evidence used",
                self._render_evidence(state),
            ]
        )
