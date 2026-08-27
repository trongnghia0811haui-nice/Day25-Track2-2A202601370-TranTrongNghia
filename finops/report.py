"""Report assembly — the lab's deliverable: baseline vs optimized + savings chart."""
from __future__ import annotations


def build_report(baseline_usd: float, optimized_usd: float, levers: dict,
                 sustainability: dict | None = None, period: str = "monthly",
                 scope_note: str | None = None) -> str:
    """Return a markdown cost-optimization report."""
    savings = baseline_usd - optimized_usd
    pct = (savings / baseline_usd * 100.0) if baseline_usd > 0 else 0.0
    lines = [
        "# NimbusAI — GPU Cost Optimization Report",
        "",
        f"**Period:** {period}  ",
        f"**Baseline spend:** ${baseline_usd:,.0f}  ",
        f"**Optimized spend:** ${optimized_usd:,.0f}  ",
        f"**Projected savings:** ${savings:,.0f}  (**{pct:.0f}%**)",
        "",
        "## Savings by lever",
        "",
        "| Lever | Savings (USD) |",
        "|---|---|",
    ]
    for name, amount in levers.items():
        lines.append(f"| {name} | ${amount:,.0f} |")
    if scope_note:
        lines += ["", "## Cost model scope", "", scope_note]
    if sustainability:
        cleanest = sustainability.get("cleanest_region", sustainability.get("best_region", "n/a"))
        cheapest = sustainability.get("cheapest_region", "n/a")
        balanced = sustainability.get("balanced_region", "n/a")
        lines += [
            "",
            "## Sustainability",
            "",
            f"- Energy per query: {sustainability.get('wh_per_query', 0):.2f} Wh",
            f"- Carbon per query: {sustainability.get('carbon_g', 0):.3f} gCO2e",
            f"- Cleanest region (carbon): {cleanest}",
            f"- Cheapest region (electricity): {cheapest}",
            f"- Balanced region (normalized cost + carbon): {balanced}",
        ]
    lines += ["", "_Figures are June-2026 as-of snapshots; re-baseline before acting._"]
    return "\n".join(lines)


def savings_waterfall(
    levers: dict,
    path: str,
    baseline_usd: float | None = None,
    optimized_usd: float | None = None,
) -> str:
    """Write a cumulative savings waterfall PNG and return its path.

    Matplotlib is a declared project dependency because the PNG is a graded
    artifact.  Missing dependencies raise an actionable error instead of
    silently producing an incomplete submission.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib is required to generate outputs/savings.png; "
            "install requirements.txt before running M5"
        ) from exc
    names = list(levers.keys())
    vals = [float(levers[n]) for n in names]
    if baseline_usd is None:
        baseline_usd = sum(vals)
    if optimized_usd is None:
        optimized_usd = baseline_usd - sum(vals)

    labels = ["Baseline"] + names + ["Optimized"]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(0, baseline_usd, color="#2e548a")
    ax.text(0, baseline_usd, f"${baseline_usd:,.0f}", ha="center", va="bottom", fontsize=8)

    running = baseline_usd
    for index, value in enumerate(vals, start=1):
        new_running = running - value
        bottom = min(running, new_running)
        height = abs(value)
        color = "#3a7d44" if value >= 0 else "#b54545"
        ax.bar(index, height, bottom=bottom, color=color)
        ax.text(index, bottom + height, f"${value:,.0f}", ha="center", va="bottom", fontsize=8)
        running = new_running

    last = len(labels) - 1
    ax.bar(last, optimized_usd, color="#2e548a")
    ax.text(last, optimized_usd, f"${optimized_usd:,.0f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(range(len(labels)), labels, rotation=20, ha="right")
    ax.set_ylabel("Monthly spend (USD)")
    ax.set_title("GPU cost savings waterfall")
    plt.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path
