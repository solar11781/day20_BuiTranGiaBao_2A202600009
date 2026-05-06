"""Command-line entrypoint for the lab system."""

import os
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from langsmith import Client, traceable, tracing_context
from rich.console import Console
from rich.panel import Panel

from multi_agent_research_lab.core.config import get_settings
from multi_agent_research_lab.core.schemas import AgentName, ResearchQuery
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.evaluation.benchmark import run_benchmark_suite
from multi_agent_research_lab.evaluation.report import render_markdown_report
from multi_agent_research_lab.graph.workflow import MultiAgentWorkflow
from multi_agent_research_lab.observability.logging import configure_logging
from multi_agent_research_lab.services.llm_client import LLMClient
from multi_agent_research_lab.services.search_client import SearchClient
from multi_agent_research_lab.services.storage import LocalArtifactStore

app = typer.Typer(help="Multi-Agent Research Lab CLI")
console = Console()


def _init() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    _configure_langsmith_environment(settings)

def _configure_langsmith_environment(settings: Any) -> None:
    """Make LangSmith settings visible to the LangSmith SDK.

    pydantic-settings reads `.env` into the Settings object, but LangSmith reads
    tracing configuration from os.environ unless a client/context is passed
    explicitly. This bridge keeps agents free from direct environment access.
    """

    if not settings.langsmith_tracing:
        return

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key or ""
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project

    # Compatibility for older LangSmith/LangChain integrations.
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_ENDPOINT", settings.langsmith_endpoint)
    os.environ.setdefault("LANGCHAIN_API_KEY", settings.langsmith_api_key or "")
    os.environ.setdefault("LANGCHAIN_PROJECT", settings.langsmith_project)

def _langsmith_client() -> Client | None:
    """Return a configured LangSmith client when tracing is enabled."""

    settings = get_settings()
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        return None
    return Client(
        api_key=settings.langsmith_api_key,
        api_url=settings.langsmith_endpoint,
    )

@traceable(name="benchmark_run")
def _run_benchmark_with_tracing(
    queries: list[str],
) -> tuple[list[ResearchState], list[Any]]:
    return run_benchmark_suite(queries, run_baseline, run_multi_agent)

@app.command()
def baseline(
    query: Annotated[str, typer.Option("--query", "-q", help="Research query")],
) -> None:
    """Run a single-agent baseline."""

    _init()
    state = run_baseline(query)
    console.print(
        Panel.fit(state.final_answer or "No answer generated.", title="Single-Agent Baseline")
    )


@app.command("multi-agent")
def multi_agent(
    query: Annotated[str, typer.Option("--query", "-q", help="Research query")],
    show_json: Annotated[bool, typer.Option("--json", help="Print full state JSON")] = False,
) -> None:
    """Run the multi-agent workflow."""

    _init()
    state = run_multi_agent(query)
    console.print(
        Panel.fit(state.final_answer or "No answer generated.", title="Multi-Agent Answer")
    )
    critic_review = state.metadata.get("critic_review")
    if isinstance(critic_review, str):
        console.print(Panel.fit(critic_review, title="Critic Review"))
    if show_json:
        console.print(state.model_dump_json(indent=2))


@app.command("openai-check")
def openai_check() -> None:
    """Make one tiny OpenAI call and print recorded token/cost metadata."""

    _init()
    settings = get_settings()
    response = LLMClient(provider="openai", model=settings.openai_model).complete(
        "You are a connectivity checker.",
        "Reply with exactly: ok",
    )
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"provider: {response.provider}",
                    f"model: {response.model}",
                    f"fallback_used: {response.fallback_used}",
                    f"input_tokens: {response.input_tokens}",
                    f"output_tokens: {response.output_tokens}",
                    f"estimated_cost_usd: {response.cost_usd}",
                    f"content: {response.content.strip()}",
                    f"error: {response.error or ''}",
                ]
            ),
            title="OpenAI Check",
        )
    )


@app.command()
def benchmark(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="YAML config with benchmark.queries"),
    ] = Path("configs/lab_default.yaml"),
    reports_dir: Annotated[
        Path,
        typer.Option("--reports-dir", help="Directory for generated reports and traces"),
    ] = Path("reports"),
) -> None:
    """Run baseline vs multi-agent benchmarks and write reports automatically."""

    _init()
    queries = _load_benchmark_queries(config)
    langsmith_client = _langsmith_client()
    if langsmith_client is not None:
        with tracing_context(enabled=True):
            states, metrics = _run_benchmark_with_tracing(
                queries,
                langsmith_extra={"client": langsmith_client},
            )
    else:
        states, metrics = _run_benchmark_with_tracing(queries)
    report = render_markdown_report(metrics)

    store = LocalArtifactStore(reports_dir)
    report_path = store.write_text("benchmark_report.md", report)
    for index, state in enumerate(states, start=1):
        store.write_text(f"traces/run_{index:02d}.json", state.model_dump_json(indent=2))

    console.print(Panel.fit(f"Wrote benchmark report: {report_path}", title="Benchmark Complete"))
    console.print(report)

    if langsmith_client is not None:
        langsmith_client.flush()


