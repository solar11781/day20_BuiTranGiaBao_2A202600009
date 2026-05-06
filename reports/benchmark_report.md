# Benchmark Report

This report is generated automatically by the lab CLI from each run's produced 
answer, trace, sources, metadata, and recorded errors.

## Metric definitions

- **Latency**: measured wall-clock runtime for the command path.
- **Cost**: sum of available token/tool cost estimates from run metadata. It is blank when no reliable price is available; local fallback runs cost 0.
- **Quality proxy**: computed from answer length, query-term overlap, citation coverage, traceability, role separation, completion, and penalties for errors/fallbacks.
- **Citation coverage**: number of source IDs referenced in the final answer divided by the number of retrieved sources.
- **Failure rate**: recorded workflow errors divided by supervisor iterations.
- **API calls**: successful OpenAI calls recorded by the run state. A benchmark suite has 6 runs by default, but multi-agent runs can make multiple API calls because each agent is a separate step.

| Run | Latency (s) | Cost (USD) | API calls | Input tokens | Output tokens | Quality proxy | Words | Cited sources | Citation refs | Failure rate | Trace events | Agents | Fallback | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---|
| baseline_q1 | 13.0893 | 0.0004 | 2 | 373 | 817 | 6.45 | 411 | 1/1 | 2 | 0% | 1 | 1 | no | answer_words=411; citation_refs=2; agents=1; api_calls=2 |
| multi_agent_q1 | 24.9568 | 0.0011 | 3 | 1993 | 2173 | 7.67 | 569 | 1/1 | 5 | 0% | 19 | 4 | no | answer_words=569; citation_refs=5; agents=4; api_calls=3 |
| baseline_q2 | 9.4583 | 0.0003 | 2 | 387 | 542 | 6.10 | 247 | 1/1 | 2 | 0% | 1 | 1 | no | answer_words=247; citation_refs=2; agents=1; api_calls=2 |
| multi_agent_q2 | 31.3900 | 0.0009 | 3 | 1973 | 1789 | 7.89 | 518 | 1/1 | 13 | 0% | 19 | 4 | no | answer_words=518; citation_refs=13; agents=4; api_calls=3 |
| baseline_q3 | 8.4562 | 0.0002 | 2 | 375 | 381 | 5.92 | 221 | 1/1 | 1 | 0% | 1 | 1 | no | answer_words=221; citation_refs=1; agents=1; api_calls=2 |
| multi_agent_q3 | 22.6776 | 0.0008 | 3 | 2003 | 1554 | 7.80 | 333 | 1/1 | 3 | 0% | 19 | 4 | no | answer_words=333; citation_refs=3; agents=4; api_calls=3 |

## Automatic Analysis

- Baseline averages: quality proxy 6.16, latency 10.3346s, answer length 293 words, trace events 1.0, API calls 2.0.
- Multi-agent averages: quality proxy 7.79, latency 26.3415s, answer length 473 words, trace events 19.0, API calls 3.0.
- Multi-agent minus baseline: quality proxy +1.63, latency +16.0069s, trace events +18.0, API calls +1.0.
- Total recorded workflow errors across runs: 0.
- Runs using fallback behavior: 0/6.
- Recommended interpretation: use the multi-agent workflow when traceability, role separation, validation, and guardrail evidence matter more than the small local orchestration overhead. Use the baseline when a short one-pass answer is enough.

## Failure Modes and Fixes

The points below are generated from the benchmark metrics and trace summaries for this run.

- **Recorded agent/workflow errors**: none were recorded in this benchmark run. **Fix if this changes**: inspect the matching trace JSON, then use the existing retry, timeout, and fallback events to identify which agent failed.
- **Fallback behavior**: fallback was not used in any of the 6 benchmark run(s). **Fix if this changes**: verify the OpenAI configuration and package installation, then inspect the source metadata in the trace for the recorded fallback reason.
- **OpenAI API execution**: all benchmark runs recorded OpenAI API calls (15 total). **Fix if usage is still missing on the dashboard**: check the OpenAI project/organization and date filters, then compare the dashboard with the API-call and token counts in this report.
- **Multi-agent overhead**: multi-agent runs averaged +16.0069s latency and +1.0 API calls compared with baseline. **Fix/decision**: use the baseline for short low-risk questions; use the multi-agent workflow when the extra traceability, role separation, and critic validation justify the overhead.
- **General fix process**: regenerate the benchmark after any change, compare `reports/benchmark_report.md` with the matching trace JSON files, and only treat a fix as successful when errors, fallback status, API calls, and final-answer quality proxy improve or remain acceptable.
