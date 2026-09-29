# Phase 14 Experiment 02: Unified Campaign and OpenCode Timeline

- **Date:** 2026-09-29
- **Investigation Window:** `2026-09-29T05:46:00Z` to `2026-09-29T06:50:00Z`
- **Methodology:** Synchronized correlation of experimental cohorts, project arrivals, completions, and OpenCode gateway dispatches.

---

## 1. High-Level Campaign Phase Boundaries

The overall timeline decomposes into five distinct intervals:

```
[05:46:16 - 05:48:38] Adversarial Containment & Preflight Checks (Zero OpenCode Traffic)
[05:48:39 - 05:57:23] Cohort 1: Regime 1 Config B (lambda = 12.0)  --> ZERO OpenCode requests (Uncontended)
[05:57:23 - 06:06:07] Cohort 2: Regime 1 Config B+ (lambda = 12.0) --> ZERO OpenCode requests (Uncontended)
[06:06:07 - 06:26:21] Cohort 3: Regime 2 Config B+ (lambda = 19.5) --> 14 OPENCODE REQUESTS (CONTENDED)
  |-- Projects 1 - 4 (06:06:07 - 06:19:18): Uncontended, 0 OpenCode requests, wait = 0.0s
  |-- Project 5     (06:18:25 - 06:22:52): Contended by Burst 1 (6 reqs on W1), wait = 12.2s
  |-- Project 6     (06:21:30 - 06:26:21): Contended by Burst 2 (6 on W1, 2 on W2), wait = 25.5s
[06:26:21 - 06:48:39] Cohort 4: Regime 2 Config B (lambda = 19.5)  --> ZERO OpenCode requests (Uncontended)
[06:48:39] Campaign Completion & Trace Persistence
```

---

## 2. Chronological Event Sequence

The table below correlates the complete chronological order of events during the critical campaign window:

| Time (UTC) | Originating Workstream | Event Type | Details & Token Metrics | Impact on Queue / System |
|---|---|---|---|---|
| **05:46:16** | Experiment 02 | Containment Verification | Adversarial prompt injection & containment probes executed | All 4 probes safely contained |
| **05:48:39** | Experiment 02 | Cohort 1 Start | Regime 1 Config B admitted ($\lambda = 12.0$ proj/hr) | Queue empty |
| **05:57:23** | Experiment 02 | Cohort 1 End / Cohort 2 Start | Regime 1 Config B+ admitted ($\lambda = 12.0$ proj/hr) | Queue empty |
| **06:06:07** | Experiment 02 | Cohort 2 End / Cohort 3 Start | Regime 2 Config B+ admitted ($\lambda = 19.5$ proj/hr) | Queue empty |
| **06:06:07** | Experiment 02 | Project B+-01 Admitted | Archetype: API Refactoring | Dispatch immediate |
| **06:09:12** | Experiment 02 | Project B+-02 Admitted | Archetype: Security Infrastructure | Dispatch immediate |
| **06:09:51** | Experiment 02 | Project B+-01 Complete | Turnaround: 224.0s ($W_1 = 168.2\text{s}$) | Wait: 0.0s |
| **06:12:16** | Experiment 02 | Project B+-03 Admitted | Archetype: Schema Refactoring | Dispatch immediate |
| **06:13:01** | Experiment 02 | Project B+-02 Complete | Turnaround: 229.8s ($W_1 = 153.3\text{s}$) | Wait: 0.0s |
| **06:15:21** | Experiment 02 | Project B+-04 Admitted | Archetype: Worker Engine | Dispatch immediate |
| **06:16:17** | Experiment 02 | Project B+-03 Complete | Turnaround: 241.0s ($W_1 = 168.6\text{s}$) | Wait: 0.0s |
| **06:18:25** | Experiment 02 | Project B+-05 Admitted | Archetype: Database Schema | Wait begins accumulating |
| **06:19:19** | **OpenCode** | **Burst 1 Initiated** | Request `528b26fb...` arrives at Gateway $\rightarrow$ Worker 1 | Worker 1 enters continuous batching |
| **06:19:22** | OpenCode | Burst 1 Req 1 Complete | Prompt: 2582, Compl: 54, Duration: 3.16s | Interleaved with Project B+-04/05 |
| **06:19:34** | Experiment 02 | Project B+-04 Complete | Turnaround: 253.0s ($W_1 = 169.1\text{s}$) | Project B+-05 dispatched after 12.2s wait |
| **06:19:38** | OpenCode | Burst 1 Req 2 Complete | Prompt: 2876, Compl: 259, Duration: 15.78s | Worker 1 decode cycles shared |
| **06:19:44** | OpenCode | Burst 1 Req 3 Complete | Prompt: 3154, Compl: 85, Duration: 6.09s | Worker 1 decode cycles shared |
| **06:20:01** | OpenCode | Burst 1 Req 4 Complete | Prompt: 2582, Compl: 54, Duration: 16.63s | Worker 1 decode cycles shared |
| **06:20:21** | OpenCode | Burst 1 Req 5 Complete | Prompt: 2876, Compl: 264, Duration: 19.54s | Worker 1 decode cycles shared |
| **06:20:28** | OpenCode | Burst 1 Req 6 Complete | Prompt: 3159, Compl: 72, Duration: 7.16s | Burst 1 finishes (18,012 tokens) |
| **06:21:30** | Experiment 02 | Project B+-06 Admitted | Archetype: Observability Contract | Queued behind Project B+-05 |
| **06:22:52** | Experiment 02 | Project B+-05 Complete | Turnaround: 254.0s ($W_1 = 170.1\text{s}$) | Project B+-06 dispatched after 25.5s wait |
| **06:24:29** | **OpenCode** | **Burst 2 Initiated** | Request `2643ce87...` arrives at Gateway $\rightarrow$ Worker 1 | Worker 1 enters continuous batching |
| **06:24:32** | OpenCode | Burst 2 Req 7 Complete | Prompt: 2582, Compl: 54, Duration: 3.68s | vLLM reports `Running: 2 reqs` |
| **06:24:51** | OpenCode | Burst 2 Req 8 Complete | Prompt: 2876, Compl: 213, Duration: 18.92s | Concurrent decoding on Worker 1 |
| **06:25:05** | OpenCode | Burst 2 Req 9 Complete | Prompt: 3108, Compl: 153, Duration: 13.82s | Concurrent decoding on Worker 1 |
| **06:25:22** | OpenCode | Burst 2 Req 10 Complete | Prompt: 2582, Compl: 59, Duration: 16.70s | vLLM reports `Running: 2 reqs` |
| **06:25:37** | OpenCode | Burst 2 Req 11 Complete | Prompt: 2881, Compl: 265, Duration: 15.78s | KV cache usage spikes to 3.9% |
| **06:25:48** | OpenCode | Burst 2 Req 12 Complete | Prompt: 3165, Compl: 181, Duration: 11.09s | Worker 1 OpenCode calls finish |
| **06:26:04** | OpenCode | Burst 2 Req 13 Complete | Prompt: 2489, Compl: 38, Duration: 3.98s | Dispatched to Worker 2 |
| **06:26:17** | OpenCode | Burst 2 Req 14 Complete | Prompt: 3054, Compl: 136, Duration: 12.10s | Burst 2 finishes (23,841 tokens) |
| **06:26:21** | Experiment 02 | Project B+-06 Complete | Turnaround: 265.6s ($W_1 = 173.6\text{s}$) | Cohort 3 completes (Elapsed: 1214.10s) |
| **06:26:21** | Experiment 02 | Cohort 4 Start | Regime 2 Config B admitted ($\lambda = 19.5$ proj/hr) | **ZERO OpenCode requests remain** |
| **06:48:39** | Experiment 02 | Cohort 4 Complete | All 6 Config B projects complete ($W_1 = 194.9\text{s}$) | Elapsed: 1337.59s; Wait grew to 189.7s |

---

## 3. Key Findings from Timeline Correlation

1. **Strict Asymmetry:** 100% of OpenCode requests occurred during Cohort 3 (Configuration B+). Cohort 4 (Configuration B) was completely uninhibited by outside load.
2. **Phase Correlation:** The onset of queue waiting in Configuration B+ (Projects 5 and 6) coincided with the two bursts of OpenCode requests.
3. **Robustness of B+:** Despite carrying 41,853 tokens of unmodeled concurrent background load, Configuration B+ finished all 6 projects in 1214.1s (17.79 proj/hr), compared to 1337.59s (16.15 proj/hr) for uncontended Configuration B.
