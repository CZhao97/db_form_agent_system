from __future__ import annotations

import json
import shutil
import sys
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
import pandas as pd
import seaborn as sns
try:
    from scipy.stats import gaussian_kde
except Exception:
    gaussian_kde = None

# ----------------------------------------------------------------------------
# Visual polish script for DB-Curator NMI figures.
#
# Main goals:
#   1. Use consistent typography, spacing, and colors across all figures.
#   2. Reduce overlap and crowding.
#   3. Make panel hierarchy more consistent.
#   4. Enlarge labels in dense figures.
#   5. Keep output filenames unchanged so the current LaTeX links still work.
# ----------------------------------------------------------------------------

ROOT = Path("/home/chen/GNPS_SIM/agent/db_form_agent_system")
FIG_DIR = ROOT / "manuscript" / "figures"
LATEX_FIG_DIR = ROOT / "manuscript" / "latex" / "generated_figs"
EVAL_DIR = ROOT / "manuscript" / "evaluation_plan"
sys.path.insert(0, str(EVAL_DIR))

TOPIC_ORDER = [
    "dbp",
    "blood_exposome",
    "drug_compounds",
    "human_endogenous_metabolites",
    "microbial_natural_products",
]

TOPIC_LABEL = {
    "dbp": "DBP",
    "blood_exposome": "Blood",
    "drug_compounds": "Drug",
    "human_endogenous_metabolites": "Endogenous",
    "microbial_natural_products": "Microbial NP",
}

COL = {
    "ink": "#1A1A1A",
    "muted": "#5A6672",
    "grid": "#E9EEF2",
    "paper": "#5B8DB8",
    "paper_dark": "#3F6C95",
    "paper_light": "#A9C6DC",
    "verify": "#D99A51",
    "verify_dark": "#B9782B",
    "accept": "#7FB39A",
    "warn": "#E5C46D",
    "fail": "#C96B6B",
    "llm": "#A4B1BC",
    "llm_light": "#D5DEE5",
    "novel": "#68A36E",
    "outline": "#B8C4CD",
    "soft_bg": "#F7FAFC",
    "white": "#FFFFFF",
}

TOPIC_COLORS = {
    "dbp": "#638FB5",
    "blood_exposome": "#67AFC0",
    "drug_compounds": "#7CB989",
    "human_endogenous_metabolites": "#9B88C9",
    "microbial_natural_products": "#D8A65E",
}

sns.set_theme(style="ticks", context="paper")
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 7.2,
    "axes.titlesize": 8.3,
    "axes.titleweight": "bold",
    "axes.labelsize": 7.1,
    "xtick.labelsize": 6.4,
    "ytick.labelsize": 6.4,
    "legend.fontsize": 6.3,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.80,
    "xtick.major.width": 0.75,
    "ytick.major.width": 0.75,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "savefig.transparent": False,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})


# ------------------------------- utils -------------------------------------

def ensure_dirs() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    LATEX_FIG_DIR.mkdir(parents=True, exist_ok=True)


def save(fig: plt.Figure, stem: str) -> None:
    png = FIG_DIR / f"{stem}.png"
    pdf = FIG_DIR / f"{stem}.pdf"

    fig.savefig(
        png,
        dpi=600,
        bbox_inches="tight",
        pad_inches=0.02,
        facecolor="white",
    )
    fig.savefig(
        pdf,
        bbox_inches="tight",
        pad_inches=0.02,
        facecolor="white",
    )

    shutil.copy2(png, LATEX_FIG_DIR / png.name)
    shutil.copy2(pdf, LATEX_FIG_DIR / pdf.name)
    plt.close(fig)
    print("wrote", png)


def style_axis(ax, axis="y") -> None:
    ax.grid(
        axis=axis,
        color=COL["grid"],
        linewidth=0.55,
        alpha=0.95,
        zorder=0,
    )
    ax.set_axisbelow(True)
    ax.tick_params(length=0, pad=2)

    for side in ["left", "bottom"]:
        if side in ax.spines:
            ax.spines[side].set_color(COL["outline"])
            ax.spines[side].set_linewidth(0.8)


def panel(ax, letter: str) -> None:
    ax.text(
        -0.09,
        1.08,
        letter,
        transform=ax.transAxes,
        fontsize=9.4,
        fontweight="bold",
        color=COL["ink"],
        va="top",
        ha="left",
        clip_on=False,
    )


def add_suptitle(fig, text: str) -> None:
    fig.suptitle(
        text,
        x=0.02,
        y=0.976,
        ha="left",
        fontsize=7.6,
        fontweight="bold",
        color=COL["ink"],
    )


def inline_key(
    ax,
    entries,
    x0=0.02,
    y=0.98,
    dx=0.23,
    size=0.028,
    fontsize=5.8,
):
    for i, (label, color) in enumerate(entries):
        x = x0 + i * dx
        ax.add_patch(
            patches.Rectangle(
                (x, y - size * 0.72),
                size,
                size,
                transform=ax.transAxes,
                facecolor=color,
                edgecolor="white",
                linewidth=0.40,
                clip_on=False,
            )
        )
        ax.text(
            x + size + 0.008,
            y - size * 0.20,
            label,
            transform=ax.transAxes,
            ha="left",
            va="center",
            fontsize=fontsize,
            color=COL["ink"],
            clip_on=False,
        )


def _violin_with_points(ax, groups, labels, colors, ylabel: str, title: str) -> None:
    parts = ax.violinplot(groups, showmedians=True, widths=0.74)

    for body, color in zip(parts["bodies"], colors):
        body.set_facecolor(color)
        body.set_edgecolor("white")
        body.set_alpha(0.70)
        body.set_linewidth(0.55)

    for key in ("cbars", "cmins", "cmaxes", "cmedians"):
        parts[key].set_color("#324554")
        parts[key].set_linewidth(0.85)

    ax.set_xticks(
        np.arange(1, len(labels) + 1),
        labels,
        rotation=18,
        ha="right",
    )
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left")
    style_axis(ax)


def arrow(ax, start, end, color="#60717F", lw=1.5, rad=0.0):
    arr = patches.FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=12,
        linewidth=lw,
        color=color,
        connectionstyle=f"arc3,rad={rad}",
        transform=ax.transAxes,
    )
    ax.add_patch(arr)


def short_gate(text: str, max_chars: int = 36) -> str:
    text = str(text or "").replace("The ", "").replace("the ", "")
    text = text.replace("chemical entity", "entity")
    text = text.replace("must be ", "").replace("must ", "")
    text = text.replace("evidence that ", "").strip(". ")

    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "..."

    return "\n".join(textwrap.wrap(text, width=17))


def short_gate_line(text: str, max_chars: int = 44) -> str:
    text = str(text or "").replace("The ", "").replace("the ", "")
    text = text.replace("chemical entity", "entity")
    text = text.replace("must be ", "").replace("must ", "")
    text = text.replace("evidence that ", "").strip(". ")
    text = " ".join(text.split())

    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "..."

    return text


