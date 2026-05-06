"""Benchmark report rendering."""

from statistics import mean

from multi_agent_research_lab.core.schemas import BenchmarkMetrics


def render_markdown_report(metrics: list[BenchmarkMetrics]) -> str:
    """Render benchmark metrics and short automatic analysis to markdown."""

    lines = [
        "# Benchmark Report",
        "",
        "This report is generated automatically by the lab CLI from each run's produced ",
        "answer, trace, sources, metadata, and recorded errors.",
        "",
        "## Metric definitions",
        "",
        "- **Latency**: measured wall-clock runtime for the command path.",
        "- **Cost**: sum of available token/tool cost estimates from run metadata. "
        "It is blank when no reliable price is available; local fallback runs cost 0.",
        "- **Quality proxy**: computed from answer length, query-term overlap, "
        "citation coverage, traceability, role separation, completion, and penalties "
        "for errors/fallbacks.",
        "- **Citation coverage**: number of source IDs referenced in the final answer "
        "divided by the number of retrieved sources.",
        "- **Failure rate**: recorded workflow errors divided by supervisor iterations.",
        "- **API calls**: successful OpenAI calls recorded by the run state. A benchmark "
        "suite has 6 runs by default, but multi-agent runs can make multiple API calls "
        "because each agent is a separate step.",
        "",
        "| Run | Latency (s) | Cost (USD) | API calls | Input tokens | Output tokens | "
        "Quality proxy | Words | Cited sources | Citation refs | Failure rate | Trace "
        "events | Agents | Fallback | Notes |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---|",
    ]
    for item in metrics:
        cost = _format_cost(item.estimated_cost_usd)
        quality = "" if item.quality_score is None else f"{item.quality_score:.2f}"
        failure_rate = "" if item.failure_rate is None else f"{item.failure_rate:.0%}"
        fallback = "yes" if item.fallback_used else "no"
        lines.append(
            "| "
            f"{_escape(item.run_name)} | "
            f"{item.latency_seconds:.4f} | "
            f"{cost} | "
            f"{item.api_call_count} | "
            f"{item.input_tokens} | "
            f"{item.output_tokens} | "
            f"{quality} | "
            f"{item.answer_word_count} | "
            f"{item.cited_source_count}/{item.source_count} | "
            f"{item.citation_reference_count} | "
            f"{failure_rate} | "
            f"{item.trace_events} | "
            f"{item.distinct_agent_count} | "
            f"{fallback} | "
            f"{_escape(item.notes)} |"
        )

    lines.extend(["", "## Automatic Analysis", "", *_analysis_lines(metrics)])
    lines.extend(["", "## Failure Modes and Fixes", "", *_failure_mode_lines(metrics)])
    return "\n".join(lines) + "\n"


def _analysis_lines(metrics: list[BenchmarkMetrics]) -> list[str]:
    if not metrics:
        return ["- No benchmark runs were provided."]

    baseline = [metric for metric in metrics if metric.run_name.startswith("baseline")]
    multi = [metric for metric in metrics if metric.run_name.startswith("multi_agent")]
    lines: list[str] = []
    if baseline:
        lines.append(
            "- Baseline averages: "
            f"quality proxy {_avg_quality(baseline):.2f}, "
            f"latency {_avg_latency(baseline):.4f}s, "
            f"answer length {_avg_words(baseline):.0f} words, "
            f"trace events {_avg_trace_events(baseline):.1f}, "
            f"API calls {_avg_api_calls(baseline):.1f}."
        )
    if multi:
        lines.append(
            "- Multi-agent averages: "
            f"quality proxy {_avg_quality(multi):.2f}, "
            f"latency {_avg_latency(multi):.4f}s, "
            f"answer length {_avg_words(multi):.0f} words, "
            f"trace events {_avg_trace_events(multi):.1f}, "
            f"API calls {_avg_api_calls(multi):.1f}."
        )
    if baseline and multi:
        quality_delta = _avg_quality(multi) - _avg_quality(baseline)
        latency_delta = _avg_latency(multi) - _avg_latency(baseline)
        trace_delta = _avg_trace_events(multi) - _avg_trace_events(baseline)
        api_delta = _avg_api_calls(multi) - _avg_api_calls(baseline)
        lines.append(
            "- Multi-agent minus baseline: "
            f"quality proxy {quality_delta:+.2f}, "
            f"latency {latency_delta:+.4f}s, "
            f"trace events {trace_delta:+.1f}, "
            f"API calls {api_delta:+.1f}."
        )
    total_errors = sum(metric.error_count for metric in metrics)
    fallback_runs = sum(1 for metric in metrics if metric.fallback_used)
    lines.append(f"- Total recorded workflow errors across runs: {total_errors}.")
    lines.append(f"- Runs using fallback behavior: {fallback_runs}/{len(metrics)}.")
    lines.append(
        "- Recommended interpretation: use the multi-agent workflow when traceability, "
        "role separation, validation, and guardrail evidence matter more than the small "
        "local orchestration overhead. Use the baseline when a short one-pass answer is enough."
    )
    return lines


