"""M3 — Purchasing Strategy: break-even, tier choice, spot-checkpoint sim (deck §4).

Run: python missions/m3_purchasing.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from missions._common import load_csv, num, catalog_by_type
from finops import pricing, sustainability

DAYS = 30
BASELINE_REGION = "us-east-1"


def _workload_gpu_hours(job: dict) -> float:
    """Return non-negative GPU-hours using the workload's actual duration."""
    hours_per_day = max(0.0, num(job.get("hours_per_day")))
    days = max(0.0, num(job.get("days"), DAYS))
    num_gpus = max(0, int(num(job.get("num_gpus"))))
    return hours_per_day * days * num_gpus


def carbon_schedule(jobs: list[dict], cat: dict) -> dict:
    """Compare electricity cost and grid carbon for interruptible train jobs.

    Training jobs are the safe scheduling scope for this lab: inference and
    non-interruptible workloads stay in their existing regions.  The returned
    values are separate from GPU rental spend so the M5 headline does not
    double-count purchasing savings.
    """
    regions = sorted(set(sustainability.REGION_CARBON) & set(sustainability.REGION_PRICE_KWH))
    choices = sustainability.region_choices()
    baseline_region = BASELINE_REGION if BASELINE_REGION in regions else (regions[0] if regions else "n/a")

    job_rows = []
    for job in jobs:
        is_train = str(job.get("kind", "")).lower() == "train"
        is_interruptible = bool(int(num(job.get("interruptible"))))
        if not (is_train and is_interruptible):
            continue

        gpu_type = job["gpu_type"]
        gpu_hours = _workload_gpu_hours(job)
        watts = max(0.0, num(cat[gpu_type].get("watts")))
        energy_wh = watts * gpu_hours

        def region_values(region: str) -> tuple[float, float]:
            if region == "n/a":
                return 0.0, 0.0
            return (
                sustainability.energy_cost_usd(energy_wh, region),
                sustainability.carbon_g(energy_wh, region),
            )

        baseline_cost, baseline_carbon = region_values(baseline_region)
        cheapest_cost, cheapest_carbon = region_values(choices.get("cheapest", "n/a"))
        cleanest_cost, cleanest_carbon = region_values(choices.get("cleanest", "n/a"))
        balanced_cost, balanced_carbon = region_values(choices.get("balanced", "n/a"))
        job_rows.append({
            "job_id": job["job_id"],
            "gpu_type": gpu_type,
            "gpu_hours": gpu_hours,
            "energy_wh": energy_wh,
            "baseline_cost_usd": baseline_cost,
            "baseline_carbon_g": baseline_carbon,
            "cheapest_cost_usd": cheapest_cost,
            "cheapest_carbon_g": cheapest_carbon,
            "cleanest_cost_usd": cleanest_cost,
            "cleanest_carbon_g": cleanest_carbon,
            "balanced_cost_usd": balanced_cost,
            "balanced_carbon_g": balanced_carbon,
            "cost_saved_usd": baseline_cost - cheapest_cost,
            "carbon_saved_g": baseline_carbon - cleanest_carbon,
        })

    total_energy_wh = sum(row["energy_wh"] for row in job_rows)
    min_price = min((sustainability.REGION_PRICE_KWH[r] for r in regions), default=1.0)
    min_carbon = min((sustainability.REGION_CARBON[r] for r in regions), default=1.0)
    region_totals = []
    for region in regions:
        electricity_usd = sustainability.energy_cost_usd(total_energy_wh, region)
        carbon_g = sustainability.carbon_g(total_energy_wh, region)
        region_totals.append({
            "region": region,
            "usd_per_kwh": sustainability.REGION_PRICE_KWH[region],
            "gco2_per_kwh": sustainability.REGION_CARBON[region],
            "balanced_score": (
                sustainability.REGION_PRICE_KWH[region] / min_price
                + sustainability.REGION_CARBON[region] / min_carbon
            ),
            "electricity_usd": electricity_usd,
            "carbon_g": carbon_g,
        })

    def sum_field(field: str) -> float:
        return sum(row[field] for row in job_rows)

    baseline_cost = sum_field("baseline_cost_usd")
    cheapest_cost = sum_field("cheapest_cost_usd")
    baseline_carbon = sum_field("baseline_carbon_g")
    cleanest_carbon = sum_field("cleanest_carbon_g")
    balanced_cost = sum_field("balanced_cost_usd")
    balanced_carbon = sum_field("balanced_carbon_g")
    totals = {
        "jobs": len(job_rows),
        "total_gpu_hours": sum_field("gpu_hours"),
        "total_energy_wh": total_energy_wh,
        "total_energy_kwh": total_energy_wh / 1000.0,
        "baseline_electricity_usd": baseline_cost,
        "cheapest_electricity_usd": cheapest_cost,
        "cheapest_cost_saved_usd": baseline_cost - cheapest_cost,
        "cheapest_cost_saved_pct": (baseline_cost - cheapest_cost) / baseline_cost * 100
        if baseline_cost else 0.0,
        "baseline_carbon_g": baseline_carbon,
        "cleanest_carbon_g": cleanest_carbon,
        "cleanest_carbon_saved_g": baseline_carbon - cleanest_carbon,
        "cleanest_carbon_saved_pct": (baseline_carbon - cleanest_carbon) / baseline_carbon * 100
        if baseline_carbon else 0.0,
        "balanced_electricity_usd": balanced_cost,
        "balanced_carbon_g": balanced_carbon,
        "balanced_cost_saved_usd": baseline_cost - balanced_cost,
        "balanced_carbon_saved_g": baseline_carbon - balanced_carbon,
    }

    rounded_jobs = []
    for row in job_rows:
        rounded_jobs.append({
            key: round(value, 2) if isinstance(value, float) else value
            for key, value in row.items()
        })
    rounded_regions = []
    for row in region_totals:
        rounded_regions.append({
            key: round(value, 4) if isinstance(value, float) else value
            for key, value in row.items()
        })
    rounded_totals = {
        key: round(value, 2) if isinstance(value, float) else value
        for key, value in totals.items()
    }
    return {
        "scope": "interruptible training jobs",
        "baseline_region": baseline_region,
        "region_choices": choices,
        "region_totals": rounded_regions,
        "jobs": rounded_jobs,
        "totals": rounded_totals,
    }