def _criteria_counts_from_json(raw: object) -> tuple[int, int]:
    try:
        items = json.loads(str(raw))
    except Exception:
        return (0, 0)

    if not isinstance(items, list):
        return (0, 0)

    total = 0
    solved = 0

    for item in items:
        if not isinstance(item, dict):
            continue

        total += 1
        status = str(item.get("status", "")).strip().lower()
        score = item.get("score")
        ok = status == "solved"

        if not ok and score is not None:
            try:
                ok = float(score) >= 0.5
            except Exception:
                ok = False

        solved += int(ok)

    return solved, total


def is_confirmed(value: object) -> bool:
    text = str(value or "").strip().lower()
    return (
        "confirmed" in text
        and "not confirmed" not in text
        and "insufficient" not in text
    )


# ---------------------------- figure 1 -------------------------------------

def figure1_architecture() -> None:
    fig, ax = plt.subplots(figsize=(9.4, 4.95))
    ax.set_axis_off()

    ax.text(
        0.01,
        0.985,
        "Scientific database construction by dynamic literature construction and predicate-state verification",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=11.0,
        fontweight="bold",
        color=COL["ink"],
    )
    ax.text(
        0.01,
        0.928,
        "The evidence corpus is built during the run; each candidate is then checked against an explicit acceptance contract.",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=6.5,
        color=COL["muted"],
    )

    def architecture_box(x, y, w, h, title, body, accent):
        ax.add_patch(
            patches.Rectangle(
                (x, y),
                w,
                h,
                transform=ax.transAxes,
                facecolor=COL["white"],
                edgecolor=COL["outline"],
                linewidth=1.0,
            )
        )
        ax.add_patch(
            patches.Rectangle(
                (x, y + h - 0.016),
                w,
                0.016,
                transform=ax.transAxes,
                facecolor=accent,
                edgecolor="none",
            )
        )
        ax.text(
            x + 0.014,
            y + h - 0.045,
            title,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=9.1,
            fontweight="bold",
            color=COL["ink"],
        )
        ax.text(
            x + 0.014,
            y + h - 0.094,
            body,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=7.6,
            color=COL["ink"],
            linespacing=1.18,
        )

    top_boxes = [
        (
            0.03,
            0.635,
            0.17,
            0.18,
            "User intent",
            "scope\nrubric\nrelease target",
            COL["paper_dark"],
        ),
        (
            0.245,
            0.635,
            0.225,
            0.18,
            "Dynamic literature set",
            "search\nseed expansion\nfollow-up retrieval",
            COL["paper"],
        ),
        (
            0.515,
            0.635,
            0.17,
            0.18,
            "Candidate queue",
            "detect\nnormalize\nrank",
            COL["paper_dark"],
        ),
        (
            0.73,
            0.635,
            0.225,
            0.18,
            "Predicate-state verification",
            "agent loop\nrubric gates\nprovenance-backed label",
            COL["verify"],
        ),
    ]

    for args in top_boxes:
        architecture_box(*args)

    for s, e in [
        ((0.203, 0.748), (0.242, 0.748)),
        ((0.473, 0.748), (0.512, 0.748)),
        ((0.688, 0.748), (0.727, 0.748)),
    ]:
        arrow(ax, s, e, color="#526370", lw=1.35)

    # left zoom: dynamic corpus
    ax.add_patch(
        patches.Rectangle(
            (0.055, 0.16),
            0.40,
            0.31,
            transform=ax.transAxes,
            facecolor="#F7FBFC",
            edgecolor="#C8D8E0",
            linewidth=1.0,
        )
    )
    ax.text(
        0.075,
        0.44,
        "Dynamic literature construction",
        transform=ax.transAxes,
        fontsize=9.2,
        fontweight="bold",
        color=COL["paper"],
        va="top",
    )

    nodes = [
        (0.108, 0.315, "broad\ntopic\nqueries"),
        (0.209, 0.315, "inspected\nsearch\nresults"),
        (0.310, 0.315, "candidate\nidentity\nqueries"),
        (0.411, 0.315, "critique-\ntriggered\nfollow-up"),
    ]

    for x, y, lab in nodes:
        ax.add_patch(
            patches.Rectangle(
                (x - 0.042, y - 0.043),
                0.084,
                0.086,
                transform=ax.transAxes,
                facecolor=COL["white"],
                edgecolor=COL["paper"],
                linewidth=1.05,
            )
        )
        ax.text(
            x,
            y,
            lab,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=6.9,
            color=COL["ink"],
            linespacing=1.05,
        )

    for s, e in [
        ((0.150, 0.315), (0.167, 0.315)),
        ((0.251, 0.315), (0.268, 0.315)),
        ((0.352, 0.315), (0.369, 0.315)),
    ]:
        arrow(ax, s, e, color=COL["paper"], lw=1.0)

    arrow(ax, (0.411, 0.270), (0.108, 0.270), color=COL["paper"], lw=0.9)

    ax.text(
        0.075,
        0.202,
        "run-time corpus expansion",
        transform=ax.transAxes,
        fontsize=7.0,
        fontweight="bold",
        color=COL["muted"],
    )

    # right zoom: predicate-state verification loop
    ax.add_patch(
        patches.Rectangle(
            (0.515, 0.16),
            0.44,
            0.31,
            transform=ax.transAxes,
            facecolor="#FBFAFE",
            edgecolor="#D3CAE9",
            linewidth=1.0,
        )
    )
    ax.text(
        0.535,
        0.44,
        "Predicate-state verification",
        transform=ax.transAxes,
        fontsize=9.2,
        fontweight="bold",
        color=COL["verify_dark"],
        va="top",
    )

    architecture_box(
        0.545,
        0.302,
        0.12,
        0.102,
        "Researcher",
        "retrieve\nread\nsynthesize",
        COL["paper"],
    )
    architecture_box(
        0.703,
        0.302,
        0.12,
        0.102,
        "Critique",
        "audit predicates\nrequest follow-up",
        COL["verify"],
    )

    arrow(ax, (0.668, 0.356), (0.700, 0.356), color=COL["verify"], lw=1.05)
    arrow(
        ax,
        (0.703, 0.322),
        (0.668, 0.322),
        color=COL["paper"],
        lw=1.05,
        rad=-0.22,
    )

    ax.add_patch(
        patches.Rectangle(
            (0.852, 0.302),
            0.085,
            0.102,
            transform=ax.transAxes,
            facecolor=COL["white"],
            edgecolor=COL["outline"],
            linewidth=1.0,
        )
    )
    ax.text(
        0.8945,
        0.386,
        "state",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=6.2,
        fontweight="bold",
        color=COL["ink"],
    )

    states = [
        ("supported", COL["accept"]),
        ("unresolved", COL["warn"]),
        ("exclusion", COL["fail"]),
    ]

    for i, (name, color) in enumerate(states):
        y = 0.356 - 0.027 * i
        ax.add_patch(
            patches.Rectangle(
                (0.863, y - 0.008),
                0.012,
                0.012,
                transform=ax.transAxes,
                facecolor=color,
                edgecolor="none",
            )
        )
        ax.text(
            0.880,
            y - 0.002,
            name,
            transform=ax.transAxes,
            va="center",
            fontsize=6.4,
            color=COL["ink"],
        )

    arrow(ax, (0.826, 0.356), (0.849, 0.356), color="#526370", lw=1.0)

    ax.text(
        0.535,
        0.224,
        "final label + evidence provenance",
        transform=ax.transAxes,
        fontsize=7.0,
        fontweight="bold",
        color=COL["muted"],
    )

    save(fig, "dbcurator_architecture_nmi")


