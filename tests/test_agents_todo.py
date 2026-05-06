from multi_agent_research_lab.agents import SupervisorAgent
from multi_agent_research_lab.core.schemas import ResearchQuery
from multi_agent_research_lab.core.state import ResearchState


def test_supervisor_routes_to_researcher_first() -> None:
    state = ResearchState(request=ResearchQuery(query="Explain multi-agent systems"))

    result = SupervisorAgent().run(state)

    assert result.route_history == ["researcher"]
    assert result.iteration == 1
    assert result.trace[-1]["name"] == "agent.supervisor.route"
    assert result.trace[-1]["payload"]["route"] == "researcher"