@traceable(name="baseline_workflow")
def run_baseline(query: str) -> ResearchState:
    """Single-agent baseline that performs search, synthesis, and tracing in one step."""

    state = ResearchState(request=ResearchQuery(query=query))
    search_client = SearchClient()
    llm_client = LLMClient()
    sources = search_client.search(query, max_results=state.request.max_sources)
    state.sources = sources
    source_text = "\n".join(
        f"[S{index}] {source.title}: {source.snippet}"
        for index, source in enumerate(sources, start=1)
    )
    response = llm_client.complete(
        "You are a concise single-agent research baseline.",
        (
            f"Query: {query}\nSources:\n{source_text}\n"
            "Write a direct answer with source IDs. Disclose any search fallback. "
            "Do not claim repository docs were used as a knowledge base."
        ),
    )
    state.research_notes = "Single-agent baseline gathered and wrote in one pass."
    state.analysis_notes = "Single-agent baseline does not separate analysis into another role."
    state.final_answer = "\n".join(
        [
            f"# Baseline answer for: {query}",
            "",
            response.content,
            "",
            "Sources:",
            source_text or "No sources available.",
        ]
    )
    search_cost = _source_cost(sources)
    response_cost = response.cost_usd
    total_cost = _sum_optional_costs([search_cost, response_cost])
    state.add_result(
        AgentName.WRITER,
        state.final_answer,
        {
            "provider": response.provider,
            "model": response.model,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cost_usd": total_cost,
            "llm_cost_usd": response_cost,
            "search_cost_usd": search_cost,
        },
    )
    state.add_trace_event(
        "baseline.completed",
        {
            "source_count": len(sources),
            "provider": response.provider,
            "used_web_search": any(bool(source.metadata.get("used_web_search")) for source in sources),
        },
    )
    state.mark_complete()
    return state


@traceable(name="multi_agent_workflow")
def run_multi_agent(query: str) -> ResearchState:
    """Run the multi-agent workflow for benchmark and CLI reuse."""

    state = ResearchState(request=ResearchQuery(query=query))
    return MultiAgentWorkflow().run(state)


def _source_cost(sources: list[Any]) -> float | None:
    costs = [source.metadata.get("cost_usd") for source in sources]
    return _sum_optional_costs(costs)


def _sum_optional_costs(costs: list[Any]) -> float | None:
    numeric_costs = [float(cost) for cost in costs if isinstance(cost, int | float)]
    if not numeric_costs:
        return None
    return sum(numeric_costs)


def _load_benchmark_queries(config: Path) -> list[str]:
    if config.exists():
        loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            benchmark_config = loaded.get("benchmark")
            if isinstance(benchmark_config, dict):
                queries = benchmark_config.get("queries")
                if isinstance(queries, list) and all(isinstance(item, str) for item in queries):
                    return queries
    fallback_config = Path("lab_default.yaml")
    if fallback_config.exists() and fallback_config != config:
        loaded = yaml.safe_load(fallback_config.read_text(encoding="utf-8"))
        return _queries_from_mapping(loaded)
    return [
        "Research GraphRAG state-of-the-art and write a 500-word summary",
        "Compare single-agent and multi-agent workflows for customer support",
        "Summarize production guardrails for LLM agents",
    ]


def _queries_from_mapping(loaded: Any) -> list[str]:
    if isinstance(loaded, dict):
        benchmark_config = loaded.get("benchmark")
        if isinstance(benchmark_config, dict):
            queries = benchmark_config.get("queries")
            if isinstance(queries, list) and all(isinstance(item, str) for item in queries):
                return queries
    return []

@app.command("langsmith-test")
def langsmith_test() -> None:
    """Send one minimal test trace to LangSmith."""

    _init()
    langsmith_client = _langsmith_client()
    if langsmith_client is None:
        console.print(
            "LangSmith tracing is not enabled. Check LANGSMITH_TRACING and LANGSMITH_API_KEY."
        )
        return

    with tracing_context(enabled=True):
        _langsmith_test_inner(langsmith_extra={"client": langsmith_client})

    langsmith_client.flush()
    console.print("LangSmith test trace sent.")


@traceable(name="langsmith_test")
def _langsmith_test_inner() -> str:
    return "ok"

if __name__ == "__main__":
    app()