# ---------------------------- figure 2 -------------------------------------

def figure2_fixed_cohort() -> None:
    summary = pd.read_csv(
        ROOT / "manuscript" / "sec_1_result" / "section1_nmi_plan_source_data.csv"
    )

    order = [
        "blood_exposome",
        "dbp",
        "drug_compounds",
        "human_endogenous_metabolites",
        "microbial_natural_products",
    ]
    labels = ["Blood", "DBP", "Drug", "Endog.", "Microbial\nNP"]

    db = (
        summary[summary.system.eq("DB-Curator")]
        .set_index("topic")
        .loc[order]
        .reset_index()
    )
    llm = (
        summary[summary.system.eq("Vanilla LLM")]
        .set_index("topic")
        .loc[order]
        .reset_index()
    )

    eval_counts = {}
    sec1_root = Path("/data/chen/db_curator_results/sec1")
    for topic in order:
        tmp = sec1_root / topic / "single_eval_tmp"
        eval_counts[topic] = len([p for p in tmp.iterdir() if p.is_dir()]) if tmp.exists() else 0

    fig = plt.figure(figsize=(7.35, 5.25), constrained_layout=False)
    fig.subplots_adjust(
        left=0.092,
        right=0.985,
        top=0.855,
        bottom=0.135,
        hspace=0.66,
        wspace=0.45,
    )

    gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.0])
    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[1, 0])
    ax_d = fig.add_subplot(gs[1, 1])

    x = np.arange(len(labels))
    bw = 0.34

    # A. Headline evidence result.
    db_claimed = float(db.db_claimed_papers.sum())
    llm_claimed = float(llm.llm_claimed_refs.sum())

    vals = np.array([
        db.db_existing_papers.sum() / db_claimed,
        db.db_quote_matched_papers.sum() / db_claimed,
        llm.llm_existing_refs.sum() / llm_claimed,
        llm.llm_relaxed_content_refs.sum() / llm_claimed,
    ], dtype=float)

    counts = [
        f"{int(db.db_existing_papers.sum())}/{int(db_claimed)}",
        f"{int(db.db_quote_matched_papers.sum())}/{int(db_claimed)}",
        f"{int(llm.llm_existing_refs.sum())}/{int(llm_claimed)}",
        f"{int(llm.llm_relaxed_content_refs.sum())}/{int(llm_claimed)}",
    ]

    labs = [
        "DB-Curator\nreal paper",
        "DB-Curator\nquote/context",
        "Zero-shot\nreal paper",
        "Zero-shot\ncontent",
    ]
    colors = ["#3F6C95", "#9EBFD5", "#AEB9C3", "#D9B65F"]

    ax_a.bar(
        np.arange(4),
        vals,
        color=colors,
        width=0.64,
        edgecolor="white",
        linewidth=0.60,
        zorder=3,
    )
    ax_a.set_ylim(0, 1.10)
    ax_a.set_xticks(np.arange(4), labs)
    ax_a.set_ylabel("Fraction of cited refs")
    ax_a.set_title("Cited evidence is auditable only for DB-Curator", loc="left")
    style_axis(ax_a)
    panel(ax_a, "a")

    for i, (v, c) in enumerate(zip(vals, counts)):
        ax_a.text(
            i,
            min(v + 0.035, 1.035),
            c,
            ha="center",
            va="bottom",
            fontsize=6.7,
            fontweight="bold",
        )

    # B. Name-level release composition.
    seg_defs = [
        ("benchmark overlap", "benchmark_overlap_auto_accepted", COL["paper"]),
        ("no-overlap true", "non_overlap_human_accepted", COL["accept"]),
        ("false", "non_overlap_human_flagged", COL["fail"]),
    ]

    for offset, frame in [(-bw / 2, db), (bw / 2, llm)]:
        bottom = np.zeros(len(labels))
        for _, col, color in seg_defs:
            vals_seg = frame[col].to_numpy(dtype=float)
            ax_b.bar(
                x + offset,
                vals_seg,
                bottom=bottom,
                width=bw,
                color=color,
                edgecolor="white",
                linewidth=0.45,
            )
            bottom += vals_seg

    ax_b.set_ylim(0, 56)
    ax_b.set_xticks(x, labels)
    ax_b.set_ylabel("Rows per 50-case cohort")
    ax_b.set_title("Name-level release check is not sufficient", loc="left")
    style_axis(ax_b)
    panel(ax_b, "b")
    ax_b.text(
        0.02,
        -0.18,
        "Within each topic: left bar, DB-Curator; right bar, zero-shot baseline.",
        transform=ax_b.transAxes,
        ha="left",
        va="top",
        fontsize=5.7,
        color=COL["muted"],
        clip_on=False,
    )
    inline_key(
        ax_b,
        [
            ("overlap", COL["paper"]),
            ("no-overlap true", COL["accept"]),
            ("false", COL["fail"]),
        ],
        x0=0.02,
        y=0.98,
        dx=0.28,
        fontsize=5.5,
    )
    # C. Evaluations needed.
    screen_vals = np.array([eval_counts[t] for t in order], dtype=float)

    ax_c.bar(
        x,
        screen_vals,
        color="#A9C6D8",
        edgecolor="white",
        linewidth=0.7,
        width=0.62,
        zorder=3,
    )
    ax_c.axhline(50, color=COL["muted"], linewidth=0.9, linestyle="--")
    ax_c.set_xticks(x, labels)
    ax_c.set_ylabel("Compounds evaluated")
    ax_c.set_title("Candidate funnel remains selective", loc="left")
    style_axis(ax_c)
    panel(ax_c, "c")

    for i, v in enumerate(screen_vals):
        ax_c.text(
            i,
            v + max(screen_vals) * 0.025,
            f"{int(v)}",
            ha="center",
            va="bottom",
            fontsize=6.2,
            fontweight="bold",
            color="#456D87",
        )

    ax_c.text(
        0.02,
        0.92,
        "dashed line, final 50-row cohort",
        transform=ax_c.transAxes,
        fontsize=5.9,
        color=COL["muted"],
        ha="left",
        va="top",
    )

    # D. Entry-level audit coverage.
    db_row_rate = db.db_all_real_rows.to_numpy(dtype=float) / db.n.to_numpy(dtype=float)
    llm_row_rate = llm.llm_rows_with_existing_refs.to_numpy(dtype=float) / llm.n.to_numpy(dtype=float)

    ax_d.bar(
        x - bw / 2,
        db_row_rate,
        width=bw,
        color=COL["paper"],
        edgecolor="white",
        linewidth=0.55,
        label="DB-Curator",
        zorder=3,
    )
    ax_d.bar(
        x + bw / 2,
        llm_row_rate,
        width=bw,
        color=COL["llm"],
        edgecolor="white",
        linewidth=0.55,
        label="Vanilla",
        zorder=3,
    )
    ax_d.set_ylim(-0.03, 1.08)
    ax_d.set_xticks(x, labels)
    ax_d.set_ylabel("Rows with real-paper support")
    ax_d.set_title("Entry-level paper support, by topic", loc="left")
    style_axis(ax_d)
    panel(ax_d, "d")

    for i, (dv, lv) in enumerate(zip(db_row_rate, llm_row_rate)):
        ax_d.text(
            i - bw / 2,
            min(dv + 0.035, 1.04),
            f"{int(db.db_all_real_rows.iloc[i])}/50",
            ha="center",
            va="bottom",
            fontsize=6.0,
            color=COL["paper_dark"],
            fontweight="bold",
        )
        ax_d.text(
            i + bw / 2,
            max(lv + 0.035, 0.06),
            f"{int(llm.llm_rows_with_existing_refs.iloc[i])}/50",
            ha="center",
            va="bottom",
            fontsize=5.8,
            color="#6B7782",
        )

    add_suptitle(
        fig,
        "Evidence grounding, not name generation, limits release-ready database construction",
    )

    handles = [
        patches.Patch(facecolor=COL["paper"], edgecolor="white", label="DB-Curator"),
        patches.Patch(facecolor=COL["llm"], edgecolor="white", label="Zero-shot baseline"),
    ]
    fig.legend(
        handles=handles,
        frameon=False,
        ncol=2,
        loc="upper right",
        bbox_to_anchor=(0.985, 0.955),
        handlelength=1.1,
        columnspacing=0.9,
    )

    save(fig, "section1_plan_aligned_human_labels")


