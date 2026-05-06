"""Benchmark helpers for single-agent vs multi-agent runs."""

import re
from collections.abc import Callable, Iterable
from time import perf_counter

from multi_agent_research_lab.core.schemas import BenchmarkMetrics
from multi_agent_research_lab.core.state import ResearchState


Runner = Callable[[str], ResearchState]


def run_benchmark(
    run_name: str,
    query: str,
    runner: Runner,
) -> tuple[ResearchState, BenchmarkMetrics]:
    """Run one system and derive benchmark metrics from its produced output.

    The metrics are intentionally lightweight for a two-hour lab. They are not a
    substitute for human review. The important point is that they are derived from the
    returned ``ResearchState`` and final answer, not assigned as fixed baseline vs
    multi-agent numbers.
    """

    started = perf_counter()
    state = runner(query)
    latency = perf_counter() - started
    features = _output_features(state)
    metrics = BenchmarkMetrics(
        run_name=run_name,
        latency_seconds=latency,
        estimated_cost_usd=_estimated_cost(state),
        quality_score=_quality_score(state, features),
        citation_coverage=_citation_coverage(state),
        failure_rate=_failure_rate(state),
        trace_events=len(state.trace),
        source_count=len(state.sources),
        error_count=len(state.errors),
        notes=_notes(state, features),
        answer_word_count=features["answer_word_count"],
        cited_source_count=features["cited_source_count"],
        citation_reference_count=features["citation_reference_count"],
        distinct_agent_count=features["distinct_agent_count"],
        fallback_used=features["fallback_used"],
        api_call_count=_api_call_count(state),
        input_tokens=_token_count(state, "input_tokens"),
        output_tokens=_token_count(state, "output_tokens"),
    )
    return state, metrics


def run_benchmark_suite(
    queries: Iterable[str],
    baseline_runner: Runner,
    multi_agent_runner: Runner,
) -> tuple[list[ResearchState], list[BenchmarkMetrics]]:
    """Run baseline and multi-agent benchmarks for each query."""

    states: list[ResearchState] = []
    metrics: list[BenchmarkMetrics] = []
    for index, query in enumerate(queries, start=1):
        baseline_state, baseline_metrics = run_benchmark(
            f"baseline_q{index}",
            query,
            baseline_runner,
        )
        multi_state, multi_metrics = run_benchmark(
            f"multi_agent_q{index}",
            query,
            multi_agent_runner,
        )
        states.extend([baseline_state, multi_state])
        metrics.extend([baseline_metrics, multi_metrics])
    return states, metrics


def _estimated_cost(state: ResearchState) -> float | None:
    costs = [result.metadata.get("cost_usd") for result in state.agent_results]
    numeric_costs = [float(cost) for cost in costs if isinstance(cost, int | float)]
    if not numeric_costs:
        return None
    return sum(numeric_costs)


def _api_call_count(state: ResearchState) -> int:
    total = 0
    for source in state.sources:
        value = source.metadata.get("api_call_count")
        if isinstance(value, int):
            total += value
    for result in state.agent_results:
        provider = result.metadata.get("provider")
        if provider == "openai" and result.agent.value != "researcher":
            total += 1
    return total


def _token_count(state: ResearchState, key: str) -> int:
    total = 0
    for source in state.sources:
        value = source.metadata.get(key)
        if isinstance(value, int):
            total += value
    for result in state.agent_results:
        if result.agent.value == "researcher":
            # Researcher token usage is already recorded on its source metadata.
            continue
        value = result.metadata.get(key)
        if isinstance(value, int):
            total += value
    return total


