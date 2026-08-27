"""M5 — Optimization Report: combine M1-M4 into baseline-vs-optimized (deck §1/§11).

Run: python missions/m5_report.py   ->  outputs/report.md + outputs/savings.png
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
from missions._common import num, catalog_by_type, ROOT
from finops import report, sustainability
from missions import m1_efficiency_audit, m2_inference_levers, m3_purchasing

DAYS = 30
# one tier down for over-provisioned ("util-lie") GPUs
RIGHTSIZE_MAP = {"H100": "A100", "H200": "H100", "A100": "A10G", "A10G": "L4", "L4": "L4"}


def run(verbose: bool = True) -> dict:
    r1 = m1_efficiency_audit.run(verbose=False)
    r2 = m2_inference_levers.run(verbose=False)
    r3 = m3_purchasing.run(verbose=False)
    cat = catalog_by_type()

    # --- buckets ---
    infer_savings = (r2["baseline_daily"] - r2["optimized_daily"]) * DAYS
    purchasing_savings = r3["on_demand_monthly"] - r3["optimized_monthly"]

    # Keep M1 opportunity savings inside an explicit affected-resource scope.
    # This prevents subtracting telemetry opportunities from an unrelated
    # baseline and prevents idle/right-size savings from overlapping.
    lie_ids = {lie["gpu_id"] for lie in r1["lies"]}
    efficiency_baseline = 0.0
    idle_savings = 0.0
    rightsize_savings = 0.0
    for summary in r1["summary"]:
        gtype = summary["gpu_type"]
        current_hr = num(cat[gtype]["on_demand_hr"])
        if summary["gpu_id"] in lie_ids:
            target_type = RIGHTSIZE_MAP.get(gtype, gtype)
            target_hr = num(cat[target_type]["on_demand_hr"])
            current_cost = current_hr * 24 * DAYS
            target_cost = min(current_cost, target_hr * 24 * DAYS)
            efficiency_baseline += current_cost
            rightsize_savings += current_cost - target_cost
        elif summary["idle_hours"] > 0:
            idle_cost = summary["idle_hours"] * current_hr * DAYS
            efficiency_baseline += idle_cost
            idle_savings += idle_cost
    efficiency_optimized = efficiency_baseline - idle_savings - rightsize_savings

    levers = {
        "Inference (cascade/cache/batch)": round(infer_savings),
        "Purchasing (spot/reserved)": round(purchasing_savings),
        "Right-size util-lies": round(rightsize_savings),
        "Kill idle GPUs": round(idle_savings),
    }
    baseline_components = {
        "inference": r2["baseline_daily"] * DAYS,
        "purchasing": r3["on_demand_monthly"],
        "m1_affected_scope": efficiency_baseline,
    }
    optimized_components = {
        "inference": r2["optimized_daily"] * DAYS,
        "purchasing": r3["optimized_monthly"],
        "m1_affected_scope": efficiency_optimized,
    }
    baseline = sum(baseline_components.values())
    optimized = sum(optimized_components.values())
    total_pct = sum(levers.values()) / baseline * 100 if baseline else 0.0

    # --- sustainability snapshot ---
    median_tokens = 800
    wh = sustainability.wh_per_query(median_tokens)
    region_choices = sustainability.region_choices()
    sust = {
        "wh_per_query": wh,
        "carbon_g": sustainability.carbon_g(wh, "us-east-1"),
        "best_region": region_choices["cleanest"],
        "cleanest_region": region_choices["cleanest"],
        "cheapest_region": region_choices["cheapest"],
        "balanced_region": region_choices["balanced"],
    }

    md = report.build_report(
        baseline,
        optimized,
        levers,
        sustainability=sust,
        scope_note=(
            "The M1 right-size and idle levers are costed only for the affected "
            "GPU-hour scope observed in telemetry. This keeps those opportunities "
            "traceable and prevents double-counting them against the M2/M3 baseline."
        ),
    )
    unit = {
        "requests": r2.get("requests", 0),
        "total_tokens": r2.get("total_tokens", 0),
        "baseline_daily": r2.get("baseline_daily", 0.0),
        "optimized_daily": r2.get("optimized_daily", 0.0),
        "baseline_per_m": r2.get("baseline_per_m", 0.0),
        "optimized_per_m": r2.get("optimized_per_m", 0.0),
    }
    md += "\n\n## Inference Unit Economics\n\n"
    md += "These unit metrics cover M2 inference traffic (the spend is daily); " \
          "the headline M5 spend remains monthly GPU rental cost.\n\n"
    md += "| Metric | Baseline | Optimized |\n|---|---:|---:|\n"
    md += (
        f"| Requests | {unit['requests']:,} | {unit['requests']:,} |\n"
        f"| Tokens served | {unit['total_tokens']:,} | {unit['total_tokens']:,} |\n"
        f"| Inference cost / day | ${unit['baseline_daily']:,.2f} | ${unit['optimized_daily']:,.2f} |\n"
        f"| $/1M-token | ${unit['baseline_per_m']:.3f} | ${unit['optimized_per_m']:.3f} |"
    )
    breakdown = r2.get("lever_breakdown", {})
    if breakdown:
        md += "\n\n### Sequential lever breakdown\n\n"
        md += (
            "Order is baseline → cascade → cache → batch; contributions are "
            "incremental and therefore sum without double-counting.\n\n"
        )
        md += "| Stage | Inference cost / day | Incremental savings / day | % of baseline |\n|---|---:|---:|---:|\n"
        stages = [
            ("Baseline", breakdown.get("baseline_usd", 0.0), 0.0, 0.0),
            (
                "After cascade",
                breakdown.get("after_cascade_usd", 0.0),
                breakdown.get("savings_usd", {}).get("cascade", 0.0),
                breakdown.get("savings_pct_of_baseline", {}).get("cascade", 0.0),
            ),
            (
                "After cache",
                breakdown.get("after_cache_usd", 0.0),
                breakdown.get("savings_usd", {}).get("cache", 0.0),
                breakdown.get("savings_pct_of_baseline", {}).get("cache", 0.0),
            ),
            (
                "After batch (optimized)",
                breakdown.get("optimized_usd", 0.0),
                breakdown.get("savings_usd", {}).get("batch", 0.0),
                breakdown.get("savings_pct_of_baseline", {}).get("batch", 0.0),
            ),
        ]
        for stage, cost, saving, pct in stages:
            md += f"| {stage} | ${cost:,.2f} | ${saving:,.2f} | {pct:.1f}% |\n"
    reasoning = r2.get("reasoning_budget", {})
    if reasoning:
        md += "\n\n## Reasoning Budget\n\n"
        md += "\n".join([
            f"- Reasoning traffic: {reasoning['reasoning_requests']} requests "
            f"({reasoning['reasoning_traffic_pct']:.1f}% of traffic).",
            f"- Optimized reasoning cost: ${reasoning['reasoning_cost_usd']:,.2f} "
            f"({reasoning['reasoning_cost_pct']:.1f}% of optimized inference cost).",
            f"- Reasoning energy: {reasoning['reasoning_energy_wh']:,.2f} Wh "
            f"({reasoning['reasoning_energy_pct']:.1f}% of inference energy).",
            f"- Reasoning premium vs non-reasoning counterfactual: "
            f"${reasoning['reasoning_premium_usd']:,.2f} and "
            f"{reasoning['reasoning_premium_wh']:,.2f} Wh.",
            f"- Routing rule: cap reasoning at {reasoning['cap_fraction']:.0%}, "
            f"preserve the highest-output requests and downgrade "
            f"{reasoning['downgraded_requests']} lowest-output excess requests; "
            f"estimated savings ${reasoning['cap_savings_usd']:,.2f} and "
            f"{reasoning['cap_savings_wh']:,.2f} Wh.",
            f"- Assumption: the synthetic generator's "
            f"{reasoning['output_multiplier_assumption']:.0f}× reasoning output-token "
            "tax is used for the non-reasoning counterfactual.",
        ])
    carbon = r3.get("carbon_schedule", {})
    if carbon:
        choices = carbon.get("region_choices", {})
        carbon_totals = carbon.get("totals", {})
        md += "\n\n## Carbon-aware Scheduling\n\n"
        md += "\n".join([
            f"**Scope:** {carbon.get('scope', 'interruptible training jobs')}.",
            f"**Baseline region:** {carbon.get('baseline_region', 'n/a')}",
            f"**Cheapest electricity:** {choices.get('cheapest', 'n/a')}; "
            f"**cleanest carbon:** {choices.get('cleanest', 'n/a')}; "
            f"**balanced:** {choices.get('balanced', 'n/a')}",
            "",
            "Balanced minimizes the equal-weight score "
            "`(USD/kWh ÷ minimum USD/kWh) + (gCO2e/kWh ÷ minimum gCO2e/kWh)`.",
            "Electricity/carbon deltas are reported separately from GPU rental spend "
            "and are not added to the headline M3 purchasing savings.",
            "Moving checkpoints to another region can increase latency or conflict "
            "with data-residency requirements; validate transfer time, SLA and "
            "residency controls before scheduling.",
            "",
            "### Regional comparison",
            "",
            "| Region | USD/kWh | gCO2e/kWh | Electricity (USD) | Carbon (gCO2e) | Balanced score |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        for row in carbon.get("region_totals", []):
            md += (
                f"\n| {row['region']} | ${row['usd_per_kwh']:.4f} | "
                f"{row['gco2_per_kwh']:.0f} | ${row['electricity_usd']:,.2f} | "
                f"{row['carbon_g']:,.2f} | {row['balanced_score']:.2f} |"
            )
        md += "\n\n### Per-job savings\n\n"
        md += "| Job | GPU-hours | Energy (kWh) | Baseline carbon (g) | Cleanest carbon (g) | Carbon saved (g) | Baseline electricity ($) | Cheapest electricity ($) | Cost saved ($) |\n"
        md += "|---|---:|---:|---:|---:|---:|---:|---:|---:|"
        for row in carbon.get("jobs", []):
            md += (
                f"\n| {row['job_id']} | {row['gpu_hours']:,.2f} | "
                f"{row['energy_wh'] / 1000:,.2f} | {row['baseline_carbon_g']:,.2f} | "
                f"{row['cleanest_carbon_g']:,.2f} | {row['carbon_saved_g']:,.2f} | "
                f"${row['baseline_cost_usd']:,.2f} | ${row['cheapest_cost_usd']:,.2f} | "
                f"${row['cost_saved_usd']:,.2f} |"
            )
        md += "\n\n### Scheduling totals\n\n"
        md += "\n".join([
            f"- Energy: {carbon_totals.get('total_energy_kwh', 0):,.2f} kWh "
            f"across {carbon_totals.get('jobs', 0)} jobs ({carbon_totals.get('total_gpu_hours', 0):,.2f} GPU-hours).",
            f"- Cheapest-electricity option ({choices.get('cheapest', 'n/a')}): "
            f"save ${carbon_totals.get('cheapest_cost_saved_usd', 0):,.2f} "
            f"({carbon_totals.get('cheapest_cost_saved_pct', 0):.1f}%) vs "
            f"{carbon.get('baseline_region', 'n/a')}.",
            f"- Cleanest-carbon option ({choices.get('cleanest', 'n/a')}): "
            f"save {carbon_totals.get('cleanest_carbon_saved_g', 0):,.2f} gCO2e "
            f"({carbon_totals.get('cleanest_carbon_saved_pct', 0):.1f}%).",
            f"- Balanced option ({choices.get('balanced', 'n/a')}): "
            f"${carbon_totals.get('balanced_electricity_usd', 0):,.2f} electricity and "
            f"{carbon_totals.get('balanced_carbon_g', 0):,.2f} gCO2e for this scope.",
        ])
    md += "\n\n## Recommended Actions\n\n"
    top_lever, top_savings = max(levers.items(), key=lambda item: item[1])
    lie_lines = []
    for lie in sorted(r1["lies"], key=lambda item: item["mfu"]):
        lie_lines.append(
            f"`{lie['gpu_id']}` ({lie['gpu_util_pct']:.1f}% GPU-Util, "
            f"MFU {lie['mfu']:.3f})"
        )
    lie_summary = ", ".join(lie_lines) if lie_lines else "none detected"
    md += "\n".join([
        f"1. **Start with {top_lever}:** it contributes ${top_savings:,.0f} "
        "of the modeled monthly savings; validate its operational guardrails before rollout.",
        f"2. **Fix util-lies:** {lie_summary}. GPU-Util measures an active clock, "
        "not useful FLOPs; memory stalls, I/O or launch overhead can keep MFU low. "
        f"The observed idle opportunity is ${r1['idle_waste_daily'] * DAYS:,.0f}/month.",
        "3. **Protect service quality:** keep checkpoint/retry controls for spot, "
        "preserve latency-sensitive requests on the appropriate route, and validate "
        "cache correctness, batch SLOs, region latency and data residency before enforcing policy.",
    ])
    out_md = os.path.join(ROOT, "outputs", "report.md")
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md)
    png = report.savings_waterfall(
        levers,
        os.path.join(ROOT, "outputs", "savings.png"),
        baseline_usd=baseline,
        optimized_usd=optimized,
    )

    if verbose:
        print("== M5 Optimization Report ==")
        print(md)
        print(f"\nWritten: outputs/report.md + {png}")

    return {
        "baseline_monthly": round(baseline),
        "optimized_monthly": round(optimized),
        "levers": levers,
        "baseline_components": {k: round(v, 2) for k, v in baseline_components.items()},
        "optimized_components": {k: round(v, 2) for k, v in optimized_components.items()},
        "cost_ledger_balanced": abs(baseline - optimized - sum(levers.values())) < 0.01,
        "reasoning_budget": reasoning,
        "carbon_schedule": carbon,
        "inference_unit_economics": unit,
        "recommended_actions": lie_summary,
        "total_savings_pct": round(total_pct, 1),
    }


if __name__ == "__main__":
    run()