# ---------------------------- figure 3 -------------------------------------

def figure3_benchmark_scale() -> None:
    summary = pd.read_csv(
        ROOT / "manuscript" / "all_labeled" / "section24_summary.csv"
    ).fillna(0)
    llm = pd.read_csv(
        ROOT
        / "manuscript"
        / "all_labeled"
        / "llm_benchmark_labeling_20260429"
        / "analysis"
        / "llm_benchmark_labeling_summary.csv"
    ).fillna(0)
    evidence = pd.read_csv(
        ROOT / "manuscript" / "all_labeled" / "section24_evidence_paper_quote_audit.csv"
    ).fillna(0)
    llm_cit = pd.read_csv(
        ROOT
        / "manuscript"
        / "all_labeled"
        / "llm_benchmark_citation_support_strict_20260430"
        / "analysis"
        / "llm_benchmark_citation_support_summary.csv"
    ).fillna(0)
    scope = pd.read_csv(
        ROOT / "manuscript" / "all_labeled" / "section24_scope_alignment.csv"
    ).fillna(0)

    summary = summary.set_index("topic").loc[TOPIC_ORDER].reset_index()
    llm = llm.set_index("topic").loc[TOPIC_ORDER].reset_index()
    evidence = evidence.set_index("topic").loc[TOPIC_ORDER].reset_index()
    llm_cit = llm_cit.set_index("topic").loc[TOPIC_ORDER].reset_index()
    scope = scope.set_index("topic").loc[TOPIC_ORDER].reset_index()

    labels = ["DBP", "Blood", "Drug", "Endog.", "Microbial\nNP"]
    x = np.arange(len(labels))
    y = np.arange(len(labels))
    bw = 0.34

    fig = plt.figure(figsize=(7.35, 5.25), constrained_layout=False)
    fig.subplots_adjust(
        left=0.090,
        right=0.985,
        top=0.855,
        bottom=0.12,
        hspace=0.60,
        wspace=0.45,
    )
    gs = fig.add_gridspec(2, 2)
    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[1, 0])
    ax_d = fig.add_subplot(gs[1, 1])

    # A. DB-Curator stacked outcomes.
    confirmed = summary.confirmed.to_numpy(dtype=float)
    not_confirmed = summary.rows_after_cleaning.to_numpy(dtype=float) - confirmed
    confirmed_color = "#6EAE7C"
    not_confirmed_color = "#E6C276"

    ax_a.barh(
        y,
        confirmed,
        color=confirmed_color,
        height=0.58,
        label="Confirmed",
        edgecolor="white",
        linewidth=0.7,
        zorder=3,
    )
    ax_a.barh(
        y,
        not_confirmed,
        left=confirmed,
        color=not_confirmed_color,
        height=0.58,
        label="Not Confirmed",
        edgecolor="white",
        linewidth=0.7,
        zorder=3,
    )
    ax_a.set_yticks(y, labels)
    ax_a.set_xlabel("Benchmark-positive rows")
    ax_a.set_title("Evidence-grounded verification outcomes", loc="left")
    style_axis(ax_a, axis="x")
    panel(ax_a, "a")
    ax_a.set_ylim(-0.55, len(labels) - 0.28)
    ax_a.legend(
        frameon=False,
        loc="upper right",
        bbox_to_anchor=(1.00, 0.98),
        fontsize=5.9,
        handlelength=1.1,
        handletextpad=0.35,
    )

    for i, (c, total) in enumerate(zip(confirmed, summary.rows_after_cleaning)):
        nc = total - c
        ax_a.text(
            c / 2,
            i,
            f"{int(c)}",
            ha="center",
            va="center",
            fontsize=6.3,
            color="white",
            fontweight="bold",
        )
        ax_a.text(
            total - nc / 2,
            i,
            f"{int(nc)}",
            ha="center",
            va="center",
            fontsize=6.1,
            color="#3A2A00",
            fontweight="bold",
        )

    # B. Confirmation fraction.
    db_rate = summary.confirmed.to_numpy(dtype=float) / summary.rows_after_cleaning.to_numpy(dtype=float)
    llm_rate = llm.llm_confirmed_rate.to_numpy(dtype=float)

    ax_b.bar(
        x - bw / 2,
        db_rate,
        width=bw,
        color="#5B8DB8",
        edgecolor="white",
        linewidth=0.7,
        label="DB-Curator",
        zorder=3,
    )
    ax_b.bar(
        x + bw / 2,
        llm_rate,
        width=bw,
        color="#AEB9C3",
        edgecolor="white",
        linewidth=0.7,
        label="Zero-shot baseline",
        zorder=3,
    )
    ax_b.set_xticks(x, labels)
    ax_b.set_ylim(-0.03, 0.92)
    ax_b.set_ylabel("Confirmed fraction")
    ax_b.set_title("Confirmed labels vary by evidence standard", loc="left")
    style_axis(ax_b)
    panel(ax_b, "b")

    for i, (n, d) in enumerate(zip(summary.confirmed, summary.rows_after_cleaning)):
        ax_b.text(
            i - bw / 2,
            db_rate[i] + 0.045,
            f"{int(n)}/{int(d)}",
            ha="center",
            va="bottom",
            fontsize=5.9,
            color=COL["paper_dark"],
            fontweight="bold",
        )

    for i, (n, d) in enumerate(zip(llm.llm_confirmed, llm.n)):
        ax_b.text(
            i + bw / 2,
            llm_rate[i] + 0.016,
            f"{int(n)}/{int(d)}",
            ha="center",
            va="bottom",
            fontsize=5.0,
            color="#6C7883",
            fontweight="bold",
        )

    # C. Citation support counts.
    db_q = evidence.quote_found_refs.to_numpy(dtype=float)
    if "llm_content_supported_refs" in llm_cit.columns:
        llm_q = llm_cit.llm_content_supported_refs.to_numpy(dtype=float)
    else:
        llm_q = llm_cit.llm_content_support_refs.to_numpy(dtype=float)

    ax_c.bar(
        x - bw / 2,
        db_q,
        width=bw,
        color="#5B8DB8",
        edgecolor="white",
        linewidth=0.7,
        label="DB-Curator quote/context",
        zorder=3,
    )
    ax_c.bar(
        x + bw / 2,
        llm_q,
        width=bw,
        color="#AEB9C3",
        edgecolor="white",
        linewidth=0.7,
        label="Zero-shot content",
        zorder=3,
    )
    ax_c.set_xticks(x, labels)
    ax_c.set_yscale("log")
    ax_c.set_ylim(0.8, max(db_q) * 1.45)
    ax_c.set_ylabel("Content-supported refs, log scale")
    ax_c.set_title("Citation support remains auditable", loc="left")
    style_axis(ax_c)
    panel(ax_c, "c")

    for i, num in enumerate(db_q):
        ax_c.text(
            i - bw / 2,
            float(num) * 1.08,
            f"{int(num)}",
            ha="center",
            va="bottom",
            fontsize=5.7,
            color=COL["paper_dark"],
            fontweight="bold",
        )

    for i, num in enumerate(llm_q):
        ypos = max(float(num), 1.0) * 1.18
        ax_c.text(
            i + bw / 2,
            ypos,
            f"{int(num)}",
            ha="center",
            va="bottom",
            fontsize=5.4,
            color="#6C7883",
            fontweight="bold",
        )

    # D. Human scope audit.
    aligned = scope.scope_aligned_rows.to_numpy(dtype=float)
    audited = scope.audited_rows.to_numpy(dtype=float)
    rate = np.divide(aligned, audited, out=np.zeros_like(aligned), where=audited > 0)

    ax_d.barh(y, rate, color="#75AA7A", height=0.58, edgecolor="white", linewidth=0.5)
    ax_d.set_yticks(y, labels)
    ax_d.set_xlim(0, 1.04)
    ax_d.set_xlabel("Human-verified topic-aligned fraction")
    ax_d.set_title("Human audit of topic-scope alignment", loc="left")
    style_axis(ax_d, axis="x")
    panel(ax_d, "d")

    for i, (a, n, r) in enumerate(zip(aligned, audited, rate)):
        ax_d.text(
            min(r - 0.03, 0.95),
            i,
            f"{int(a)}/{int(n)}",
            va="center",
            ha="right",
            fontsize=6.2,
            color="black",
            fontweight="bold",
        )

    add_suptitle(
        fig,
        "Benchmark-scale verification separates evidence labels, citation support, and topic-scope audit",
    )

    handles = [
        patches.Patch(facecolor=COL["paper"], edgecolor="white", label="DB-Curator"),
        patches.Patch(facecolor=COL["llm"], edgecolor="white", label="Zero-shot baseline"),
    ]
    fig.legend(
        handles=handles,
        frameon=False,
        ncol=2,
        loc="upper right",
        bbox_to_anchor=(0.985, 0.962),
        handlelength=1.1,
        columnspacing=0.9,
    )

    save(fig, "section24_five_topic_overview")


