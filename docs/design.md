# Design: Multi-Agent Research Lab

## Problem

Build a lab-scale research assistant that accepts a query, gathers local/mock evidence,
analyses that evidence, writes a final answer, records a trace, and benchmarks the
single-agent baseline against the multi-agent workflow.

## Why multi-agent?

To practise role separation, shared state handoff, traceability,
and guardrails. A single-agent baseline is included for comparison, but the multi-agent
workflow makes it easier to inspect who gathered sources, who analysed them, who wrote
the answer, and where a failure happened.

## Agent roles

| Agent      | Responsibility                                                      | Input                                        | Output                                                         | Failure mode                                                           |
| ---------- | ------------------------------------------------------------------- | -------------------------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Supervisor | Route the next step and enforce max-iteration stop logic.           | Shared `ResearchState`.                      | Route: `researcher`, `analyst`, `writer`, `critic`, or `done`. | Falls back to `done` on invalid route and records an error.            |
| Researcher | Retrieve local/mock sources and write source-indexed notes.         | Query and `max_sources`.                     | `sources`, `research_notes`.                                   | Uses fallback source that explicitly discloses missing evidence.       |
| Analyst    | Convert sources into evidence, risks, and synthesis guidance.       | `sources`, `research_notes`.                 | `analysis_notes`.                                              | Records missing research and writes limited-evidence analysis.         |
| Writer     | Produce final answer with source references and limitations.        | Query, sources, research and analysis notes. | `final_answer`.                                                | Uses guarded fallback answer when analysis is missing or retries fail. |
| Critic     | Bonus validation of answer presence, citation coverage, and errors. | Final state.                                 | `critic_review`, `citation_coverage`.                          | Records unavailable review if critic fallback is needed.               |

## Shared state

- `request`: original query, audience, and source limit.
- `iteration` and `route_history`: routing trace and max-iteration guard.
- `sources`: local/mock search results or explicit fallback source.
- `research_notes`, `analysis_notes`, `final_answer`: agent handoff artifacts.
- `agent_results`: structured outputs with metadata.
- `trace`: JSON-friendly span and event history.
- `errors`: recorded failures for benchmark failure-rate metrics.
- `metadata`: completion flag, critic review, citation coverage.

## Routing policy

```text
start
  -> supervisor
  -> researcher if research_notes missing
  -> analyst if analysis_notes missing
  -> writer if final_answer missing
  -> critic if critic_review missing
  -> done
```

The Supervisor checks `MAX_ITERATIONS`. If the limit is reached before an answer exists,
it routes to Writer so the workflow can produce a guarded fallback instead of failing
silently.

## Guardrails

- Max iterations: from `MAX_ITERATIONS` / `Settings.max_iterations`, default 6.
- Timeout: workflow checks elapsed wall-clock time before each routed step.
- Retry: each worker agent gets two attempts.
- Fallback: each role has a role-specific fallback path.
- Validation: Critic checks final-answer presence, citation coverage, and errors.

## Benchmark plan

The `benchmark` CLI command runs each configured query through both systems:

1. Single-agent baseline.
2. Multi-agent workflow.

Metrics are generated automatically:

- Latency.
- Estimated cost.
- Heuristic quality score.
- Citation coverage.
- Failure rate.
- Trace event count.
- Source count.
