"""Workflow orchestration for the multi-agent lab."""

from collections.abc import Mapping
from time import perf_counter

from multi_agent_research_lab.agents import (
    AnalystAgent,
    CriticAgent,
    ResearcherAgent,
    SupervisorAgent,
    WriterAgent,
)
from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.config import get_settings
from multi_agent_research_lab.core.errors import AgentExecutionError
from multi_agent_research_lab.core.schemas import SourceDocument
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.observability.tracing import trace_span


class MultiAgentWorkflow:
    """Builds and runs the multi-agent graph.

    The implementation is deliberately lightweight for the two-hour lab: no long-running
    services, no external graph runtime requirement, and no hidden background work.
    """

    def __init__(self, agents: Mapping[str, BaseAgent] | None = None) -> None:
        self.supervisor = SupervisorAgent()
        self.agents: dict[str, BaseAgent] = dict(agents or self.build())

    def build(self) -> Mapping[str, BaseAgent]:
        """Create the workflow node map.

        This is the lab-scale equivalent of a graph definition. The Supervisor decides
        the route; this map binds each route to its executable node.
        """

        return {
            "researcher": ResearcherAgent(),
            "analyst": AnalystAgent(),
            "writer": WriterAgent(),
            "critic": CriticAgent(),
        }

    def run(self, state: ResearchState) -> ResearchState:
        """Execute the workflow and return final state."""

        settings = get_settings()
        started = perf_counter()
        while not state.is_complete:
            elapsed = perf_counter() - started
            if elapsed > settings.timeout_seconds:
                state.add_error(
                    f"Workflow timeout after {elapsed:.2f}s; using final fallback if needed."
                )
                if not state.final_answer:
                    self._fallback_writer(state, "timeout")
                state.mark_complete()
                break

            with trace_span("supervisor", {"iteration": state.iteration}) as span:
                self.supervisor.run(state)
            state.add_trace_event("span.supervisor", span)

            route = state.latest_route()
            if route == "done":
                state.mark_complete()
                break

            if route is None:
                state.add_error("Supervisor did not provide a route; stopping workflow.")
                state.mark_complete()
                break

            agent = self.agents.get(route)
            if agent is None:
                state.add_error(f"No agent registered for route '{route}'; stopping workflow.")
                state.mark_complete()
                break

            self._run_agent_with_guardrails(agent, state)

            if state.iteration >= settings.max_iterations and not state.is_complete:
                if not state.final_answer:
                    self._fallback_writer(state, "max_iterations")
                state.add_trace_event(
                    "workflow.max_iterations",
                    {"iteration": state.iteration, "max_iterations": settings.max_iterations},
                )

        state.add_trace_event(
            "workflow.completed",
            {
                "iterations": state.iteration,
                "routes": state.route_history,
                "errors": len(state.errors),
            },
        )
        return state

    def _run_agent_with_guardrails(self, agent: BaseAgent, state: ResearchState) -> None:
        attempts = 2
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                with trace_span(
                    f"agent.{agent.name}",
                    {"attempt": attempt, "route": agent.name},
                ) as span:
                    agent.run(state)
                state.add_trace_event(f"span.agent.{agent.name}", span)
                return
            except Exception as exc:  # pragma: no cover - defensive guardrail
                last_error = exc
                state.add_error(f"{agent.name} attempt {attempt} failed: {exc}")

        self._apply_agent_fallback(agent.name, state, last_error)

    def _apply_agent_fallback(
        self,
        agent_name: str,
        state: ResearchState,
        error: Exception | None,
    ) -> None:
        reason = str(error) if error else "unknown error"
        if agent_name == "researcher":
            state.sources = [
                SourceDocument(
                    title="Workflow researcher fallback",
                    url=None,
                    snippet="Researcher failed after retries; no external evidence is claimed.",
                    metadata={"source_type": "fallback", "reason": reason},
                )
            ]
            state.research_notes = (
                "Research notes:\n"
                "[S1] Workflow researcher fallback: Researcher failed after retries; "
                "no external evidence is claimed."
            )
        elif agent_name == "analyst":
            state.analysis_notes = (
                "Analysis notes:\n"
                "- Analyst failed after retries. Use research notes directly and state limits."
            )
        elif agent_name == "writer":
            self._fallback_writer(state, reason)
        elif agent_name == "critic":
            state.metadata["critic_review"] = "Critic failed after retries; review unavailable."
            state.metadata["critic_passed"] = False
        else:
            raise AgentExecutionError(f"Unknown agent fallback requested: {agent_name}")
        state.add_trace_event("workflow.agent_fallback", {"agent": agent_name, "reason": reason})

    def _fallback_writer(self, state: ResearchState, reason: str) -> None:
        source_summary = "\n".join(
            f"- [S{index}] {source.title}: {source.snippet}"
            for index, source in enumerate(state.sources, start=1)
        )
        if not source_summary:
            source_summary = "- No sources available."
        state.final_answer = "\n".join(
            [
                f"# Fallback answer for: {state.request.query}",
                "",
                f"The writer fallback was used because: {reason}.",
                "Available evidence:",
                source_summary,
                "",
                "This response avoids adding facts beyond the available state.",
            ]
        )
        state.add_trace_event("workflow.writer_fallback", {"reason": reason})