# ---------------------------- extended operational -------------------------

def figure4_operational_efficiency() -> None:
    import generate_section24_extended_figures as ext

    df = ext.load_all().copy()
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=["tokens_used_num", "duration_sec_num"])
    df = df[(df["tokens_used_num"] > 0) & (df["duration_sec_num"] > 0)]

    verdict_colors = {
        "Confirmed": COL["accept"],
        "Insufficient direct evidence": COL["warn"],
        "Explicit negative": COL["fail"],
        "Suspected": COL["verify"],
    }

    fig = plt.figure(figsize=(8.2, 6.1), constrained_layout=False)
    fig.subplots_adjust(
        left=0.080,
        right=0.985,
        top=0.805,
        bottom=0.10,
        hspace=0.74,
        wspace=0.34,
    )

    gs = fig.add_gridspec(2, 2)
    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[1, 0])
    ax_d = fig.add_subplot(gs[1, 1])

    token_log = np.log10(df["tokens_used_num"].to_numpy(dtype=float))
    grid = np.linspace(np.nanpercentile(token_log, 1), np.nanpercentile(token_log, 99), 260)

    for verdict in ["Confirmed", "Insufficient direct evidence", "Explicit negative", "Suspected"]:
        sub = df.loc[df["verdict_plot"].eq(verdict), "tokens_used_num"].dropna()
        sub = sub[sub > 0]

        if len(sub) < 8:
            continue

        vals = np.log10(sub.to_numpy(dtype=float))
        color = verdict_colors.get(verdict, "#64748B")

        if gaussian_kde is not None and len(np.unique(vals)) > 3:
            kde = gaussian_kde(vals, bw_method=0.26)
            dens = kde(grid)
            xx = grid
        else:
            hist, edges = np.histogram(vals, bins=34, density=True)
            xx = (edges[:-1] + edges[1:]) / 2
            dens = hist

        ax_a.plot(xx, dens, color=color, linewidth=2.1, label=f"{verdict} (n={len(sub)})")
        ax_a.fill_between(xx, dens, color=color, alpha=0.16)

    ax_a.set_xlabel("Tokens per candidate, log10 scale")
    ax_a.set_ylabel("Density")
    ax_a.set_title("Resource allocation is heavy-tailed", loc="left")
    style_axis(ax_a)
    panel(ax_a, "a")
    ax_a.legend(
        frameon=False,
        fontsize=5.9,
        loc="upper right",
        bbox_to_anchor=(1.00, 1.33),
        ncol=2,
        handlelength=1.5,
        columnspacing=0.8,
        borderaxespad=0.0,
    )

    for topic in TOPIC_ORDER:
        sub = df[df.topic.eq(topic)]
        ax_b.scatter(
            sub["tokens_used_num"],
            sub["duration_sec_num"] / 60.0,
            s=14,
            alpha=0.58,
            color=TOPIC_COLORS[topic],
            edgecolor="none",
            label=TOPIC_LABEL[topic],
        )

    ax_b.set_xscale("log")
    ax_b.set_yscale("log")
    ax_b.set_xlabel("Tokens per candidate")
    ax_b.set_ylabel("Runtime per candidate (min)")

    lx = np.log10(df["tokens_used_num"].to_numpy(dtype=float))
    ly = np.log10((df["duration_sec_num"] / 60.0).to_numpy(dtype=float))
    corr = np.corrcoef(lx, ly)[0, 1]

    ax_b.set_title(f"Runtime tracks token use (r={corr:.2f} on log scale)", loc="left")
    style_axis(ax_b)
    panel(ax_b, "b")
    ax_b.legend(
        frameon=False,
        fontsize=5.9,
        ncol=3,
        loc="upper center",
        bbox_to_anchor=(0.52, 1.31),
        handletextpad=0.35,
        columnspacing=0.9,
        borderaxespad=0.0,
    )

    runtime_groups = [
        np.log10(
            np.clip(
                df.loc[df.topic.eq(topic), "duration_sec_num"].dropna().to_numpy(dtype=float) / 60.0,
                1e-3,
                None,
            )
        )
        for topic in TOPIC_ORDER
    ]

    _violin_with_points(
        ax_c,
        runtime_groups,
        [TOPIC_LABEL[t] for t in TOPIC_ORDER],
        [TOPIC_COLORS[t] for t in TOPIC_ORDER],
        "Runtime, log10 minutes",
        "Runtime is domain-dependent",
    )
    panel(ax_c, "c")

    verdict_order = [
        "Confirmed",
        "Insufficient direct evidence",
        "Explicit negative",
        "Suspected",
    ]
    score_df = df.dropna(subset=["overall_score_num"])
    score_groups = [
        score_df.loc[score_df.verdict_plot.eq(v), "overall_score_num"].to_numpy(dtype=float)
        for v in verdict_order
    ]

    _violin_with_points(
        ax_d,
        score_groups,
        ["Confirmed", "Insufficient\ndirect evidence", "Explicit\nnegative", "Suspected"],
        [verdict_colors[v] for v in verdict_order],
        "Overall rubric score",
        "Rubric score separates final decisions",
    )
    ax_d.tick_params(axis="x", rotation=10)
    panel(ax_d, "d")

    add_suptitle(fig, "Operational cost and routing behavior across five chemical domains")
    save(fig, "section24_operational_efficiency")


