"""M2 — Inference Cost Levers: $/1M-token, batch x cache x cascade (deck §7).

Run: python missions/m2_inference_levers.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from missions._common import load_csv, num
from finops import pricing, sustainability

# $/1M tokens (input, output) — illustrative 2026.
MODEL_PRICES = {"small": (0.20, 0.40), "large": (3.00, 15.00)}
REASONING_CAP_FRACTION = 0.05
REASONING_OUTPUT_MULTIPLIER = 6.0


def run(verbose: bool = True) -> dict:
    rows = load_csv("token_usage.csv")
    base_cost = opt_cost = 0.0
    cascade_cost = cache_cost = 0.0
    total_tokens = 0
    groups = {
        "reasoning": {"requests": 0, "tokens": 0, "cost": 0.0, "energy_wh": 0.0},
        "standard": {"requests": 0, "tokens": 0, "cost": 0.0, "energy_wh": 0.0},
    }
    reasoning_rows = []
    for r in rows:
        inp, out = int(num(r["input_tokens"])), int(num(r["output_tokens"]))
        cached = int(num(r["cached_input_tokens"]))
        is_batch = bool(int(num(r["is_batch"])))
        is_reasoning = bool(int(num(r["is_reasoning"])))
        request_tokens = inp + out
        total_tokens += request_tokens
        # BASELINE: naive deployment — everything on the large model, no cache, no batch
        lin, lout = MODEL_PRICES["large"]
        baseline_row_cost = pricing.request_cost(inp, out, lin, lout)
        base_cost += baseline_row_cost
        # OPTIMIZED: cascade (route_tier), prompt caching, batch API
        route_tier = r.get("route_tier")
        if route_tier not in MODEL_PRICES:
            supported = ", ".join(sorted(MODEL_PRICES))
            raise ValueError(f"unsupported route_tier {route_tier!r}; expected one of {supported}")
        pin, pout = MODEL_PRICES[route_tier]
        cascade_row_cost = pricing.request_cost(inp, out, pin, pout)
        cache_row_cost = pricing.request_cost(inp, out, pin, pout, cached_in=cached)
        cascade_cost += cascade_row_cost
        cache_cost += cache_row_cost
        row_cost = pricing.request_cost(inp, out, pin, pout, cached_in=cached, batch=is_batch)
        opt_cost += row_cost

        group_name = "reasoning" if is_reasoning else "standard"
        group = groups[group_name]
        group["requests"] += 1
        group["tokens"] += request_tokens
        group["cost"] += row_cost
        group["energy_wh"] += sustainability.wh_per_query(request_tokens, is_reasoning=is_reasoning)

        if is_reasoning:
            # The synthetic generator applies a sixfold output-token tax to
            # reasoning traffic.  Use that documented assumption for a
            # counterfactual non-reasoning route and for the cap simulation.
            counter_output = out / REASONING_OUTPUT_MULTIPLIER
            counter_cost = pricing.request_cost(
                inp, counter_output, pin, pout, cached_in=cached, batch=is_batch
            )
            counter_energy = sustainability.wh_per_query(
                inp + counter_output, is_reasoning=False
            )
            reasoning_rows.append({
                "output_tokens": out,
                "cost": row_cost,
                "counter_cost": counter_cost,
                "energy_wh": sustainability.wh_per_query(request_tokens, is_reasoning=True),
                "counter_energy_wh": counter_energy,
            })

    reasoning = groups["reasoning"]
    standard = groups["standard"]
    reasoning_requests = reasoning["requests"]
    cap_requests = int(len(rows) * REASONING_CAP_FRACTION)
    excess = max(0, reasoning_requests - cap_requests)
    downgrade = sorted(reasoning_rows, key=lambda item: item["output_tokens"])[:excess]
    cap_savings_usd = sum(item["cost"] - item["counter_cost"] for item in downgrade)
    cap_savings_wh = sum(item["energy_wh"] - item["counter_energy_wh"] for item in downgrade)

    counterfactual_cost = sum(item["counter_cost"] for item in reasoning_rows)
    counterfactual_energy = sum(item["counter_energy_wh"] for item in reasoning_rows)
    reasoning_budget = {
        "reasoning_requests": reasoning_requests,
        "standard_requests": standard["requests"],
        "reasoning_traffic_pct": round(reasoning_requests / len(rows) * 100, 1) if rows else 0.0,
        "reasoning_tokens": reasoning["tokens"],
        "standard_tokens": standard["tokens"],
        "reasoning_cost_usd": round(reasoning["cost"], 2),
        "standard_cost_usd": round(standard["cost"], 2),
        "reasoning_cost_pct": round(reasoning["cost"] / opt_cost * 100, 1) if opt_cost else 0.0,
        "reasoning_energy_wh": round(reasoning["energy_wh"], 2),
        "standard_energy_wh": round(standard["energy_wh"], 2),
        "reasoning_energy_pct": round(
            reasoning["energy_wh"] / (reasoning["energy_wh"] + standard["energy_wh"]) * 100, 1
        ) if (reasoning["energy_wh"] + standard["energy_wh"]) else 0.0,
        "counterfactual_non_reasoning_cost_usd": round(counterfactual_cost, 2),
        "counterfactual_non_reasoning_energy_wh": round(counterfactual_energy, 2),
        "reasoning_premium_usd": round(reasoning["cost"] - counterfactual_cost, 2),
        "reasoning_premium_wh": round(reasoning["energy_wh"] - counterfactual_energy, 2),
        "cap_fraction": REASONING_CAP_FRACTION,
        "cap_requests": cap_requests,
        "downgraded_requests": excess,
        "cap_savings_usd": round(cap_savings_usd, 2),
        "cap_savings_wh": round(cap_savings_wh, 2),
        "output_multiplier_assumption": REASONING_OUTPUT_MULTIPLIER,
    }

    # Sequential waterfall: apply one lever at a time so the three savings
    # contributions add exactly to the optimized-vs-baseline delta.  The
    # ordering is explicit because standalone counterfactuals would overlap.
    lever_savings = {
        "cascade": base_cost - cascade_cost,
        "cache": cascade_cost - cache_cost,
        "batch": cache_cost - opt_cost,
    }
    lever_breakdown = {
        "method": "sequential: baseline -> cascade -> cache -> batch",
        "baseline_usd": round(base_cost, 2),
        "after_cascade_usd": round(cascade_cost, 2),
        "after_cache_usd": round(cache_cost, 2),
        "optimized_usd": round(opt_cost, 2),
        "savings_usd": {name: round(value, 2) for name, value in lever_savings.items()},
        "savings_pct_of_baseline": {
            name: round(value / base_cost * 100, 1) if base_cost else 0.0
            for name, value in lever_savings.items()
        },
    }

    base_pm = pricing.dollars_per_million(base_cost, total_tokens)
    opt_pm = pricing.dollars_per_million(opt_cost, total_tokens)
    savings_pct = (1 - opt_cost / base_cost) * 100 if base_cost else 0.0

    if verbose:
        print("== M2 Inference Cost Levers ==")
        print(f"requests={len(rows)}  tokens={total_tokens:,}")
        print(f"baseline  : ${base_cost:,.2f}/day   ${base_pm:.3f}/1M-token")
        print(f"optimized : ${opt_cost:,.2f}/day   ${opt_pm:.3f}/1M-token")
        print(f"savings   : {savings_pct:.1f}%  (cascade + caching + batch)")
        print(f"discount stack (batch + 100% cache): {pricing.discount_stack(batch=True, cache_hit_frac=1.0):.3f} of naive")
        print("lever waterfall (daily inference cost):")
        print(f"  cascade: ${lever_savings['cascade']:,.2f} saved")
        print(f"  cache  : ${lever_savings['cache']:,.2f} saved")
        print(f"  batch  : ${lever_savings['batch']:,.2f} saved")
        print(
            f"reasoning : {reasoning_requests}/{len(rows)} requests "
            f"({reasoning_budget['reasoning_traffic_pct']:.1f}%), "
            f"${reasoning_budget['reasoning_cost_usd']:.2f} "
            f"({reasoning_budget['reasoning_cost_pct']:.1f}% of optimized cost), "
            f"{reasoning_budget['reasoning_energy_wh']:.2f} Wh "
            f"({reasoning_budget['reasoning_energy_pct']:.1f}% of energy)"
        )
        print(
            f"reasoning cap: {REASONING_CAP_FRACTION:.0%} traffic -> "
            f"downgrade {excess} requests, save "
            f"${cap_savings_usd:.2f} / {cap_savings_wh:.2f} Wh"
        )

    return {
        "baseline_daily": round(base_cost, 2), "optimized_daily": round(opt_cost, 2),
        "baseline_per_m": round(base_pm, 3), "optimized_per_m": round(opt_pm, 3),
        "savings_pct": round(savings_pct, 1), "requests": len(rows), "total_tokens": total_tokens,
        "reasoning_budget": reasoning_budget,
        "lever_breakdown": lever_breakdown,
    }


if __name__ == "__main__":
    run()
