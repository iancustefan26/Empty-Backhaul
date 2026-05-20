"""Render the R-series figures from the 123cargo experiment JSONs.

  python -m scripts.build_123cargo_charts

Reads:   backend/docs/experiments_123cargo/exp_r{1..4}.json
Writes:  backend/docs/figures/experiments_123cargo/r{1..4}_*.png

11 PNGs total (3 + 2 + 3 + 3). Mirrors the v2 chart builder's
style + helpers (no external dependencies beyond matplotlib).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
EXP_DIR = BACKEND_DIR / "docs" / "experiments_123cargo"
FIG_DIR = BACKEND_DIR / "docs" / "figures" / "experiments_123cargo"

# Reuse the v2 palette so the thesis figures look unified across chapters
COLOURS = {
    "off":      "#94a3b8",
    "on":       "#10b981",
    "primary":  "#f97316",
    "accent":   "#0ea5e9",
    "customer": "#059669",
    "broker":   "#7c3aed",
    "warn":     "#d97706",
    "danger":   "#dc2626",
}

ROMANIA_BOUNDS = (20.0, 30.0, 43.5, 48.5)   # (lon_min, lon_max, lat_min, lat_max)


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


def _add_romania_backdrop(ax, *, alpha: float = 0.06):
    """Subtle rectangular outline for Romania on a map-style plot."""
    lon_min, lon_max, lat_min, lat_max = ROMANIA_BOUNDS
    ax.set_xlim(lon_min, lon_max)
    ax.set_ylim(lat_min, lat_max)
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=alpha * 5)


# ---------------------------------------------------------------------------
# R1
# ---------------------------------------------------------------------------

def chart_r1(plt) -> None:
    path = EXP_DIR / "exp_r1.json"
    if not path.exists():
        print(f"  [skip] {path.name} missing", file=sys.stderr)
        return
    d = json.loads(path.read_text())
    h_on = d["results"]["headline_chains_on"]
    h_off = d["results"]["comparison_chains_off"]
    per_van = d["details"]["per_van_breakdown_chains_on"]

    # 1. Per-van breakdown — horizontal bar
    fig, ax = plt.subplots(figsize=(9, 4.5))
    plates = [v["plate"] for v in per_van]
    margins = [v["margin_eur"] for v in per_van]
    colours = [COLOURS["on"] if v["kind"] == "CHAIN"
               else COLOURS["primary"] if v["kind"] == "SINGLE"
               else COLOURS["off"]
               for v in per_van]
    bars = ax.barh(plates, margins, color=colours,
                   edgecolor="#0f172a", linewidth=0.4)
    for b, v in zip(bars, per_van):
        if v["margin_eur"] > 0:
            ax.text(b.get_width() + max(margins) * 0.01,
                    b.get_y() + b.get_height() / 2,
                    f"€{v['margin_eur']:.0f} · {v['route'][:35]}",
                    va="center", fontsize=8)
    ax.set_xlabel("Margin (€)")
    ax.set_title(f"R1 — Per-van earnings on real Frigo market "
                 f"(7-van Cluj fleet, {h_on['loads_served']} loads served)")
    ax.invert_yaxis()
    # Legend
    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(facecolor=COLOURS["on"], label="CHAIN (2 loads)"),
        Patch(facecolor=COLOURS["primary"], label="SINGLE (1 load)"),
        Patch(facecolor=COLOURS["off"], label="IDLE"),
    ], loc="lower right", frameon=False, fontsize=8)
    _save(plt, fig, "r1_per_van_breakdown.png")

    # 2. Chains impact — grouped bars
    fig, ax = plt.subplots(figsize=(8, 4.4))
    metrics = ["total_margin_eur", "loads_served", "chains_formed", "vans_dispatched"]
    metric_labels = ["Margin (€)", "Loads served", "Chains formed", "Vans dispatched"]
    x = range(len(metrics))
    width = 0.36
    off_vals = [h_off[m] for m in metrics]
    on_vals = [h_on[m] for m in metrics]

    # Margin is on different scale; normalize each metric to its max
    maxes = [max(o, n, 1) for o, n in zip(off_vals, on_vals)]
    off_norm = [v / mx * 100 for v, mx in zip(off_vals, maxes)]
    on_norm = [v / mx * 100 for v, mx in zip(on_vals, maxes)]
    ax.bar([i - width / 2 for i in x], off_norm, width,
           color=COLOURS["off"], label="chains OFF", edgecolor="#0f172a", linewidth=0.4)
    ax.bar([i + width / 2 for i in x], on_norm, width,
           color=COLOURS["on"], label="chains ON", edgecolor="#0f172a", linewidth=0.4)
    for i, (o, n) in enumerate(zip(off_vals, on_vals)):
        ax.text(i - width / 2, off_norm[i] + 2, f"{o:.0f}", ha="center", fontsize=8)
        ax.text(i + width / 2, on_norm[i] + 2, f"{n:.0f}", ha="center", fontsize=8,
                fontweight="bold")
    ax.set_xticks(list(x))
    ax.set_xticklabels(metric_labels)
    ax.set_ylabel("Normalised (% of max)")
    delta_pct = d["results"]["deltas"].get("margin_delta_pct")
    delta_str = f" (margin +{delta_pct:.0f}%)" if delta_pct is not None else ""
    ax.set_title(f"R1 — Chain advantage on real freight{delta_str}")
    ax.legend(loc="upper right", frameon=False)
    ax.set_ylim(0, 115)
    _save(plt, fig, "r1_chains_impact.png")

    # 3. Route map — top loads served (with depot star)
    top_loads = d["details"]["top_5_profitable_loads_chains_on"]
    if top_loads:
        # We need the lat/lng for each — they're not in R1's JSON since I only
        # serialised the 123cargo_id + route name. Re-load from the dataset.
        from app.services import load_123cargo as l123c  # type: ignore
        from app.data.romania_cities import ROMANIA_CITIES
        cargo_data = l123c.load_dataset()
        by_id = {r["id"]: r for r in cargo_data["loads"]}

        fig, ax = plt.subplots(figsize=(8, 6))
        _add_romania_backdrop(ax)

        # Depot
        cluj = ROMANIA_CITIES["Cluj-Napoca"]
        ax.scatter([cluj.lon], [cluj.lat], marker="*", s=400,
                   c=COLOURS["primary"], edgecolors="#0f172a", linewidths=1,
                   zorder=10, label="Depot")
        ax.annotate("Cluj-Napoca\n(depot)", (cluj.lon, cluj.lat),
                    textcoords="offset points", xytext=(8, 8),
                    fontsize=9, fontweight="bold")

        # Loads served (top 5)
        for tl in top_loads:
            row = by_id.get(tl["123cargo_id"])
            if not row:
                continue
            pl, pn = float(row["source_lng"]), float(row["source_lat"])
            dl, dn = float(row["destination_lng"]), float(row["destination_lat"])
            # Empty leg from depot to pickup
            ax.plot([cluj.lon, pl], [cluj.lat, pn],
                    color=COLOURS["off"], linestyle="--", linewidth=1, alpha=0.5)
            # Loaded leg pickup → delivery
            ax.plot([pl, dl], [pn, dn], color=COLOURS["on"], linewidth=2.5,
                    alpha=0.85)
            # Empty leg back to depot
            ax.plot([dl, cluj.lon], [dn, cluj.lat],
                    color=COLOURS["off"], linestyle="--", linewidth=1, alpha=0.5)
            # Markers
            ax.scatter([pl], [pn], marker="o", s=60, c=COLOURS["accent"],
                       edgecolors="#0f172a", linewidths=0.5, zorder=8)
            ax.scatter([dl], [dn], marker="s", s=60, c=COLOURS["broker"],
                       edgecolors="#0f172a", linewidths=0.5, zorder=8)

        from matplotlib.patches import Patch
        from matplotlib.lines import Line2D
        ax.legend(handles=[
            Line2D([], [], color=COLOURS["primary"], marker="*", linestyle="",
                   markersize=12, label="Depot (Cluj)"),
            Line2D([], [], color=COLOURS["accent"], marker="o", linestyle="",
                   markersize=8, label="Pickup"),
            Line2D([], [], color=COLOURS["broker"], marker="s", linestyle="",
                   markersize=8, label="Delivery"),
            Line2D([], [], color=COLOURS["on"], linewidth=2.5, label="Loaded km"),
            Line2D([], [], color=COLOURS["off"], linestyle="--", label="Empty km"),
        ], loc="upper left", frameon=False, fontsize=8)
        ax.set_title(f"R1 — Top {len(top_loads)} profitable routes "
                     f"the 7-van Cluj fleet picked up")
        _save(plt, fig, "r1_route_map.png")


# ---------------------------------------------------------------------------
# R2
# ---------------------------------------------------------------------------

def chart_r2(plt) -> None:
    path = EXP_DIR / "exp_r2.json"
    if not path.exists():
        print(f"  [skip] {path.name} missing", file=sys.stderr)
        return
    d = json.loads(path.read_text())
    rows = d["results"]["per_depot"]

    # 1. Depot comparison — grouped bars
    fig, ax = plt.subplots(figsize=(9, 4.6))
    depots = [r["depot"] for r in rows]
    margins = [r["total_margin_eur"] for r in rows]
    dispatched = [r["vans_dispatched"] for r in rows]
    served = [r["loads_served"] for r in rows]
    deadhead = [r["deadhead_pct"] for r in rows]

    # Normalize each metric to its row max for a unified scale
    margin_norm = [m / max(margins) * 100 if max(margins) > 0 else 0 for m in margins]
    dispatched_norm = [v / max(dispatched) * 100 if max(dispatched) > 0 else 0
                       for v in dispatched]
    served_norm = [v / max(served) * 100 if max(served) > 0 else 0 for v in served]
    # Deadhead: lower is better, invert so all bars point "good = tall"
    max_dh = max(deadhead) if max(deadhead) > 0 else 1
    deadhead_norm = [(max_dh - v) / max_dh * 100 for v in deadhead]

    x = list(range(len(depots)))
    width = 0.18
    ax.bar([i - 1.5 * width for i in x], margin_norm, width,
           color=COLOURS["on"], label=f"Margin (max €{max(margins):.0f})")
    ax.bar([i - 0.5 * width for i in x], dispatched_norm, width,
           color=COLOURS["primary"], label="Vans dispatched")
    ax.bar([i + 0.5 * width for i in x], served_norm, width,
           color=COLOURS["accent"], label=f"Loads served (max {max(served)})")
    ax.bar([i + 1.5 * width for i in x], deadhead_norm, width,
           color=COLOURS["off"], label="Lower deadhead (inverted)")
    ax.set_xticks(x)
    ax.set_xticklabels(depots)
    ax.set_ylabel("Normalised score (0-100, higher = better)")
    ax.set_title(f"R2 — Depot location comparison "
                 f"(same 7-van fleet, {d['inputs']['n_loads']} real Frigo loads)")
    ax.legend(loc="upper right", fontsize=8, frameon=False)
    # Add the raw margin numbers as annotations
    for i, m in enumerate(margins):
        ax.annotate(f"€{m:.0f}", (i - 1.5 * width, margin_norm[i] + 2),
                    ha="center", fontsize=8, fontweight="bold")
    _save(plt, fig, "r2_depot_comparison.png")

    # 2. Depot map — each candidate annotated with its margin
    from app.data.romania_cities import ROMANIA_CITIES
    fig, ax = plt.subplots(figsize=(8, 6))
    _add_romania_backdrop(ax)
    winner = d["results"]["winners"]["by_margin"]
    for r in rows:
        c = ROMANIA_CITIES.get(r["depot"])
        if not c:
            continue
        is_winner = r["depot"] == winner
        size = 350 if is_winner else 180
        colour = COLOURS["on"] if is_winner else COLOURS["accent"]
        edge = "#0f172a"
        ax.scatter([c.lon], [c.lat], marker="*", s=size, c=colour,
                   edgecolors=edge, linewidths=1.2 if is_winner else 0.6, zorder=10)
        label = f"{r['depot']}\n€{r['total_margin_eur']:.0f}"
        if is_winner:
            label += "  ★ best"
        ax.annotate(label, (c.lon, c.lat), textcoords="offset points",
                    xytext=(10, 10), fontsize=9,
                    fontweight="bold" if is_winner else "normal")
    ax.set_title(f"R2 — Best depot by total margin (7-van fleet, real Frigo)")
    _save(plt, fig, "r2_depot_margin_map.png")


# ---------------------------------------------------------------------------
# R3
# ---------------------------------------------------------------------------

def chart_r3(plt) -> None:
    path = EXP_DIR / "exp_r3.json"
    if not path.exists():
        print(f"  [skip] {path.name} missing", file=sys.stderr)
        return
    d = json.loads(path.read_text())
    rows = d["results"]["per_config"]

    # 1. Marginal return curve — single-Cluj path
    single = sorted(
        [r for r in rows if r["label"].startswith("single-cluj")],
        key=lambda x: x["n_vans"],
    )
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6.5), sharex=True)
    xs = [r["n_vans"] for r in single]
    ax1.plot(xs, [r["total_margin_eur"] for r in single],
             marker="o", color=COLOURS["on"], linewidth=2)
    for r in single:
        ax1.annotate(f"€{r['total_margin_eur']:.0f}",
                     (r["n_vans"], r["total_margin_eur"]),
                     textcoords="offset points", xytext=(0, 8),
                     ha="center", fontsize=9)
    ax1.set_ylabel("Total fleet margin (€)")
    ax1.set_title("R3 — Diminishing returns: single-Cluj depot scaling")

    ax2.plot(xs, [r["margin_per_van"] for r in single],
             marker="s", color=COLOURS["warn"], linewidth=2)
    for r in single:
        ax2.annotate(f"€{r['margin_per_van']:.0f}/van",
                     (r["n_vans"], r["margin_per_van"]),
                     textcoords="offset points", xytext=(0, 8),
                     ha="center", fontsize=9)
    ax2.set_xlabel("Fleet size (vans)")
    ax2.set_ylabel("Margin per van (€)")
    ax2.axhline(y=100, color=COLOURS["danger"], linestyle="--", linewidth=1,
                label="diminishing-returns threshold (€100/van)")
    ax2.legend(loc="upper right", frameon=False, fontsize=9)
    _save(plt, fig, "r3_marginal_return.png")

    # 2. Single vs multi at fleet=14
    msd = d["results"]["multi_vs_single_at_fleet_14"]
    if msd:
        fig, ax = plt.subplots(figsize=(7, 4.4))
        labels = ["Single-Cluj 14 vans", "Dual: Cluj + Bucureşti 14 vans"]
        vals = [msd["single_margin"], msd["dual_margin"]]
        colours = [COLOURS["off"], COLOURS["on"]]
        bars = ax.bar(labels, vals, color=colours,
                      edgecolor="#0f172a", linewidth=0.4)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + max(vals) * 0.02,
                    f"€{v:.0f}", ha="center", fontsize=11, fontweight="bold")
        ax.set_ylabel("Total fleet margin (€)")
        lift = msd.get("margin_lift_pct")
        lift_str = f" (+{lift:.0f}%)" if lift is not None else ""
        ax.set_title(f"R3 — Same fleet size, different depot strategy{lift_str}")
        _save(plt, fig, "r3_single_vs_multi_depot.png")

    # 3. Per-depot contribution — bar of each 21-van config's loads served
    triples = [r for r in rows if r["n_depots"] == 3]
    if triples:
        fig, ax = plt.subplots(figsize=(8, 4.4))
        labels = [", ".join(r["depots"]) for r in triples]
        margins = [r["total_margin_eur"] for r in triples]
        served = [r["loads_served"] for r in triples]
        x = range(len(triples))
        width = 0.4
        ax.bar([i - width / 2 for i in x], margins, width,
               color=COLOURS["on"], label="Margin (€)")
        ax2 = ax.twinx()
        ax2.bar([i + width / 2 for i in x], served, width,
                color=COLOURS["accent"], label="Loads served")
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, fontsize=8, rotation=8, ha="right")
        ax.set_ylabel("Margin (€)", color=COLOURS["on"])
        ax2.set_ylabel("Loads served", color=COLOURS["accent"])
        ax.set_title("R3 — 21-van triple-depot configurations: which trio works best?")
        for i, (m, s) in enumerate(zip(margins, served)):
            ax.text(i - width / 2, m + max(margins) * 0.02, f"€{m:.0f}",
                    ha="center", fontsize=9)
            ax2.text(i + width / 2, s + max(served) * 0.02, f"{s}",
                     ha="center", fontsize=9)
        _save(plt, fig, "r3_per_depot_contribution.png")


# ---------------------------------------------------------------------------
# R4
# ---------------------------------------------------------------------------

def chart_r4(plt) -> None:
    path = EXP_DIR / "exp_r4.json"
    if not path.exists():
        print(f"  [skip] {path.name} missing", file=sys.stderr)
        return
    d = json.loads(path.read_text())
    grid = d["results"]["grid"]
    fleet_sizes = d["inputs"]["fleet_sizes"]
    n_depots_range = d["inputs"]["n_depots_range"]

    # Build 2-D matrices indexed by (n_depots, fleet_size) -> value
    margin = [[0.0] * len(fleet_sizes) for _ in n_depots_range]
    per_van = [[0.0] * len(fleet_sizes) for _ in n_depots_range]
    for c in grid:
        i = n_depots_range.index(c["n_depots"])
        j = fleet_sizes.index(c["n_vans"])
        margin[i][j] = c["total_margin_eur"]
        per_van[i][j] = c["margin_per_van"]

    optimum = d["results"]["optimum_cell"]
    best_roi = d["results"]["best_roi_cell"]

    # 1. Profit heatmap — total margin
    fig, ax = plt.subplots(figsize=(9, 4.4))
    im = ax.imshow(margin, cmap="Greens", aspect="auto")
    ax.set_xticks(range(len(fleet_sizes)))
    ax.set_xticklabels(fleet_sizes)
    ax.set_yticks(range(len(n_depots_range)))
    ax.set_yticklabels([f"{n} depot{'s' if n > 1 else ''}" for n in n_depots_range])
    ax.set_xlabel("Fleet size (vans)")
    ax.set_title(f"R4 — Total margin €  (depot priority: "
                 f"{', '.join(d['inputs']['depot_priority'][:4])})")
    for i, row in enumerate(margin):
        for j, v in enumerate(row):
            ax.text(j, i, f"€{v:.0f}", ha="center", va="center",
                    fontsize=9,
                    color="white" if v > max(map(max, margin)) * 0.6 else "#0f172a")
    # Mark the optimum
    if optimum:
        oi = n_depots_range.index(optimum["n_depots"])
        oj = fleet_sizes.index(optimum["n_vans"])
        ax.add_patch(plt.Rectangle((oj - 0.5, oi - 0.5), 1, 1,
                                    fill=False, edgecolor=COLOURS["primary"],
                                    linewidth=3))
        ax.annotate(f"OPTIMUM\n€{optimum['total_margin_eur']:.0f}",
                    (oj, oi), textcoords="offset points", xytext=(0, -45),
                    ha="center", fontsize=9, fontweight="bold",
                    color=COLOURS["primary"])
    plt.colorbar(im, ax=ax, label="Total margin (€)")
    _save(plt, fig, "r4_profit_heatmap.png")

    # 2. Profit vs fleet — one curve per n_depots
    fig, ax = plt.subplots(figsize=(9, 4.6))
    for i, n_depots in enumerate(n_depots_range):
        ys = margin[i]
        ax.plot(fleet_sizes, ys, marker="o",
                label=f"{n_depots} depot{'s' if n_depots > 1 else ''}",
                linewidth=2)
    ax.set_xlabel("Fleet size (vans)")
    ax.set_ylabel("Total fleet margin (€)")
    ax.set_title("R4 — Profit vs fleet size, by number of depots")
    ax.legend(loc="lower right", frameon=False)
    ax.grid(True, alpha=0.3)
    knees = d["results"]["diminishing_returns_knees_per_depot_count"]
    for nd_str, k in knees.items():
        if k:
            ax.annotate(
                f"knee: {k['from_size']}-{k['to_size']} vans @ {nd_str} depot",
                xy=(k["to_size"], margin[n_depots_range.index(int(nd_str))]
                                         [fleet_sizes.index(k["to_size"])]),
                xytext=(0, 12), textcoords="offset points",
                ha="center", fontsize=7, color="#7f1d1d",
                arrowprops=dict(arrowstyle="-", color="#7f1d1d", alpha=0.5),
            )
    _save(plt, fig, "r4_profit_vs_fleet_curves.png")

    # 3. Margin per van — diminishing returns visualised
    fig, ax = plt.subplots(figsize=(9, 4.6))
    for i, n_depots in enumerate(n_depots_range):
        ys = per_van[i]
        ax.plot(fleet_sizes, ys, marker="s",
                label=f"{n_depots} depot{'s' if n_depots > 1 else ''}",
                linewidth=2)
    ax.set_xlabel("Fleet size (vans)")
    ax.set_ylabel("Margin per van (€)")
    ax.set_title("R4 — ROI per van: when does the next van cost more than it earns?")
    ax.axhline(y=d["inputs"]["knee_threshold_eur"], color=COLOURS["danger"],
               linestyle="--", linewidth=1,
               label=f"€{d['inputs']['knee_threshold_eur']} ROI floor")
    if best_roi:
        ax.scatter([best_roi["n_vans"]], [best_roi["margin_per_van"]],
                   marker="*", s=300, color=COLOURS["primary"], zorder=10,
                   edgecolors="#0f172a", linewidth=1)
        ax.annotate(
            f"BEST ROI\n€{best_roi['margin_per_van']:.0f}/van\n"
            f"({best_roi['n_vans']} vans, {best_roi['n_depots']} depot)",
            (best_roi["n_vans"], best_roi["margin_per_van"]),
            textcoords="offset points", xytext=(10, -10),
            fontsize=9, fontweight="bold", color=COLOURS["primary"],
        )
    ax.legend(loc="upper right", frameon=False)
    ax.grid(True, alpha=0.3)
    _save(plt, fig, "r4_margin_per_van.png")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    plt = _setup_mpl()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    print("[123cargo-charts] rendering figures …", file=sys.stderr)
    chart_r1(plt)
    chart_r2(plt)
    chart_r3(plt)
    chart_r4(plt)
    print("[123cargo-charts] done.", file=sys.stderr)


if __name__ == "__main__":
    main()