# ---------------------------- figure 4 main --------------------------------

def figure4_rubric_full_discrimination() -> None:
    import generate_section24_extended_figures as ext

    df = ext.load_all().copy()
    rubric = ext.rubric_discriminative_power(df).dropna(subset=["delta"]).copy()
    rubric.to_csv(
        ROOT / "manuscript" / "all_labeled" / "section24_rubric_confirmation_probability.csv",
        index=False,
    )

    display_rubric_labels = {
        "The entity must be a specific chemical compound.": "Specific chemical",
        "The reaction must occur in real or simulated water matrices.": "Water matrix",
        "The compound's formation must occur during a water disinfection or oxidation process.": "Disinfection/oxidation",
        "The formation must result from the reaction of disinfectants or oxidants with naturally occurring or anthropogenic precursors.": "Precursor reaction",
        "There must be evidence directly attributing the compound’s formation to the treatment process.": "Direct formation evidence",
        "There must be evidence directly attributing the compound's formation to the treatment process.": "Direct formation evidence",
        "The presence of the chemical entity must be supported by evidence from primary literature, biomonitoring surveys, or public metabolomics datasets.": "Literature/dataset support",
        "The supporting evidence must be associated with human blood specimens.": "Human blood specimen",
        "The chemical entity may be either endogenous or exogenous.": "Endogenous or exogenous",
        "The chemical entity must be reported as present in human blood or systemic circulation.": "Blood/circulation",
        "The entry excludes drug packages.": "Excludes packages",
        "The entry excludes final commercial drug products.": "Excludes commercial products",
        "The entry excludes drug formulations.": "Excludes formulations",
        "The drug substance or entity elicits or is intended to elicit pharmacologically relevant effects.": "Pharmacologic effect",
        "The entry represents a specific drug substance or drug entity.": "Specific drug entity",
        "The entry includes small-molecule drugs.": "Small-molecule drug",
        "The entry includes biotech drugs.": "Biotech drug",
        "The entity must be a small molecule.": "Small molecule",
        "The entity must not be solely an exogenous chemical.": "Not solely exogenous",
        "The entity must not be solely a microbiota-only metabolite.": "Not microbiota-only",
        "The entity must be produced within the human body.": "Produced in human body",
        "The entity must function in human biochemical or physiological processes.": "Human biochemical function",
        "If a metabolite is produced by both microbiota and host metabolism, it is included.": "Host + microbiota allowed",
        "The entity must originate from bacteria, fungi, or cyanobacteria.": "Bacterial/fungal/cyano origin",
        "The entity's origin must be supported by peer-reviewed primary scientific literature.": "Peer-reviewed origin support",
        "The entity must not be a non-secondary-metabolite biomolecule.": "Not non-secondary biomolecule",
        "The entity must not be a primary metabolite.": "Not primary metabolite",
        "The entity's structural assignment must be unambiguous.": "Unambiguous structure",
        "The unambiguous structural assignment must be supported by sufficient analytical evidence.": "Analytical evidence",
    }

    counts = df["criteria_json"].map(_criteria_counts_from_json)
    df["criteria_solved_count"] = [v[0] for v in counts]
    df["criteria_total_count"] = [v[1] for v in counts]

    fig = plt.figure(figsize=(7.35, 7.25), constrained_layout=False)
    fig.subplots_adjust(left=0.255, right=0.975, top=0.905, bottom=0.075, hspace=0.72)
    gs = fig.add_gridspec(5, 1)
    letters = list("abcde")

    for row_i, topic in enumerate(TOPIC_ORDER):
        ax = fig.add_subplot(gs[row_i, 0])
        topic_df = df[df.topic.eq(topic)].copy()
        topic_rubric = rubric[rubric.topic.eq(topic)].copy()
        topic_rubric["overall_pass_rate"] = np.divide(
            topic_rubric["confirmed_pass_rate"] * topic_rubric["n_confirmed"]
            + topic_rubric["other_pass_rate"] * topic_rubric["n_other"],
            topic_rubric["n_confirmed"] + topic_rubric["n_other"],
        )
        topic_rubric = topic_rubric.sort_values(
            ["overall_pass_rate", "delta"], ascending=[False, False]
        ).reset_index(drop=True)

        labels_plot = [
            display_rubric_labels.get(c, short_gate_line(c, max_chars=34))
            for c in topic_rubric["criterion"].tolist()
        ][::-1]
        y = np.arange(len(labels_plot))
        overall = topic_rubric["overall_pass_rate"].to_numpy(dtype=float)[::-1] * 100
        confirmed = topic_rubric["confirmed_pass_rate"].to_numpy(dtype=float)[::-1] * 100
        other = topic_rubric["other_pass_rate"].to_numpy(dtype=float)[::-1] * 100

        # One quiet neutral bar shows corpus pass rate; red/green dots carry the actual discrimination.
        bar_colors = ["#D9E6D4" if v < 75 else "#9EC78D" if v < 95 else "#5A9B69" for v in overall]
        ax.barh(y, overall, color=bar_colors, edgecolor="white", linewidth=0.55, height=0.62, zorder=2)
        ax.scatter(other, y, s=24, color="#C85C5C", edgecolor="white", linewidth=0.45, zorder=5,
                   label="Non-Confirmed rows" if row_i == 0 else None)
        ax.scatter(confirmed, y, s=24, color="#12965C", edgecolor="white", linewidth=0.45, zorder=6,
                   label="Confirmed rows" if row_i == 0 else None)

        ax.set_yticks(y, labels_plot)
        ax.tick_params(axis="y", labelsize=6.7, pad=2.5)
        ax.set_xlim(0, 110)
        ax.set_xlabel("Pass rate (%)" if row_i == len(TOPIC_ORDER) - 1 else "")
        ax.set_title(f"{TOPIC_LABEL[topic]} predicate gates (n={len(topic_df)})", loc="left", pad=6)
        style_axis(ax, axis="x")
        panel(ax, letters[row_i])
        ax.set_xticks([0, 25, 50, 75, 100])

        for yy, val in zip(y, overall):
            if val >= 94:
                x_text = val - 2.0
                ha = "right"
            else:
                x_text = val + 1.4
                ha = "left"
            ax.text(x_text, yy, f"{val:.0f}%", ha=ha, va="center",
                    fontsize=6.2, fontweight="bold", color=COL["ink"])

        if row_i == 0:
            ax.legend(frameon=False, loc="upper right", bbox_to_anchor=(1.0, 1.28), ncol=2,
                      fontsize=6.2, handletextpad=0.35, columnspacing=0.9)

    add_suptitle(fig, "Predicate gates reveal topic-specific acceptance logic")
    save(fig, "section24_evidence_depth")


