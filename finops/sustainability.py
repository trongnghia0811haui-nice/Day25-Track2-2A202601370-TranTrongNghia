"""Sustainability economics — energy and carbon as governed cost levers (deck §11).

Region selection cuts $ and carbon together; reasoning queries are an energy bomb.
"""
from __future__ import annotations

# Grid carbon intensity (gCO2 / kWh) — illustrative 2026 snapshot.
REGION_CARBON = {
    "us-east-1": 380,
    "us-west-2": 120,   # Oregon hydro
    "europe-north1": 30,  # Norway
    "europe-central2": 660,  # Poland (dirtiest)
    "us-east-wa": 90,
}
# Electricity price (USD / kWh) — illustrative.
REGION_PRICE_KWH = {
    "us-east-1": 0.12,
    "us-west-2": 0.07,
    "europe-north1": 0.09,
    "europe-central2": 0.18,
    "us-east-wa": 0.055,
}

REASONING_ENERGY_MULTIPLIER = 80.0  # deck: reasoning ~74-86x a small-model query


def region_choices() -> dict[str, str]:
    """Return explicit cheapest, cleanest and balanced region choices.

    ``balanced`` minimizes price and carbon after normalizing each dimension
    to its best available value.  The three choices stay separate because
    the cheapest region is not necessarily the cleanest one.
    """
    regions = sorted(set(REGION_CARBON) & set(REGION_PRICE_KWH))
    if not regions:
        return {"cheapest": "n/a", "cleanest": "n/a", "balanced": "n/a"}
    cheapest = min(regions, key=lambda region: REGION_PRICE_KWH[region])
    cleanest = min(regions, key=lambda region: REGION_CARBON[region])
    min_price = min(REGION_PRICE_KWH[region] for region in regions)
    min_carbon = min(REGION_CARBON[region] for region in regions)
    balanced = min(
        regions,
        key=lambda region: (REGION_PRICE_KWH[region] / min_price)
        + (REGION_CARBON[region] / min_carbon),
    )
    return {"cheapest": cheapest, "cleanest": cleanest, "balanced": balanced}


def wh_per_query(total_tokens: int, wh_per_1k_tokens: float = 0.30, is_reasoning: bool = False) -> float:
    """Energy for one query. Median Gemini prompt ~0.24 Wh; reasoning ~74-86x."""
    base = (total_tokens / 1000.0) * wh_per_1k_tokens
    return base * (REASONING_ENERGY_MULTIPLIER if is_reasoning else 1.0)


def carbon_g(wh: float, region: str = "us-east-1") -> float:
    """Grams CO2 for an energy amount in a region."""
    gco2_kwh = REGION_CARBON.get(region, 400)
    return (wh / 1000.0) * gco2_kwh


def energy_cost_usd(wh: float, region: str = "us-east-1") -> float:
    """Electricity cost of an energy amount in a region."""
    return (wh / 1000.0) * REGION_PRICE_KWH.get(region, 0.12)


def tokens_per_watt(total_tokens: int, wh: float, seconds: float = 1.0) -> float:
    """Energy efficiency of serving: tokens per watt (higher is better)."""
    watts = (wh * 3600.0) / seconds if seconds > 0 else 0.0
    return total_tokens / watts if watts > 0 else 0.0
