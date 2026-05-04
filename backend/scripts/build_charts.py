"""Turn the JSON output of `scripts/run_ablation.py` into thesis-ready charts + CSV.

  python -m scripts.build_charts                          # reads docs/ablation.json
  python -m scripts.build_charts --in <path>  --out <dir>

Produces (under --out, default `docs/figures`):
  - accuracy_per_variant.png      bar chart, primary headline figure
  - confusion_matrix_grid.png     5 mini-CMs side-by-side
  - per_rule_accuracy.png         heatmap, rule_category × variant
  - cost_vs_accuracy.png          scatter — does spending more LLM money help?
  - latency_distribution.png      box plot of per-call wall_ms per variant
  - sanity_overrides.png          bar chart of how often the sanity layer fired
And `docs/results.csv` — per-variant numbers in a flat table for the thesis LaTeX.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = BACKEND_DIR / "docs"
DEFAULT_INPUT = DOCS_DIR / "ablation.json"
DEFAULT_OUTPUT = DOCS_DIR / "figures"

# Per-variant colour scheme — kept consistent across all charts so the
# thesis figures read together.
COLOURS = {
    "V0": "#94a3b8",  # slate-400 — neutral baseline
    "V1": "#ef4444",  # red-500 — vanilla LLM (worst expected)
    "V2": "#f59e0b",  # amber-500 — prompt only
    "V3": "#3b82f6",  # blue-500 — sanity only
    "V4": "#10b981",  # emerald-500 — full pipeline
}


def _load(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"[charts] input not found: {path}\n  run `python -m scripts.run_ablation` first.")
    return json.loads(path.read_text())


def _setup_matplotlib():
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


def _save(plt, fig, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    print(f"  wrote {out.relative_to(BACKEND_DIR)}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 1. accuracy bar chart
# ---------------------------------------------------------------------------

_SHORT_LABELS = {
    "V0": "Mock",
    "V1": "Vanilla LLM",
    "V2": "LLM\n+ prompt",
    "V3": "LLM\n+ sanity",
    "V4": "Full\npipeline",
}


def chart_accuracy(plt, results: list[dict], out: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    variants = [r["variant"] for r in results]
    accs = [r["accuracy"] * 100 for r in results]
    bars = ax.bar(variants, accs, color=[COLOURS.get(v, "#888") for v in variants],
                  width=0.65)
    for b, a in zip(bars, accs):
        ax.text(b.get_x() + b.get_width() / 2, a + 0.8, f"{a:.1f}%",
                ha="center", va="bottom", fontsize=11, weight="bold")
    ax.set_ylim(0, 110)
    ax.set_ylabel("Accuracy (%)")
    ax.set_title("Compliance accuracy per pipeline variant", loc="left", weight="bold")
    ax.set_xticks(range(len(variants)))
    ax.set_xticklabels([f"{v}\n{_SHORT_LABELS.get(v, '')}" for v in variants],
                       fontsize=9)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    _save(plt, fig, out)


# ---------------------------------------------------------------------------
# 2. confusion matrix grid
# ---------------------------------------------------------------------------

def chart_confusion_grid(plt, results: list[dict], out: Path) -> None:
    n = len(results)
    fig, axs = plt.subplots(1, n, figsize=(2.6 * n, 2.8), squeeze=False)
    axs = axs[0]
    for ax, r in zip(axs, results):
        cm = r["confusion"]
        # 2x2 grid: rows = expected (compliant, blocked), cols = actual (compliant, blocked)
        # TP = expected ✓, actual ✓; FN = expected ✓, actual ✗; FP = expected ✗, actual ✓; TN = expected ✗, actual ✗
        m = [
            [cm.get("TP", 0), cm.get("FN", 0)],
            [cm.get("FP", 0), cm.get("TN", 0)],
        ]
        im = ax.imshow(m, cmap="Blues", aspect="auto", vmin=0)
        ax.set_xticks([0, 1])
        ax.set_yticks([0, 1])
        ax.set_xticklabels(["✓ compliant", "✗ blocked"], fontsize=8)
        ax.set_yticklabels(["✓ compliant", "✗ blocked"], fontsize=8)
        ax.set_xlabel("actual")
        ax.set_ylabel("expected")
        for i in range(2):
            for j in range(2):
                v = m[i][j]
                colour = "white" if v > max(max(m)) / 2 else "black"
                ax.text(j, i, str(v), ha="center", va="center", color=colour, weight="bold")
        ax.set_title(r["variant"], color=COLOURS.get(r["variant"], "#000"), weight="bold")
    fig.suptitle("Per-variant confusion matrices", weight="bold")
    fig.tight_layout()
    _save(plt, fig, out)


# ---------------------------------------------------------------------------
# 3. per-rule accuracy heatmap
# ---------------------------------------------------------------------------

def chart_per_rule(plt, results: list[dict], out: Path) -> None:
    rule_order = ["temperature", "pharma_logger", "chemicals_quarantine",
                  "forbidden_prior_cargo", "wash_override", "clean_path", "multi_blocker"]
    variants = [r["variant"] for r in results]
    matrix = []
    for rule in rule_order:
        row = []
        for r in results:
            stats = r["per_rule"].get(rule, {})
            row.append(stats.get("accuracy", 0.0) * 100)
        matrix.append(row)

    fig, ax = plt.subplots(figsize=(0.9 * len(variants) + 3, 0.5 * len(rule_order) + 2))
    im = ax.imshow(matrix, cmap="RdYlGn", aspect="auto", vmin=0, vmax=100)
    ax.set_xticks(range(len(variants)))
    ax.set_xticklabels(variants, fontsize=10, weight="bold")
    ax.set_yticks(range(len(rule_order)))
    ax.set_yticklabels([r.replace("_", " ") for r in rule_order], fontsize=9)
    for i in range(len(rule_order)):
        for j in range(len(variants)):
            v = matrix[i][j]
            colour = "white" if (v < 50 or v > 90) else "black"
            ax.text(j, i, f"{v:.0f}", ha="center", va="center", color=colour, fontsize=9)
    ax.set_title("Per-rule accuracy (%)", loc="left", weight="bold")
    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("accuracy %")
    _save(plt, fig, out)


# ---------------------------------------------------------------------------
# 4. cost vs. accuracy scatter
# ---------------------------------------------------------------------------

def chart_cost_vs_accuracy(plt, results: list[dict], out: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 4))
    for r in results:
        short = _SHORT_LABELS.get(r["variant"], "").replace("\n", " ")
        ax.scatter(
            r["estimated_cost_usd"], r["accuracy"] * 100,
            color=COLOURS.get(r["variant"], "#888"),
            s=200, label=f"{r['variant']} — {short}",
            edgecolor="black", linewidth=0.6, zorder=3,
        )
        ax.annotate(r["variant"], (r["estimated_cost_usd"], r["accuracy"] * 100),
                    textcoords="offset points", xytext=(8, 4), fontsize=9, weight="bold")
    ax.set_xlabel("Estimated cost per full eval (USD, off-tier Gemini Flash pricing)")
    ax.set_ylabel("Accuracy (%)")
    ax.set_title("Does spending more LLM tokens raise accuracy?", loc="left", weight="bold")
    ax.set_ylim(0, 105)
    ax.grid(linestyle=":", alpha=0.4)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.9)
    _save(plt, fig, out)


# ---------------------------------------------------------------------------
# 5. latency distribution box plot
# ---------------------------------------------------------------------------

def chart_latency(plt, results: list[dict], out: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4))
    data, labels, colors = [], [], []
    for r in results:
        wall = [row["wall_ms"] for row in r["rows"] if row.get("wall_ms") is not None]
        if wall:
            data.append(wall)
            labels.append(r["variant"])
            colors.append(COLOURS.get(r["variant"], "#888"))
    bp = ax.boxplot(data, labels=labels, patch_artist=True, showfliers=True,
                    medianprops={"color": "black", "linewidth": 1.4})
    for patch, c in zip(bp["boxes"], colors):
        patch.set_facecolor(c)
        patch.set_alpha(0.7)
    ax.set_ylabel("Per-call wall time (ms)")
    ax.set_title("Latency distribution per variant (warm cache included)", loc="left", weight="bold")
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    _save(plt, fig, out)


# ---------------------------------------------------------------------------
# 6. sanity-override frequency
# ---------------------------------------------------------------------------

def chart_sanity(plt, results: list[dict], out: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 3.5))
    variants = [r["variant"] for r in results]
    overrides = [r["sanity_corrections"] for r in results]
    total = max(r.get("confusion", {}).get("TP", 0) + r.get("confusion", {}).get("TN", 0) +
                r.get("confusion", {}).get("FP", 0) + r.get("confusion", {}).get("FN", 0)
                for r in results)
    bars = ax.bar(variants, overrides, color=[COLOURS.get(v, "#888") for v in variants])
    for b, v in zip(bars, overrides):
        ax.text(b.get_x() + b.get_width() / 2, v + total * 0.005, str(v),
                ha="center", va="bottom", fontsize=10, weight="bold")
    ax.set_ylabel(f"Sanity-layer corrections (out of {total})")
    ax.set_title("Where the deterministic layer overrode the LLM", loc="left", weight="bold")
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    _save(plt, fig, out)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def write_csv(results: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "variant", "label", "accuracy_pct", "precision_pct", "recall_pct", "f1",
            "TP", "TN", "FP", "FN",
            "llm_calls", "cache_hits", "input_tokens", "output_tokens",
            "estimated_cost_usd", "total_wall_ms", "sanity_corrections",
        ])
        for r in results:
            cm = r["confusion"]
            w.writerow([
                r["variant"], r["label"], f"{r['accuracy']*100:.2f}",
                f"{r['precision']*100:.2f}", f"{r['recall']*100:.2f}", f"{r['f1']:.4f}",
                cm.get("TP", 0), cm.get("TN", 0), cm.get("FP", 0), cm.get("FN", 0),
                r["llm_calls"], r["cache_hits"], r["input_tokens"], r["output_tokens"],
                f"{r['estimated_cost_usd']:.6f}", r["total_wall_ms"], r["sanity_corrections"],
            ])
    print(f"  wrote {out.relative_to(BACKEND_DIR)}", file=sys.stderr)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="input", default=str(DEFAULT_INPUT))
    parser.add_argument("--out", dest="output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    bundle = _load(Path(args.input))
    results = bundle["results"]
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    plt = _setup_matplotlib()
    chart_accuracy(plt, results, out_dir / "accuracy_per_variant.png")
    chart_confusion_grid(plt, results, out_dir / "confusion_matrix_grid.png")
    chart_per_rule(plt, results, out_dir / "per_rule_accuracy.png")
    chart_cost_vs_accuracy(plt, results, out_dir / "cost_vs_accuracy.png")
    chart_latency(plt, results, out_dir / "latency_distribution.png")
    chart_sanity(plt, results, out_dir / "sanity_overrides.png")
    write_csv(results, DOCS_DIR / "results.csv")

    print(f"\n[charts] done. Open {out_dir.relative_to(BACKEND_DIR)} to inspect.", file=sys.stderr)


if __name__ == "__main__":
    main()