def run(verbose: bool = True) -> dict:
    jobs = load_csv("workloads.csv")
    cat = catalog_by_type()
    on_demand_monthly = optimized_monthly = 0.0
    recs = []
    for j in jobs:
        gtype = j["gpu_type"]
        hpd = num(j["hours_per_day"])
        interruptible = bool(int(num(j["interruptible"])))
        c = cat[gtype]
        gpu_hours = _workload_gpu_hours(j)
        od = num(c["on_demand_hr"])
        on_demand_cost = gpu_hours * od

        tier = pricing.recommend_tier(hpd, interruptible)
        if tier == "spot":
            sim = pricing.spot_checkpoint_cost(gpu_hours, num(c["spot_hr"]), od)
            opt_cost = sim["spot_cost"]
        elif tier == "reserved":
            opt_cost = gpu_hours * num(c["reserved_3yr_hr"])
        else:
            opt_cost = on_demand_cost

        on_demand_monthly += on_demand_cost
        optimized_monthly += opt_cost
        recs.append({"job_id": j["job_id"], "gpu_type": gtype, "tier": tier,
                     "on_demand": round(on_demand_cost), "optimized": round(opt_cost)})

    savings = on_demand_monthly - optimized_monthly
    savings_pct = savings / on_demand_monthly * 100 if on_demand_monthly else 0.0
    carbon = carbon_schedule(jobs, cat)

    if verbose:
        print("== M3 Purchasing Strategy ==")
        print(f"break-even utilization @ 45% reserved discount = {pricing.break_even_utilization(0.45):.0%}")
        print(f"{'job':18}{'gpu':7}{'tier':11}{'on-demand':>12}{'optimized':>12}")
        for r in recs:
            print(f"{r['job_id']:18}{r['gpu_type']:7}{r['tier']:11}${r['on_demand']:>11,}${r['optimized']:>11,}")
        print(f"\nmonthly: on-demand ${on_demand_monthly:,.0f} -> optimized ${optimized_monthly:,.0f}  ({savings_pct:.1f}% saved)")
        print("\ncarbon-aware scheduling (interruptible training only):")
        print(
            f"energy: {carbon['totals']['total_energy_kwh']:,.2f} kWh across "
            f"{carbon['totals']['jobs']} jobs; "
            f"cleanest={carbon['region_choices']['cleanest']}, "
            f"cheapest={carbon['region_choices']['cheapest']}, "
            f"balanced={carbon['region_choices']['balanced']}"
        )
        print(f"{'region':18}{'USD/kWh':>10}{'gCO2/kWh':>12}{'electricity':>16}{'carbon g':>16}")
        for row in carbon["region_totals"]:
            print(
                f"{row['region']:18}${row['usd_per_kwh']:>9.3f}"
                f"{row['gco2_per_kwh']:>12.0f}${row['electricity_usd']:>15,.2f}"
                f"{row['carbon_g']:>16,.0f}"
            )
        print("per-job savings (baseline us-east-1 -> cheapest electricity / cleanest carbon):")
        for row in carbon["jobs"]:
            print(
                f"  {row['job_id']:18} {row['gpu_hours']:>8,.1f} GPUh  "
                f"${row['cost_saved_usd']:>8,.2f}  {row['carbon_saved_g']:>10,.0f} gCO2e"
            )
        print(
            f"total: save ${carbon['totals']['cheapest_cost_saved_usd']:,.2f} electricity "
            f"({carbon['totals']['cheapest_cost_saved_pct']:.1f}%) and "
            f"{carbon['totals']['cleanest_carbon_saved_g']:,.0f} gCO2e "
            f"({carbon['totals']['cleanest_carbon_saved_pct']:.1f}%)"
        )

    return {"recommendations": recs, "on_demand_monthly": round(on_demand_monthly),
            "optimized_monthly": round(optimized_monthly), "savings_pct": round(savings_pct, 1),
            "carbon_schedule": carbon}


if __name__ == "__main__":
    run()