def _quality_score(state: ResearchState, features: dict[str, int | bool]) -> float:
    """Compute a transparent output-quality proxy from observable run artifacts.

    This score intentionally avoids hard-coded values by run type. A run earns points
    for a substantive answer, query-term coverage, cited evidence, role/trace
    transparency, and successful completion. Errors and fallback usage reduce the score.
    """

    final_answer = state.final_answer or ""
    answer_words = int(features["answer_word_count"])
    distinct_agents = int(features["distinct_agent_count"])

    # Answer substance: 0-2 points based on output length. Longer answers do not
    # automatically win after 300 words, which keeps the score useful for short lab runs.
    answer_substance = min(2.0, (answer_words / 300.0) * 2.0)

    # Evidence use: 0-2 points from citation coverage and source richness.
    source_richness = min(1.0, len(state.sources) / 5.0)
    evidence_use = (1.5 * _citation_coverage(state)) + (0.5 * source_richness)

    # Query relevance: 0-1.5 points from term overlap between query and final output.
    query_terms = _terms(state.request.query)
    answer_terms = _terms(final_answer)
    relevance = 0.0
    if query_terms:
        relevance = 1.5 * (len(query_terms & answer_terms) / len(query_terms))

    # Traceability/role separation: baseline can earn trace points, multi-agent earns more
    # only when the output state actually contains multiple agent results and trace events.
    traceability = min(1.0, len(state.trace) / 10.0)
    role_separation = min(1.0, distinct_agents / 4.0)

    # Completion and guardrail health: reward completion, penalize errors/fallbacks.
    completion = 1.0 if state.final_answer and state.is_complete else 0.0
    penalty = min(2.0, len(state.errors) * 0.75)
    if bool(features["fallback_used"]):
        penalty += 0.5

    score = (
        answer_substance
        + evidence_use
        + relevance
        + traceability
        + role_separation
        + completion
        - penalty
    )
    return round(max(0.0, min(score, 10.0)), 2)


def _citation_coverage(state: ResearchState) -> float:
    if "citation_coverage" in state.metadata:
        value = state.metadata["citation_coverage"]
        if isinstance(value, int | float):
            return float(value)
    if not state.sources:
        return 0.0
    final_answer = state.final_answer or ""
    cited = sum(
        1
        for index in range(1, len(state.sources) + 1)
        if f"[S{index}]" in final_answer
    )
    return cited / len(state.sources)


def _failure_rate(state: ResearchState) -> float:
    denominator = max(1, state.iteration)
    return min(1.0, len(state.errors) / denominator)


def _output_features(state: ResearchState) -> dict[str, int | bool]:
    final_answer = state.final_answer or ""
    cited_ids = set(re.findall(r"\[S(\d+)\]", final_answer))
    citation_refs = re.findall(r"\[S\d+\]", final_answer)
    distinct_agents = {result.agent.value for result in state.agent_results}
    trace_names = {str(event.get("name", "")) for event in state.trace}
    fallback_used = (
        any(
            source.metadata.get("source_type") in {"fallback", "openai_model_fallback"}
            for source in state.sources
        )
        or "workflow.agent_fallback" in trace_names
        or "workflow.writer_fallback" in trace_names
    )
    return {
        "answer_word_count": len(final_answer.split()),
        "cited_source_count": len(cited_ids),
        "citation_reference_count": len(citation_refs),
        "distinct_agent_count": len(distinct_agents),
        "fallback_used": fallback_used,
    }


def _notes(state: ResearchState, features: dict[str, int | bool]) -> str:
    details = [
        f"answer_words={features['answer_word_count']}",
        f"citation_refs={features['citation_reference_count']}",
        f"agents={features['distinct_agent_count']}",
        f"api_calls={_api_call_count(state)}",
    ]
    if state.errors:
        details.append(f"errors={len(state.errors)}")
    if bool(features["fallback_used"]):
        details.append("fallback_used=true")
    return "; ".join(details)


def _terms(text: str) -> set[str]:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
    stopwords = {
        "and",
        "are",
        "for",
        "from",
        "into",
        "the",
        "this",
        "that",
        "with",
        "write",
    }
    return {term for term in cleaned.split() if len(term) >= 3 and term not in stopwords}