def _failure_mode_lines(metrics: list[BenchmarkMetrics]) -> list[str]:
    """Generate the required failure-mode explanation from benchmark outputs.

    The section only uses information available in ``BenchmarkMetrics`` so the
    generated report stays tied to the actual benchmark run instead of a manually
    written story.
    """

    if not metrics:
        command = (
            "python -m multi_agent_research_lab.cli benchmark "
            "--config configs/lab_default.yaml --reports-dir reports"
        )
        return [
            "- No benchmark runs were provided, so no run-specific failure mode can be "
            f"diagnosed yet. Fix: run `{command}` and inspect the regenerated report "
            "and traces."
        ]

    lines = [
        "The points below are generated from the benchmark metrics and trace summaries "
        "for this run.",
        "",
    ]

    failing_runs = [metric for metric in metrics if metric.error_count > 0]
    fallback_runs = [metric for metric in metrics if metric.fallback_used]
    zero_api_runs = [metric for metric in metrics if metric.api_call_count == 0]

    lines.append(_error_failure_line(failing_runs))
    lines.append(_fallback_failure_line(fallback_runs, len(metrics)))
    lines.append(_api_failure_line(zero_api_runs, metrics))

    baseline = [metric for metric in metrics if metric.run_name.startswith("baseline")]
    multi = [metric for metric in metrics if metric.run_name.startswith("multi_agent")]
    if baseline and multi:
        latency_delta = _avg_latency(multi) - _avg_latency(baseline)
        api_delta = _avg_api_calls(multi) - _avg_api_calls(baseline)
        if latency_delta > 0 or api_delta > 0:
            lines.append(
                "- **Multi-agent overhead**: multi-agent runs averaged "
                f"{latency_delta:+.4f}s latency and {api_delta:+.1f} API calls compared "
                "with baseline. **Fix/decision**: use the baseline for short low-risk "
                "questions; use the multi-agent workflow when the extra traceability, role "
                "separation, and critic validation justify the overhead."
            )

    lines.append(
        "- **General fix process**: regenerate the benchmark after any change, compare "
        "`reports/benchmark_report.md` with the matching trace JSON files, and only "
        "treat a fix as successful when errors, fallback status, API calls, and "
        "final-answer quality proxy improve or remain acceptable."
    )
    return lines


def _error_failure_line(failing_runs: list[BenchmarkMetrics]) -> str:
    if failing_runs:
        run_names = ", ".join(metric.run_name for metric in failing_runs)
        total_errors = sum(metric.error_count for metric in failing_runs)
        return (
            f"- **Recorded agent/workflow errors**: {total_errors} error(s) appeared in "
            f"{len(failing_runs)} run(s): {run_names}. **Fix**: open the matching "
            "`reports/traces/run_XX.json` files, inspect the recorded `errors` and "
            "failed agent span, then keep the existing retry/fallback path while "
            "correcting the provider, prompt, or agent code that produced the error."
        )
    return (
        "- **Recorded agent/workflow errors**: none were recorded in this benchmark run. "
        "**Fix if this changes**: inspect the matching trace JSON, then use the existing "
        "retry, timeout, and fallback events to identify which agent failed."
    )


def _fallback_failure_line(fallback_runs: list[BenchmarkMetrics], total_runs: int) -> str:
    if fallback_runs:
        run_names = ", ".join(metric.run_name for metric in fallback_runs)
        return (
            f"- **Fallback behavior**: fallback was used in {len(fallback_runs)}/"
            f"{total_runs} run(s): {run_names}. **Fix**: check `.env` values such as "
            "`OPENAI_API_KEY`, `LLM_PROVIDER`, `OPENAI_MODEL`, `OPENAI_SEARCH_MODEL`, "
            "and `OPENAI_SEARCH_MODE`; confirm the OpenAI package is installed with "
            "`pip install -e \".[dev,llm]\"`; then rerun the benchmark to verify "
            "fallback usage returns to `no`."
        )
    return (
        f"- **Fallback behavior**: fallback was not used in any of the {total_runs} "
        "benchmark run(s). **Fix if this changes**: verify the OpenAI configuration and "
        "package installation, then inspect the source metadata in the trace for the "
        "recorded fallback reason."
    )


def _api_failure_line(
    zero_api_runs: list[BenchmarkMetrics],
    metrics: list[BenchmarkMetrics],
) -> str:
    if zero_api_runs:
        run_names = ", ".join(metric.run_name for metric in zero_api_runs)
        return (
            f"- **OpenAI API execution**: {len(zero_api_runs)} run(s) recorded zero "
            f"API calls: {run_names}. **Fix**: run "
            "`python -m multi_agent_research_lab.cli openai-check`, confirm it reports "
            "`fallback_used: False`, and make sure the benchmark is executed in the "
            "same activated environment."
        )
    total_api_calls = sum(metric.api_call_count for metric in metrics)
    return (
        "- **OpenAI API execution**: all benchmark runs recorded OpenAI API calls "
        f"({total_api_calls} total). **Fix if usage is still missing on the "
        "dashboard**: check the OpenAI project/organization and date filters, then "
        "compare the dashboard with the API-call and token counts in this report."
    )


def _avg_quality(metrics: list[BenchmarkMetrics]) -> float:
    values = [metric.quality_score or 0.0 for metric in metrics]
    return mean(values) if values else 0.0


def _avg_latency(metrics: list[BenchmarkMetrics]) -> float:
    values = [metric.latency_seconds for metric in metrics]
    return mean(values) if values else 0.0


def _avg_words(metrics: list[BenchmarkMetrics]) -> float:
    values = [metric.answer_word_count for metric in metrics]
    return mean(values) if values else 0.0


def _avg_trace_events(metrics: list[BenchmarkMetrics]) -> float:
    values = [metric.trace_events for metric in metrics]
    return mean(values) if values else 0.0


def _avg_api_calls(metrics: list[BenchmarkMetrics]) -> float:
    values = [metric.api_call_count for metric in metrics]
    return mean(values) if values else 0.0


def _format_cost(value: float | None) -> str:
    if value is None:
        return ""
    if value == 0:
        return "0.0000"
    if abs(value) < 0.0001:
        return f"{value:.8f}"
    return f"{value:.4f}"


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
