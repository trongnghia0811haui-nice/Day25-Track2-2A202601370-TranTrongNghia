# NimbusAI — GPU Cost Optimization Report

**Period:** monthly  
**Baseline spend:** $21,125  
**Optimized spend:** $11,968  
**Projected savings:** $9,157  (**43%**)

## Savings by lever

| Lever | Savings (USD) |
|---|---|
| Inference (cascade/cache/batch) | $1,212 |
| Purchasing (spot/reserved) | $6,690 |
| Right-size util-lies | $655 |
| Kill idle GPUs | $600 |

## Cost model scope

The M1 right-size and idle levers are costed only for the affected GPU-hour scope observed in telemetry. This keeps those opportunities traceable and prevents double-counting them against the M2/M3 baseline.

## Sustainability

- Energy per query: 0.24 Wh
- Carbon per query: 0.091 gCO2e
- Cleanest region (carbon): europe-north1
- Cheapest region (electricity): us-east-wa
- Balanced region (normalized cost + carbon): europe-north1

_Figures are June-2026 as-of snapshots; re-baseline before acting._

## Inference Unit Economics

These unit metrics cover M2 inference traffic (the spend is daily); the headline M5 spend remains monthly GPU rental cost.

| Metric | Baseline | Optimized |
|---|---:|---:|
| Requests | 2,400 | 2,400 |
| Tokens served | 7,533,027 | 7,533,027 |
| Inference cost / day | $48.87 | $8.48 |
| $/1M-token | $6.488 | $1.126 |

### Sequential lever breakdown

Order is baseline → cascade → cache → batch; contributions are incremental and therefore sum without double-counting.

| Stage | Inference cost / day | Incremental savings / day | % of baseline |
|---|---:|---:|---:|
| Baseline | $48.87 | $0.00 | 0.0% |
| After cascade | $11.48 | $37.40 | 76.5% |
| After cache | $10.28 | $1.20 | 2.4% |
| After batch (optimized) | $8.48 | $1.79 | 3.7% |


## Reasoning Budget

- Reasoning traffic: 201 requests (8.4% of traffic).
- Optimized reasoning cost: $1.40 (16.5% of optimized inference cost).
- Reasoning energy: 29,787.74 Wh (94.0% of inference energy).
- Reasoning premium vs non-reasoning counterfactual: $1.03 and 29,610.14 Wh.
- Routing rule: cap reasoning at 5%, preserve the highest-output requests and downgrade 81 lowest-output excess requests; estimated savings $0.23 and 7,870.22 Wh.
- Assumption: the synthetic generator's 6× reasoning output-token tax is used for the non-reasoning counterfactual.

## Carbon-aware Scheduling

**Scope:** interruptible training jobs.
**Baseline region:** us-east-1
**Cheapest electricity:** us-east-wa; **cleanest carbon:** europe-north1; **balanced:** europe-north1

Balanced minimizes the equal-weight score `(USD/kWh ÷ minimum USD/kWh) + (gCO2e/kWh ÷ minimum gCO2e/kWh)`.
Electricity/carbon deltas are reported separately from GPU rental spend and are not added to the headline M3 purchasing savings.
Moving checkpoints to another region can increase latency or conflict with data-residency requirements; validate transfer time, SLA and residency controls before scheduling.

### Regional comparison

| Region | USD/kWh | gCO2e/kWh | Electricity (USD) | Carbon (gCO2e) | Balanced score |
|---|---:|---:|---:|---:|---:|
| europe-central2 | $0.1800 | 660 | $301.18 | 1,104,312.00 | 25.27 |
| europe-north1 | $0.0900 | 30 | $150.59 | 50,196.00 | 2.64 |
| us-east-1 | $0.1200 | 380 | $200.78 | 635,816.00 | 14.85 |
| us-east-wa | $0.0550 | 90 | $92.03 | 150,588.00 | 4.00 |
| us-west-2 | $0.0700 | 120 | $117.12 | 200,784.00 | 5.27 |

### Per-job savings

| Job | GPU-hours | Energy (kWh) | Baseline carbon (g) | Cleanest carbon (g) | Carbon saved (g) | Baseline electricity ($) | Cheapest electricity ($) | Cost saved ($) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| job-train-llm | 2,240.00 | 1,568.00 | 595,840.00 | 47,040.00 | 548,800.00 | $188.16 | $86.24 | $101.92 |
| job-train-embed | 200.00 | 80.00 | 30,400.00 | 2,400.00 | 28,000.00 | $9.60 | $4.40 | $5.20 |
| job-finetune | 36.00 | 25.20 | 9,576.00 | 756.00 | 8,820.00 | $3.02 | $1.39 | $1.64 |

### Scheduling totals

- Energy: 1,673.20 kWh across 3 jobs (2,476.00 GPU-hours).
- Cheapest-electricity option (us-east-wa): save $108.76 (54.2%) vs us-east-1.
- Cleanest-carbon option (europe-north1): save 585,620.00 gCO2e (92.1%).
- Balanced option (europe-north1): $150.59 electricity and 50,196.00 gCO2e for this scope.

## Recommended Actions

1. **Start with Purchasing (spot/reserved):** it contributes $6,690 of the modeled monthly savings; validate its operational guardrails before rollout.
2. **Fix util-lies:** `gpu-h100-4` (98.2% GPU-Util, MFU 0.194), `gpu-a10g-1` (96.9% GPU-Util, MFU 0.268). GPU-Util measures an active clock, not useful FLOPs; memory stalls, I/O or launch overhead can keep MFU low. The observed idle opportunity is $600/month.
3. **Protect service quality:** keep checkpoint/retry controls for spot, preserve latency-sensitive requests on the appropriate route, and validate cache correctness, batch SLOs, region latency and data residency before enforcing policy.