# ---------------------------- figure 5 -------------------------------------

def figure5_iterative() -> None:
    iter_df = pd.read_csv(
        ROOT / "manuscript" / "all_labeled" / "section24_claim_change_and_calls.csv"
    ).fillna(0)
    corr = pd.read_csv(
        ROOT / "manuscript" / "all_labeled" / "section24_fig6b_change_correctness.csv"
    ).fillna(0)
    mode = pd.read_csv(
        "/data/chen/db_form_agent_system_archive/results/data/comparison_results_offline_vs_hybrid.csv"
    ).fillna(0)

    mode["offline_confirmed"] = mode["offline_normalized_prediction"].map(is_confirmed)
    mode["hybrid_confirmed"] = mode["hybrid_normalized_prediction"].map(is_confirmed)

    for col in [
        "offline_tokens_used",
        "hybrid_tokens_used",
        "offline_duration_seconds",
        "hybrid_duration_seconds",
    ]:
        mode[col] = pd.to_numeric(mode[col], errors="coerce").fillna(0)

    fig = plt.figure(figsize=(7.35, 5.35), constrained_layout=False)
    fig.subplots_adjust(
        left=0.090,
        right=0.985,
        top=0.84,
        bottom=0.12,
        hspace=0.74,
        wspace=0.46,
    )

    gs = fig.add_gridspec(2, 2)
    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[1, 0])
    ax_d = fig.add_subplot(gs[1, 1])

    gain = (
        iter_df.groupby("topic")
        .agg(
            initial_confirmed=("initial_confirmed", "sum"),
            final_confirmed=("final_confirmed", "sum"),
            n=("final_confirmed", "size"),
        )
        .reindex(TOPIC_ORDER)
        .reset_index()
    )

    x = np.arange(len(gain))
    labels = [TOPIC_LABEL[t] for t in TOPIC_ORDER]
    width = 0.34

    ax_a.bar(
        x - width / 2,
        gain.initial_confirmed,
        width,
        color=COL["llm_light"],
        label="Researcher first claim",
        zorder=3,
    )
    ax_a.bar(
        x + width / 2,
        gain.final_confirmed,
        width,
        color=COL["verify"],
        label="After critique loop",
        zorder=3,
    )
    ax_a.set_xticks(
        x,
        [f"{l}\n(n={int(n)})" for l, n in zip(labels, gain.n)],
    )
    ax_a.set_ylabel("Rows assigned Confirmed")
    ax_a.set_title("Critique revises the verification state", loc="left", pad=8)
    style_axis(ax_a)
    panel(ax_a, "a")

    ymax = max(gain.final_confirmed.max(), gain.initial_confirmed.max()) * 1.26
    ax_a.set_ylim(0, ymax)

    for i, r in gain.iterrows():
        delta = int(r.final_confirmed - r.initial_confirmed)
        ax_a.text(
            i + width / 2,
            r.final_confirmed + ymax * 0.025,
            f"{delta:+d}",
            ha="center",
            fontsize=6.2,
            fontweight="bold",
        )

    # Colors are described in the caption; avoid a legend collision with the bars.

    delta_rows = []
    for topic in TOPIC_ORDER:
        sub = iter_df[iter_df.topic.eq(topic)]
        rescued = int(((~sub.initial_confirmed.astype(bool)) & sub.final_confirmed.astype(bool)).sum())
        tightened = int((sub.initial_confirmed.astype(bool) & (~sub.final_confirmed.astype(bool))).sum())
        delta_rows.append((topic, rescued, tightened))

    ddf = pd.DataFrame(delta_rows, columns=["topic", "rescued", "tightened"])

    corr["is_rescued_right"] = (
        corr["trajectory"].eq("Rescued to Confirmed") & corr["right"].astype(bool)
    )
    corr["is_true_negative"] = (
        corr["trajectory"].eq("Tightened away from Confirmed")
        & corr["right"].astype(bool)
    )
    corr["is_over_tightened"] = ~corr["right"].astype(bool)
    correctness = (
        corr.groupby("topic")
        .agg(
            rescued_right=("is_rescued_right", "sum"),
            true_negative=("is_true_negative", "sum"),
            over_tightened=("is_over_tightened", "sum"),
            total=("right", "size"),
        )
        .reindex(TOPIC_ORDER)
        .fillna(0)
        .reset_index()
    )
    all_row = pd.DataFrame([{
        "topic": "all",
        "rescued_right": int(corr["is_rescued_right"].sum()),
        "true_negative": int(corr["is_true_negative"].sum()),
        "over_tightened": int(corr["is_over_tightened"].sum()),
        "total": int(len(corr)),
    }])
    correctness = pd.concat([correctness, all_row], ignore_index=True)
    correctness["right_total"] = (
        correctness["rescued_right"].astype(int) + correctness["true_negative"].astype(int)
    )
    b_labels = [TOPIC_LABEL[t] for t in TOPIC_ORDER] + ["All"]
    xb = np.arange(len(correctness))
    ax_b.bar(
        xb,
        correctness["rescued_right"],
        color=COL["accept"],
        edgecolor="white",
        linewidth=0.6,
        zorder=3,
        label="Rescued Confirmed",
    )
    ax_b.bar(
        xb,
        correctness["true_negative"],
        bottom=correctness["rescued_right"],
        color=COL["paper"],
        edgecolor="white",
        linewidth=0.6,
        zorder=3,
        label="True negative label",
    )
    ax_b.bar(
        xb,
        correctness["over_tightened"],
        bottom=correctness["rescued_right"] + correctness["true_negative"],
        color=COL["warn"],
        edgecolor="white",
        linewidth=0.6,
        zorder=3,
        label="Over-tightened",
    )
    ax_b.set_xticks(xb, b_labels, rotation=18, ha="right")
    ax_b.set_ylabel("Changed decisions")
    ax_b.set_title("Human audit of changed decisions", loc="left")
    style_axis(ax_b)
    panel(ax_b, "b")
    ymax_b = max(correctness["total"].max() * 1.18, 5)
    ax_b.set_ylim(0, ymax_b)
    for i, r in correctness.iterrows():
        total = int(r.total)
        if total:
            ax_b.text(i, total + ymax_b * 0.025, f"{int(r.right_total)}/{total}",
                      ha="center", va="bottom", fontsize=5.9, fontweight="bold")
    ax_b.legend(
        frameon=False,
        loc="upper left",
        fontsize=5.6,
        handletextpad=0.25,
        borderaxespad=0.0,
    )

    confirm_counts = [
        int(mode.offline_confirmed.sum()),
        int(mode.hybrid_confirmed.sum()),
    ]
    med_min = [
        float(mode.offline_duration_seconds.median() / 60),
        float(mode.hybrid_duration_seconds.median() / 60),
    ]

    bars = ax_c.bar(
        [0, 1],
        confirm_counts,
        color=[COL["warn"], COL["accept"]],
        width=0.55,
        zorder=3,
        edgecolor="white",
        linewidth=0.6,
    )
    ax_c.set_xticks([0, 1], ["Offline-only", "Hybrid retrieval"])
    ax_c.set_ylabel("Confirmed labels out of 50")
    ax_c.set_title("Hybrid retrieval increases yield in a 50-case ablation", loc="left")
    style_axis(ax_c)
    panel(ax_c, "c")

    for bar, count in zip(bars, confirm_counts):
        ax_c.text(
            bar.get_x() + bar.get_width() / 2,
            count + 0.6,
            f"{count}/50",
            ha="center",
            fontsize=6.1,
            fontweight="bold",
        )

    ax_c.text(
        0.02,
        0.92,
        "n=50 retrieval-mode ablation",
        transform=ax_c.transAxes,
        fontsize=5.9,
        fontweight="bold",
        color=COL["ink"],
        bbox=dict(
            boxstyle="round,pad=0.22",
            facecolor=COL["white"],
            edgecolor="#D8E2E8",
        ),
    )

    ax_c2 = ax_c.twinx()
    ax_c2.grid(False)
    ax_c2.plot(
        [0, 1],
        med_min,
        marker="o",
        color=COL["paper"],
        linewidth=1.25,
        zorder=4,
    )
    ax_c2.set_ylabel("Median runtime (minutes)")
    ax_c2.set_ylim(0, max(med_min) * 1.35)
    ax_c2.spines["right"].set_color(COL["outline"])

    calls = (
        iter_df.groupby("claim_changed")[
            ["researcher_call_count", "critique_call_count", "supporting_sources"]
        ]
        .mean()
        .reindex([False, True])
        .fillna(0)
    )

    xx = np.arange(2)

    width_d = 0.24
    ax_d.bar(
        xx - width_d,
        calls.researcher_call_count,
        width_d,
        color=COL["paper"],
        label="Researcher calls",
        zorder=3,
        edgecolor="white",
        linewidth=0.6,
    )
    ax_d.bar(
        xx,
        calls.critique_call_count,
        width_d,
        color=COL["verify"],
        label="Critique calls",
        zorder=3,
        edgecolor="white",
        linewidth=0.6,
    )
    ax_d.bar(
        xx + width_d,
        calls.supporting_sources,
        width_d,
        color=COL["paper_light"],
        label="Supporting sources",
        zorder=3,
        edgecolor="white",
        linewidth=0.6,
    )
    ax_d.set_xticks(xx, ["Stable claim", "Claim changed"])
    ax_d.set_ylabel("Mean count per row")
    ax_d.set_title("Changed claims trigger deeper review", loc="left")
    style_axis(ax_d)
    panel(ax_d, "d")
    ax_d.legend(frameon=False, loc="upper left", handletextpad=0.3)

    ymax_d = max(calls.researcher_call_count.max(), calls.critique_call_count.max(), calls.supporting_sources.max()) * 1.24
    ax_d.set_ylim(0, ymax_d)

    for i, changed in enumerate([False, True]):
        for xoff, col in [(-width_d, "researcher_call_count"), (0, "critique_call_count"), (width_d, "supporting_sources")]:
            val = float(calls.loc[changed, col])
            ax_d.text(i + xoff, val + ymax_d * 0.025, f"{val:.1f}",
                      ha="center", fontsize=5.6, fontweight="bold")

    add_suptitle(
        fig,
        "Critique-guided retrieval revises evidence-limited decisions and increases support depth",
    )
    save(fig, "section24_iterative_research_importance")


def main() -> None:
    ensure_dirs()
    figure1_architecture()
    figure2_fixed_cohort()
    figure3_benchmark_scale()
    figure4_operational_efficiency()
    figure4_rubric_full_discrimination()
    figure5_iterative()


if __name__ == "__main__":
    main()
