# Lab Guide: Multi-Agent Research System

## Scenario

This lab builds a small research assistant that accepts a query, gathers evidence, analyzes it, writes a final answer, and records enough trace information to explain what happened. The implementation compares two approaches:

1. **Single-agent baseline**: one path performs search, synthesis, and answer writing.
2. **Multi-agent workflow**: a Supervisor coordinates Researcher, Analyst, Writer, and Critic roles.

## Rules used by this implementation

- Each agent has one clear responsibility.
- Shared state is the single handoff object between agents.
- The workflow records trace events for routing, agent runs, fallback paths, and completion.
- Benchmarking is generated automatically from actual run outputs and traces.
- Guardrails are included for max iterations, timeout, retry, fallback, and validation.

## Milestone 1: Baseline

Implemented in:

- `src/multi_agent_research_lab/cli.py`
- `src/multi_agent_research_lab/services/llm_client.py`
- `src/multi_agent_research_lab/services/search_client.py`

The baseline command uses the same local search and deterministic synthesis components as the multi-agent workflow, but it performs the work in one pass. This provides a simple comparison point for latency, trace volume, answer length, and citation behavior.

## Milestone 2: Supervisor

Implemented in:

- `src/multi_agent_research_lab/agents/supervisor.py`
- `src/multi_agent_research_lab/graph/workflow.py`

Routing policy:

```text
researcher -> analyst -> writer -> critic -> done
```

The Supervisor checks state fields to decide the next route. It also respects the configured max-iteration limit and routes to Writer before stopping if no final answer exists.

## Milestone 3: Worker agents

Implemented in:

- `src/multi_agent_research_lab/agents/researcher.py`
- `src/multi_agent_research_lab/agents/analyst.py`
- `src/multi_agent_research_lab/agents/writer.py`
- `src/multi_agent_research_lab/agents/critic.py`

Agent responsibilities:

- **Researcher** retrieves local/mock sources and writes source-indexed research notes.
- **Analyst** turns research notes into synthesis guidance, evidence, risks, and limitations.
- **Writer** produces a final answer with source IDs and explicit limitations.
- **Critic** validates final-answer presence, citation coverage, and workflow errors.

## Milestone 4: Trace and benchmark

Implemented in:

- `src/multi_agent_research_lab/observability/tracing.py`
- `src/multi_agent_research_lab/evaluation/benchmark.py`
- `src/multi_agent_research_lab/evaluation/report.py`
- `src/multi_agent_research_lab/services/storage.py`

The benchmark command creates:

```text
reports/benchmark_report.md
reports/traces/run_01.json
reports/traces/run_02.json
...
```

## Benchmark metrics

Metrics are generated from the produced state and output:

| Metric            | How it is generated                                                                                                                                                 |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Latency           | Wall-clock runtime measured by `perf_counter`.                                                                                                                      |
| Cost              | Sum of provider metadata. Local fallback runs report `0.0000`.                                                                                                      |
| Quality proxy     | Output-derived heuristic using answer length, query-term overlap, citation coverage, traceability, role separation, completion, and penalties for errors/fallbacks. |
| Citation coverage | Source IDs referenced in the final answer divided by retrieved source count.                                                                                        |
| Failure rate      | Recorded errors divided by supervisor iterations.                                                                                                                   |
| Trace events      | Number of JSON trace records in the run state.                                                                                                                      |
| Fallback used     | Derived from fallback source metadata or fallback text in the final answer.                                                                                         |

These numbers are intentionally lightweight for a two-hour lab. They are useful for comparing runs and inspecting behavior, but they are not a production-grade evaluation or human quality score.

## Exit ticket answers

1. Use multi-agent when traceability, role separation, validation, and guardrail evidence matter.
2. Avoid multi-agent when the task is short, low risk, and a simple one-pass answer is enough.
