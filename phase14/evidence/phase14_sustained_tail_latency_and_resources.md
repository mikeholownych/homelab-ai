# Phase 14 Experiment 02: Tail Latency and Resource Accounting

## 1. End-to-End Latency & Queue Wait Distributions

End-to-end latency ($T_{\text{e2e}} = W_q + T_{\text{turnaround}}$) reflects the full elapsed time from project arrival to acceptance:

### Regime 2 (19.5 proj/hr Capacity Boundary Cohort)

| Latency Dimension | Configuration B (Control) | Configuration B+ (Candidate) | Difference ($\Delta$) |
|---|---|---|---|
| **Mean Queue Wait (W_q)** | 93.68s | 6.29s | **-87.39s** |
| **P50 Queue Wait** | 91.43s | 0.01s | -91.42s |
| **P95 Queue Wait** | 179.85s | 22.15s | **-157.70s** |
| **Mean End-to-End Latency (T_e2e)** | 316.61s | 250.86s | **-65.75s** |
| **P50 End-to-End Latency** | 315.40s | 247.03s | -68.37s |
| **P95 End-to-End Latency** | 404.45s | 284.83s | **-119.62s** |

## 2. Worker Utilization and Idle Accounting

- **Worker 1 Active Service Demand (Cohort Total)**: 1166.5s (B) vs. 1002.8s (B+) -> **172.3s compute time freed on Lead Worker 1**.
- **Worker 2 Active Service Demand (Cohort Total)**: 412.1s (B) vs. 589.7s (B+) -> Productive utilization of idle GPU 1 capacity.
- **Worker 1 Utilization (U1)**: 87.2% (B) vs. 82.6% (B+).
- **Worker 2 Utilization (U2)**: 30.8% (B) vs. 48.6% (B+).

## 3. Host and Thermal Telemetry

- **Chassis Thermals**: GPU 0 maintained peak temperature 61°C; GPU 1 maintained peak temperature 58°C throughout multi-project execution.
- **Memory Footprint**: Peak host RAM usage remained < 16 GiB out of 64 GiB ECC; swap usage was 0.0 MB.
- **Zero Throttling**: Zero thermal throttling, PCIe bus saturation, or kernel drops were detected.
