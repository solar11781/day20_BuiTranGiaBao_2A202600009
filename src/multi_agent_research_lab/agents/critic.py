"""Optional critic agent for bonus guardrail work."""

import re

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.schemas import AgentName
from multi_agent_research_lab.core.state import ResearchState


class CriticAgent(BaseAgent):
    """Fact-checking and safety-review agent for the lab workflow."""

    name = "critic"

    def run(self, state: ResearchState) -> ResearchState:
        """Validate the final answer and append critic findings."""

        findings: list[str] = []
        if not state.final_answer:
            findings.append("FAIL: final answer is missing.")
        else:
            findings.append("PASS: final answer is present.")

        coverage = self._citation_coverage(state)
        if state.sources and coverage < 1.0:
            findings.append(
                f"WARN: citation coverage is {coverage:.0%}; not every source is referenced."
            )
        elif state.sources:
            findings.append("PASS: all sources are referenced at least once.")
        else:
            findings.append("WARN: no sources available for citation coverage check.")

        if state.errors:
            findings.append(f"WARN: workflow recorded {len(state.errors)} error(s).")
        else:
            findings.append("PASS: no workflow errors recorded.")

        critic_report = "Critic review:\n" + "\n".join(f"- {finding}" for finding in findings)
        state.metadata["critic_review"] = critic_report
        state.metadata["citation_coverage"] = coverage
        state.metadata["critic_passed"] = state.final_answer is not None and bool(state.sources)
        state.add_result(
            AgentName.CRITIC,
            critic_report,
            {"citation_coverage": coverage, "error_count": len(state.errors)},
        )
        state.add_trace_event(
            "agent.critic.completed",
            {"citation_coverage": coverage, "error_count": len(state.errors)},
        )
        return state

    def _citation_coverage(self, state: ResearchState) -> float:
        if not state.sources or not state.final_answer:
            return 0.0
        references = set(re.findall(r"\[S(\d+)\]", state.final_answer))
        cited = sum(1 for index in range(1, len(state.sources) + 1) if str(index) in references)
        return cited / len(state.sources)
