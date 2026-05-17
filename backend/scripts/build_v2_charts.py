"""Render the experiments_v2 figures from the JSON outputs.

  python -m scripts.build_v2_charts

Reads:   backend/docs/experiments_v2/*.json
Writes:  backend/docs/figures/experiments_v2/*.png

Charts produced
---------------
S2  s2_drive_time_histogram.png    drive-time distribution + 9 h cap line
    s2_blocked_by_source.png       customer vs broker, profitable vs blocked
A1  a1_accuracy_per_variant.png    V0/V1/V3/V4 accuracy + 95 % Wilson CI
    a1_category_heatmap.png        per-rule accuracy matrix (variant × category)
T1  t1_margin_by_fleet.png         CP-SAT vs greedy margin by fleet size
    t1_pareto.png                  Pareto curve at fleet=15
T2  t2_headline_bars.png           chains-on vs chains-off (margin / deadhead)
    t2_sensitivity_heatmap.png     fleet × broker-density margin lift %
    t2_chain_fillfactor.png        per-chain fill-factor vs margin
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
EXP_DIR = BACKEND_DIR / "docs" / "experiments_v2"
FIG_DIR = BACKEND_DIR / "docs" / "figures" / "experiments_v2"

# Variant palette (kept consistent with build_charts.py PR2 ablations)
COLOURS = {
    "V0": "#94a3b8",  # slate-400 — deterministic baseline
    "V1": "#ef4444",  # red-500 — vanilla LLM
    "V3": "#3b82f6",  # blue-500 — vanilla + sanity
    "V4": "#10b981",  # emerald-500 — full pipeline
    "greedy":   "#f97316",  # orange-500 — baseline
    "cpsat":    "#10b981",  # emerald-500 — treatment
    "off":      "#94a3b8",
    "on":       "#10b981",
    "customer": "#059669",  # emerald-600
    "broker":   "#7c3aed",  # violet-600
}


def _setup_mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.labelsize": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "savefig.dpi": 160,
        "savefig.bbox": "tight",
    })
    return plt


def _save(plt, fig, name: str) -> None:
    out = FIG_DIR / name
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    print(f"  wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)


# ---------------------------------------------------------------------------
# S2
# ---------------------------------------------------------------------------

def chart_s2(plt) -> None:
    d = json.loads((EXP_DIR / "exp_s2.json").read_text())
    res = d["results"]
    hist = d["details"]["drive_time_histogram"]
    counts = hist["counts"]
    labels = [f"{i}-{i+1}" for i in range(10)] + ["10+"]

    # 1. Drive-time histogram with 9 h cap line
    fig, ax = plt.subplots(figsize=(8, 4.2))
    bar_colours = ["#10b981" if i < 9 else "#ef4444" for i in range(len(counts))]
    ax.bar(labels, counts, color=bar_colours, edgecolor="#0f172a", linewidth=0.4)
    ax.axvline(x=8.5, color="#0f172a", linestyle="--", linewidth=1.2,
               label="EU 561/2006 9 h cap")
    ax.set_xlabel("Estimated drive time (hours, depot → pickup → delivery)")
    ax.set_ylabel("(van × load) pair count")
    ax.set_title(f"S2 — Drive-time distribution across {res['total_pairs']:,} pairs\n"
                 f"red bars = blocked by the 9 h cap ({res['blocked_pairs']} pairs)")
    ax.legend(loc="upper right", frameon=False)
    _save(plt, fig, "s2_drive_time_histogram.png")

    # 2. Profitable vs blocked, by source
    sources = ["customer", "broker"]
    profitable = [res["by_source"][s]["profitable_pairs"] for s in sources]
    blocked    = [res["by_source"][s]["blocked_pairs"] for s in sources]
    safe       = [p - b for p, b in zip(profitable, blocked)]

    fig, ax = plt.subplots(figsize=(6, 4))
    x = range(len(sources))
    ax.bar(x, safe, color="#10b981", label="Safe (≤ 9 h)")
    ax.bar(x, blocked, bottom=safe, color="#ef4444", label="Blocked by hours filter")
    ax.set_xticks(list(x))
    ax.set_xticklabels([s.title() for s in sources])
    ax.set_ylabel("Profitable pairs")
    ax.set_title(f"S2 — Hours-filter impact by load source\n"
                 f"€{res['total_blocked_margin_eur']:,.0f} of margin would tempt illegal trips")
    for i, (s, b) in enumerate(zip(safe, blocked)):
        ax.text(i, s + b + max(profitable) * 0.02, f"{b}\nblocked\n({b/(s+b)*100:.0f} %)",
                ha="center", fontsize=9, color="#7f1d1d")
    ax.legend(loc="upper right", frameon=False)
    _save(plt, fig, "s2_blocked_by_source.png")


# ---------------------------------------------------------------------------
# A1
# ---------------------------------------------------------------------------

def chart_a1(plt) -> None:
    d = json.loads((EXP_DIR / "exp_a1.json").read_text())
    variants = d["results"]["per_variant"]
    matrix = d["results"]["per_category_accuracy"]

    # 1. Accuracy bar chart with 95 % CI
    fig, ax = plt.subplots(figsize=(8, 4.4))
    names = [v["variant"] for v in variants]
    labels = [
        f"{v['variant']}\n{v['label'].split('(')[0].strip()[:18]}"
        for v in variants
    ]
    accs = [v["accuracy"] * 100 for v in variants]
    err_low = [accs[i] - v["accuracy_ci95"][0] * 100 for i, v in enumerate(variants)]
    err_high = [v["accuracy_ci95"][1] * 100 - accs[i] for i, v in enumerate(variants)]
    colours = [COLOURS.get(v["variant"], "#64748b") for v in variants]
    bars = ax.bar(range(len(variants)), accs, color=colours,
                  yerr=[err_low, err_high], capsize=5,
                  edgecolor="#0f172a", linewidth=0.4)
    ax.set_xticks(range(len(variants)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(75, 102)
    ax.set_ylabel("Accuracy on 146-case ground truth (%)")
    ax.set_title(f"A1 — Live-Gemini ablation accuracy  (model: {d['inputs']['gemini_model']})")
    ax.axhline(y=95, color="#0f172a", linestyle=":", linewidth=0.8,
               label="publication floor (95 %)")
    for i, (b, v) in enumerate(zip(bars, variants)):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.4,
                f"{v['accuracy'] * 100:.1f} %",
                ha="center", fontsize=9, fontweight="bold")
    ax.legend(loc="lower right", frameon=False)
    _save(plt, fig, "a1_accuracy_per_variant.png")

    # 2. Per-category accuracy heatmap
    cats = sorted(matrix.keys())
    var_ids = [v["variant"] for v in variants]
    data = [[matrix[c].get(v, {"accuracy": None})["accuracy"]
             if matrix[c].get(v) else None
             for v in var_ids]
            for c in cats]
    # Replace None with NaN for matplotlib
    import math
    data_num = [[(x if x is not None else math.nan) for x in row] for row in data]

    fig, ax = plt.subplots(figsize=(8, 4.6))
    im = ax.imshow(data_num, cmap="RdYlGn", vmin=0.5, vmax=1.0, aspect="auto")
    ax.set_xticks(range(len(var_ids)))
    ax.set_xticklabels(var_ids)
    ax.set_yticks(range(len(cats)))
    ax.set_yticklabels([c.replace("_", " ") for c in cats])
    for i, row in enumerate(data_num):
        for j, x in enumerate(row):
            if x is None or (isinstance(x, float) and math.isnan(x)):
                continue
            cell = matrix[cats[i]][var_ids[j]]
            ax.text(j, i, f"{x:.2f}\n{cell['correct']}/{cell['total']}",
                    ha="center", va="center", fontsize=8,
                    color="#0f172a" if x >= 0.85 else "white")
    ax.set_title("A1 — Per-category accuracy (rule_category × variant)")
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label("Accuracy")
    _save(plt, fig, "a1_category_heatmap.png")


# ---------------------------------------------------------------------------
# T1
# ---------------------------------------------------------------------------

def chart_t1(plt) -> None:
    d = json.loads((EXP_DIR / "exp_t1.json").read_text())
    abundant = d["results"]["abundant"]
    scarce = d["results"]["scarce"]
    pareto = d["results"]["pareto_at_fleet_15"]

    # 1. Margin by fleet size — both regimes
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.4))

    for ax, rows, label in [(ax1, abundant, "ABUNDANT (100 loads)"),
                             (ax2, scarce, "SCARCE (top-10 loads)")]:
        fleets = [r["fleet_size"] for r in rows]
        gm = [r["greedy"]["total_margin_eur"] for r in rows]
        cm = [r["cpsat"]["total_margin_eur"] for r in rows]
        x = range(len(fleets))
        width = 0.36
        ax.bar([i - width / 2 for i in x], gm, width=width,
               color=COLOURS["greedy"], label="FCFS greedy", edgecolor="#0f172a", linewidth=0.4)
        ax.bar([i + width / 2 for i in x], cm, width=width,
               color=COLOURS["cpsat"], label="CP-SAT", edgecolor="#0f172a", linewidth=0.4)
        for i, r in enumerate(rows):
            if r["lift_pct"] is not None:
                ax.text(i, max(gm[i], cm[i]) + 200, f"+{r['lift_pct']:.1f} %",
                        ha="center", fontsize=8, color="#0f172a")
        ax.set_xticks(list(x))
        ax.set_xticklabels([f"{f} vans" for f in fleets])
        ax.set_ylabel("Total fleet margin (€)")
        ax.set_title(label)
        ax.legend(loc="upper left", frameon=False)
    fig.suptitle("T1 — CP-SAT vs FCFS greedy by fleet size", y=1.02)
    _save(plt, fig, "t1_margin_by_fleet.png")

    # 2. Pareto curve at fleet=15
    fig, ax = plt.subplots(figsize=(7, 4))
    times = [p["time_limit_s"] for p in pareto]
    runtimes = [p["runtime_ms"] for p in pareto]
    margins = [p["margin_eur"] for p in pareto]
    ax.plot(runtimes, margins, marker="o", color=COLOURS["cpsat"],
            markersize=10, linewidth=1.5)
    for i, p in enumerate(pareto):
        ax.annotate(f"t≤{p['time_limit_s']:>4}s\n{p['status']}",
                    xy=(runtimes[i], margins[i]),
                    xytext=(8, 5), textcoords="offset points",
                    fontsize=8)
    ax.set_xlabel("Actual solver runtime (ms)")
    ax.set_ylabel("Margin reached (€)")
    ax.set_title("T1 — Pareto: CP-SAT runtime vs margin at fleet=15\n"
                 "All solves return OPTIMAL in < 50 ms; time limit is non-binding")
    _save(plt, fig, "t1_pareto.png")


# ---------------------------------------------------------------------------
# T2
# ---------------------------------------------------------------------------

def chart_t2(plt) -> None:
    d = json.loads((EXP_DIR / "exp_t2.json").read_text())
    h = d["results"]["headline"]
    chains = d["results"]["chain_breakdown"]
    matrix = d["results"]["sensitivity_matrix"]

    # 1. Headline: margin + deadhead + chains formed
    fig, (axm, axd, axc) = plt.subplots(1, 3, figsize=(13, 4.4))

    for ax, key, title, ylabel, fmt in [
        (axm, "total_margin_eur", "Total fleet margin", "€", "{:.0f}"),
        (axd, "deadhead_pct", "Deadhead %", "% of total km", "{:.1f} %"),
        (axc, "chains_formed", "Chains formed", "count", "{}"),
    ]:
        vals = [h["chains_off"][key], h["chains_on"][key]]
        bars = ax.bar(["chains OFF", "chains ON"], vals,
                      color=[COLOURS["off"], COLOURS["on"]],
                      edgecolor="#0f172a", linewidth=0.4)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + max(vals) * 0.02,
                    fmt.format(v), ha="center", fontsize=10, fontweight="bold")
        ax.set_title(title)
        ax.set_ylabel(ylabel)
    fig.suptitle(f"T2 — Backhaul chains headline (fleet {h['fleet_size']}, "
                 f"broker pool {h['broker_density']})", y=1.02)
    _save(plt, fig, "t2_headline_bars.png")

    # 2. Sensitivity heatmap: fleet × broker-density → margin delta %
    fleets = sorted({c["fleet_size"] for c in matrix})
    brokers = sorted({c["broker_density"] for c in matrix})
    grid = [[None for _ in brokers] for _ in fleets]
    dh_grid = [[None for _ in brokers] for _ in fleets]
    for c in matrix:
        i = fleets.index(c["fleet_size"])
        j = brokers.index(c["broker_density"])
        grid[i][j] = c["margin_delta_pct"]
        dh_grid[i][j] = c["deadhead_delta_pp"]

    fig, (axm, axd) = plt.subplots(1, 2, figsize=(11, 4.4))
    im1 = axm.imshow(grid, cmap="Greens", aspect="auto")
    axm.set_xticks(range(len(brokers))); axm.set_xticklabels([f"broker={b}" for b in brokers])
    axm.set_yticks(range(len(fleets))); axm.set_yticklabels([f"fleet={f}" for f in fleets])
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            if v is not None:
                axm.text(j, i, f"+{v:.0f} %", ha="center", va="center", fontsize=11)
    axm.set_title("Margin lift (chains-on vs chains-off)")
    plt.colorbar(im1, ax=axm)

    im2 = axd.imshow(dh_grid, cmap="Greens_r", aspect="auto")
    axd.set_xticks(range(len(brokers))); axd.set_xticklabels([f"broker={b}" for b in brokers])
    axd.set_yticks(range(len(fleets))); axd.set_yticklabels([f"fleet={f}" for f in fleets])
    for i, row in enumerate(dh_grid):
        for j, v in enumerate(row):
            if v is not None:
                axd.text(j, i, f"{v:.1f} pp", ha="center", va="center", fontsize=11)
    axd.set_title("Deadhead change (chains-on vs chains-off)")
    plt.colorbar(im2, ax=axd)
    fig.suptitle("T2 — Sensitivity matrix: chains stay valuable across regimes", y=1.02)
    _save(plt, fig, "t2_sensitivity_heatmap.png")

    # 3. Per-chain quality scatter
    if chains:
        fig, ax = plt.subplots(figsize=(7.5, 4.4))
        margins = [c["margin_eur"] for c in chains]
        kms = [c["total_km"] for c in chains]
        fills = [c["fill_factor"] for c in chains]
        sc = ax.scatter(kms, margins, c=fills, cmap="viridis", vmin=0.5, vmax=1.0,
                        s=80, edgecolor="#0f172a", linewidth=0.5)
        for c in chains:
            ax.annotate(c["van_plate"].replace("-CRL", ""),
                        xy=(c["total_km"], c["margin_eur"]),
                        xytext=(4, -2), textcoords="offset points",
                        fontsize=7, color="#0f172a")
        ax.set_xlabel("Total chain km")
        ax.set_ylabel("Chain margin (€)")
        ax.set_title(f"T2 — Per-chain quality ({len(chains)} chains formed at fleet=25)\n"
                     "colour = fill-factor (loaded_km / total_km)")
        cbar = plt.colorbar(sc, ax=ax)
        cbar.set_label("Fill factor")
        _save(plt, fig, "t2_chain_fillfactor.png")


def main() -> None:
    plt = _setup_mpl()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    print("[v2-charts] rendering figures …", file=sys.stderr)
    chart_s2(plt)
    chart_a1(plt)
    chart_t1(plt)
    chart_t2(plt)
    print("[v2-charts] done.", file=sys.stderr)


if __name__ == "__main__":
    main()
