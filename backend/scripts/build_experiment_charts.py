"""Read the four experiment JSONs and emit the thesis figures.

Outputs PNGs under `backend/docs/figures/experiments/` and a flat
`backend/docs/experiments_summary.csv` for thesis LaTeX import.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
EXP_DIR = BACKEND_DIR / "docs" / "experiments"
FIG_DIR = BACKEND_DIR / "docs" / "figures" / "experiments"


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


def chart_exp_a(plt) -> None:
    data = json.loads((EXP_DIR / "exp_a.json").read_text())
    d = data["delta"]
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    metrics = ["Total margin (€)", "Empty km", "Loaded km"]
    baseline_vals = [d["margin_baseline_eur"], d["empty_km_baseline"], d["loaded_km_baseline"]]
    treat_vals = [d["margin_treatment_eur"], d["empty_km_treatment"], d["loaded_km_treatment"]]
    x = range(len(metrics))
    w = 0.35
    ax.bar([i - w/2 for i in x], baseline_vals, w, label="Naive nearest-pickup", color="#94a3b8")
    ax.bar([i + w/2 for i in x], treat_vals, w, label="Route planner (chains on)", color="#10b981")
    for i, (b, t) in enumerate(zip(baseline_vals, treat_vals)):
        ax.text(i - w/2, b, f"{b:.0f}", ha="center", va="bottom", fontsize=9)
        ax.text(i + w/2, t, f"{t:.0f}", ha="center", va="bottom", fontsize=9, weight="bold")
    ax.set_xticks(list(x))
    ax.set_xticklabels(metrics)
    ax.set_title(
        f"Experiment A — {d['margin_lift_pct']:+.1f}% margin lift, "
        f"{d['deadhead_delta_pp']:+.1f} pp deadhead",
        loc="left", weight="bold",
    )
    ax.legend(loc="upper right")
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    _save(plt, fig, "exp_a_margin_lift.png")


def chart_exp_b(plt) -> None:
    data = json.loads((EXP_DIR / "exp_b.json").read_text())
    b, t, d = data["baseline"], data["treatment"], data["delta"]
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    labels = ["Gross margin", "Fines (avoided by treatment)", "NET margin after fines"]
    baseline_vals = [b["gross_margin_eur"], b["total_fine_exposure_eur"], b["net_margin_after_fines_eur"]]
    treat_vals = [t["gross_margin_eur"], 0, t["net_margin_after_fines_eur"]]
    x = range(len(labels))
    w = 0.35
    bars_b = ax.bar([i - w/2 for i in x], baseline_vals, w,
                     label="Baseline (no compliance gate)",
                     color=["#fbbf24", "#ef4444", "#94a3b8"])
    bars_t = ax.bar([i + w/2 for i in x], treat_vals, w,
                     label="Treatment (compliance gate ON)",
                     color="#10b981")
    for i, (bv, tv) in enumerate(zip(baseline_vals, treat_vals)):
        ax.text(i - w/2, bv if bv >= 0 else bv - 200, f"€{bv:.0f}",
                ha="center", va="bottom" if bv >= 0 else "top", fontsize=9)
        ax.text(i + w/2, tv, f"€{tv:.0f}", ha="center", va="bottom", fontsize=9, weight="bold")
    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("€ (positive = profit, negative = loss)")
    ax.set_title(
        f"Experiment B — {d['violations_avoided']} violations / "
        f"€{d['fines_avoided_eur']:.0f} in fines avoided",
        loc="left", weight="bold",
    )
    ax.legend(loc="lower left", fontsize=8)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    _save(plt, fig, "exp_b_compliance_value.png")


def chart_exp_c(plt) -> None:
    data = json.loads((EXP_DIR / "exp_c.json").read_text())
    d = data["delta"]
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))

    # Left: margin + utilisation comparison
    metrics = ["Net margin (€)", "Utilisation (%)", "Deadhead (%)"]
    baseline_vals = [
        d["margin_baseline_eur"], d["utilisation_baseline_pct"], d["deadhead_baseline_pct"],
    ]
    treat_vals = [
        d["margin_treatment_eur"], d["utilisation_treatment_pct"], d["deadhead_treatment_pct"],
    ]
    ax = axs[0]
    x = range(len(metrics))
    w = 0.35
    ax.bar([i - w/2 for i in x], baseline_vals, w, label="Customer-only", color="#94a3b8")
    ax.bar([i + w/2 for i in x], treat_vals, w, label="Customer + broker", color="#a78bfa")
    for i, (b, t) in enumerate(zip(baseline_vals, treat_vals)):
        ax.text(i - w/2, b, f"{b:.1f}", ha="center", va="bottom", fontsize=9)
        ax.text(i + w/2, t, f"{t:.1f}", ha="center", va="bottom", fontsize=9, weight="bold")
    ax.set_xticks(list(x))
    ax.set_xticklabels(metrics, fontsize=9)
    ax.set_title("Headline KPIs", loc="left", weight="bold")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y", linestyle=":", alpha=0.4)

    # Right: load served breakdown
    ax2 = axs[1]
    cats = ["Customer\nbaseline", "Customer\ntreatment", "Broker\ntreatment"]
    vals = [
        d["customer_served_baseline"],
        d["customer_served_treatment"],
        d["broker_served_treatment"],
    ]
    colors = ["#94a3b8", "#10b981", "#a78bfa"]
    bars = ax2.bar(cats, vals, color=colors)
    for b, v in zip(bars, vals):
        ax2.text(b.get_x() + b.get_width() / 2, v, str(v),
                 ha="center", va="bottom", fontsize=10, weight="bold")
    ax2.set_ylabel("# loads served")
    ax2.set_title(
        f"Loads served  ({d['chains_with_broker_load']} chain(s) include a broker leg)",
        loc="left", weight="bold",
    )
    ax2.grid(axis="y", linestyle=":", alpha=0.4)

    fig.suptitle(
        f"Experiment C — {d['margin_lift_pct']:+.1f}% margin lift from broker freight, "
        f"customer SLA preserved", weight="bold",
    )
    fig.tight_layout()
    _save(plt, fig, "exp_c_broker_lift.png")


def chart_exp_d(plt) -> None:
    data = json.loads((EXP_DIR / "exp_d.json").read_text())
    pts = data["points"]
    Ns = [p["fleet_size"] for p in pts]
    margins = [p["total_margin_eur"] for p in pts]
    per_van = [p["margin_per_van_eur"] for p in pts]
    deadhead = [p["deadhead_pct"] for p in pts]
    util = [p["fleet_utilization_pct"] for p in pts]

    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))

    ax = axs[0]
    ax.plot(Ns, margins, marker="o", color="#10b981", label="Total fleet margin €", linewidth=2)
    ax.set_xlabel("Fleet size N")
    ax.set_ylabel("€", color="#10b981")
    ax.tick_params(axis="y", labelcolor="#10b981")
    ax2 = ax.twinx()
    ax2.plot(Ns, per_van, marker="s", color="#a78bfa", label="Margin per van €", linewidth=2)
    ax2.set_ylabel("€ per van", color="#a78bfa")
    ax2.tick_params(axis="y", labelcolor="#a78bfa")
    ax.spines["right"].set_visible(True)
    ax.set_title("Revenue scaling — diminishing returns once load supply is exhausted",
                 loc="left", weight="bold")
    ax.set_xticks(Ns)

    ax3 = axs[1]
    ax3.plot(Ns, deadhead, marker="o", color="#f59e0b", label="Deadhead %")
    ax3.plot(Ns, util, marker="s", color="#3b82f6", label="Fleet utilisation %")
    ax3.set_xlabel("Fleet size N")
    ax3.set_ylabel("%")
    ax3.set_xticks(Ns)
    ax3.set_title("Operational metrics — utilisation drops as load pool saturates",
                  loc="left", weight="bold")
    ax3.legend(loc="best")
    ax3.grid(linestyle=":", alpha=0.4)

    _save(plt, fig, "exp_d_fleet_scaling.png")


def write_csv() -> None:
    out = BACKEND_DIR / "docs" / "experiments_summary.csv"
    rows = []
    a = json.loads((EXP_DIR / "exp_a.json").read_text())["delta"]
    rows.append([
        "A — margin lift",
        a["margin_baseline_eur"], a["margin_treatment_eur"], a["margin_lift_eur"],
        a["margin_lift_pct"], a["deadhead_baseline_pct"], a["deadhead_treatment_pct"],
        a["utilisation_baseline_pct"], a["utilisation_treatment_pct"],
    ])
    b = json.loads((EXP_DIR / "exp_b.json").read_text())
    rows.append([
        "B — compliance value",
        b["baseline"]["net_margin_after_fines_eur"],
        b["treatment"]["net_margin_after_fines_eur"],
        b["delta"]["net_margin_lift_eur"],
        None, None, None, None, None,
    ])
    c = json.loads((EXP_DIR / "exp_c.json").read_text())["delta"]
    rows.append([
        "C — broker lift",
        c["margin_baseline_eur"], c["margin_treatment_eur"], c["margin_lift_eur"],
        c["margin_lift_pct"], c["deadhead_baseline_pct"], c["deadhead_treatment_pct"],
        c["utilisation_baseline_pct"], c["utilisation_treatment_pct"],
    ])

    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "experiment", "baseline_eur", "treatment_eur", "lift_eur", "lift_pct",
            "deadhead_baseline_pct", "deadhead_treatment_pct",
            "utilisation_baseline_pct", "utilisation_treatment_pct",
        ])
        for r in rows:
            w.writerow(r)
    print(f"  wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)


def main() -> None:
    plt = _setup_mpl()
    chart_exp_a(plt)
    chart_exp_b(plt)
    chart_exp_c(plt)
    chart_exp_d(plt)
    write_csv()
    print(f"\n[charts] done. Open {FIG_DIR.relative_to(BACKEND_DIR.parent)}/", file=sys.stderr)


if __name__ == "__main__":
    main()
