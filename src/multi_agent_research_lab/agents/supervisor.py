"""Supervisor / router agent."""

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.config import get_settings
from multi_agent_research_lab.core.state import ResearchState


class SupervisorAgent(BaseAgent):
    """Decides which worker should run next and when to stop."""

    name = "supervisor"

    VALID_ROUTES = {"researcher", "analyst", "writer", "critic", "done"}

    def run(self, state: ResearchState) -> ResearchState:
        """Update ``state.route_history`` with the next route.

        Routing policy:
        - gather research first;
        - analyse research second;
        - write a final answer third;
        - run the bonus critic once;
        - stop when complete or when max iterations is reached.
        """

        settings = get_settings()
        if state.iteration >= settings.max_iterations:
            route = "done" if state.final_answer else "writer"
            reason = "max_iterations_reached"
        elif not state.research_notes:
            route = "researcher"
            reason = "missing_research_notes"
        elif not state.analysis_notes:
            route = "analyst"
            reason = "missing_analysis_notes"
        elif not state.final_answer:
            route = "writer"
            reason = "missing_final_answer"
        elif not state.metadata.get("critic_review"):
            route = "critic"
            reason = "missing_critic_review"
        else:
            route = "done"
            reason = "all_required_outputs_present"
            state.mark_complete()

        if route not in self.VALID_ROUTES:
            route = "done"
            reason = "invalid_route_fallback"
            state.add_error("Supervisor produced an invalid route and fell back to done.")

        state.record_route(route)
        state.add_trace_event(
            "agent.supervisor.route",
            {
                "route": route,
                "reason": reason,
                "iteration": state.iteration,
                "max_iterations": settings.max_iterations,
            },
        )
        return state
