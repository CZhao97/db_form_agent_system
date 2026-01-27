import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from pathlib import Path


# =========================
# CONFIG: set your file paths here
# =========================
BASELINE_XLSX = "notebooks/dbp_gemini_flash_2_5_results.xlsx"
AGENT_CSV     = "evaluation_results_full_fresh_k10.csv"

OUT_GROUPED   = "comparison_bar_chart_pretty.png"
OUT_STACKED   = "comparison_stacked_percent.png"


# =========================
# Helpers
# =========================
def normalize(v):
    """Normalize free-text outputs into canonical verdict labels."""
    if not isinstance(v, str):
        return "Unclear"
    v = v.strip().lower()
    if "not confirmed" in v:
        return "Not Confirmed"
    if "confirmed" in v:
        return "Confirmed DBP"
    if "suspected" in v:
        return "Suspected DBP"
    return "Unclear"


def merge_cats(x):
    """Merge low-specificity categories for cleaner comparison plots."""
    return "Not Confirmed / Unclear" if x in ["Not Confirmed", "Unclear"] else x


def ensure_full_categories(df, models_order, verdict_order):
    """Ensure every model has all verdict categories (fill missing with 0)."""
    all_idx = pd.MultiIndex.from_product([models_order, verdict_order], names=["Model", "Verdict"])
    return (
        df.set_index(["Model", "Verdict"])
          .reindex(all_idx, fill_value=0)
          .reset_index()
    )


def get_count(plot_df, model, verdict):
    return int(plot_df[(plot_df["Model"] == model) & (plot_df["Verdict"] == verdict)]["Count"].iloc[0])


def pick_prediction_column(df_agent):
    """Choose best available prediction column for agent file."""
    for c in ["normalized_prediction", "Model Prediction", "prediction", "verdict", "label"]:
        if c in df_agent.columns:
            return c
    raise ValueError(
        "Agent file is missing a prediction column. Expected one of: "
        "normalized_prediction / Model Prediction / prediction / verdict / label"
    )


def nudge_small_bar_labels(ax, y_threshold=30, y_nudge=10):
    """
    If a bar label is too close to the axis (tiny bars), push it up a bit.
    Works for the labels created by ax.bar_label.
    """
    for txt in ax.texts:
        # only nudge bar-label texts (they contain a newline like "233\n(34.1%)")
        if "\n(" not in txt.get_text():
            continue
        x, y = txt.get_position()
        if y < y_threshold:
            txt.set_position((x, y + y_nudge))


# =========================
# Main
# =========================
def main():
    # ---- check files exist ----
    if not Path(BASELINE_XLSX).exists():
        raise FileNotFoundError(f"Baseline XLSX not found: {BASELINE_XLSX}")
    if not Path(AGENT_CSV).exists():
        raise FileNotFoundError(f"Agent CSV not found: {AGENT_CSV}")

    # -----------------------------
    # 1) Load data
    # -----------------------------
    print("Loading Baseline...")
    df_base = pd.read_excel(BASELINE_XLSX)

    if "IUPAC name" not in df_base.columns:
        raise ValueError("Baseline file is missing column: 'IUPAC name'")
    if "Model Prediction" not in df_base.columns:
        raise ValueError("Baseline file is missing column: 'Model Prediction'")

    df_base["Base_Verdict"] = df_base["Model Prediction"].apply(normalize)

    print("Loading Agent...")
    df_agent = pd.read_csv(AGENT_CSV)

    if "IUPAC name" not in df_agent.columns:
        raise ValueError("Agent file is missing column: 'IUPAC name'")

    pred_col = pick_prediction_column(df_agent)
    df_agent["Agent_Verdict"] = df_agent[pred_col].astype(str).apply(normalize)

    # -----------------------------
    # 2) Merge on common compounds
    # -----------------------------
    merged = pd.merge(df_agent, df_base, on="IUPAC name", how="inner", suffixes=("_Agent", "_Base"))
    N = len(merged)
    print(f"Merged N={N}")

    # -----------------------------
    # 3) Confusion matrix
    # -----------------------------
    print("\n--- Confusion Matrix (MAS vs Baseline) ---")
    print(pd.crosstab(merged["Agent_Verdict"], merged["Base_Verdict"]))

    # -----------------------------
    # 4) Prepare plotting data
    # -----------------------------
    merged["Agent_Verdict_Plot"] = merged["Agent_Verdict"].apply(merge_cats)
    merged["Base_Verdict_Plot"] = merged["Base_Verdict"].apply(merge_cats)

    agent_counts = (
        merged["Agent_Verdict_Plot"]
        .value_counts()
        .rename_axis("Verdict")
        .reset_index(name="Count")
    )
    agent_counts["Model"] = "MAS (Gemini Flash 2.5)"

    base_counts = (
        merged["Base_Verdict_Plot"]
        .value_counts()
        .rename_axis("Verdict")
        .reset_index(name="Count")
    )
    base_counts["Model"] = "Baseline (Gemini Flash 2.5)"

    plot_data = pd.concat([agent_counts, base_counts], ignore_index=True)

    verdict_order = ["Confirmed DBP", "Suspected DBP", "Not Confirmed / Unclear"]
    models_order  = ["MAS (Gemini Flash 2.5)", "Baseline (Gemini Flash 2.5)"]

    plot_data = ensure_full_categories(plot_data, models_order, verdict_order)
    plot_data["Percent"] = plot_data["Count"] / N * 100

    # -----------------------------
    # 5) Plot 1: grouped bars (count + percent) with callout above Confirmed group
    # -----------------------------
    sns.set_theme(style="whitegrid", context="talk")

    fig, ax = plt.subplots(figsize=(12.5, 6.2))
    palette_models = sns.color_palette("colorblind", n_colors=2)

    sns.barplot(
        data=plot_data,
        x="Verdict", y="Count",
        hue="Model",
        order=verdict_order, hue_order=models_order,
        palette=palette_models,
        ax=ax,
        edgecolor="white",
        linewidth=1.5
    )

    # Wrap / shorten tick labels
    pretty_labels = {
        "Confirmed DBP": "Confirmed\nDBP",
        "Suspected DBP": "Suspected\nDBP",
        "Not Confirmed / Unclear": "Not confirmed /\nUnclear",
    }
    ax.set_xticklabels([pretty_labels[v] for v in verdict_order])

    # Bar labels: count + percent
    for container in ax.containers:
        labels = []
        for bar in container:
            h = bar.get_height()
            pct = (h / N * 100) if N else 0
            labels.append(f"{int(h)}\n({pct:.1f}%)")
        ax.bar_label(container, labels=labels, padding=3, fontsize=12)

    # Make tiny-bar labels readable
    nudge_small_bar_labels(ax, y_threshold=30, y_nudge=10)

    ax.set_xlabel("")
    ax.set_ylabel("Number of compounds", fontsize=18)

    ax.grid(axis="y", alpha=0.22)
    ax.grid(axis="x", visible=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Add headroom for labels
    ax.set_ylim(0, plot_data["Count"].max() * 1.12)

    # Compute deltas for annotation
    mas_model = models_order[0]
    base_model = models_order[1]
    agent_c = get_count(plot_data, mas_model, "Confirmed DBP")
    base_c  = get_count(plot_data, base_model, "Confirmed DBP")
    delta_c = agent_c - base_c
    mult = (agent_c / base_c) if base_c else np.nan

    # ✅ Place "+147 confirmed (2.7×)" above the Confirmed group
    label_ys = []
    for t in ax.texts:
        if "\n(" in t.get_text():  # bar labels only
            x, y = t.get_position()
            if -0.5 <= x <= 0.5:   # labels around Confirmed category (x≈0)
                label_ys.append(y)

    top_label_y = max(label_ys) if label_ys else y_top_confirmed
    callout_y = top_label_y + 400  # 25 data units gap; adjust to 15/20/30 if desired

    ax.text(
        0,
        callout_y,
        f"+{delta_c} confirmed\n({mult:.1f}×)",
        ha="center",
        va="bottom",
        fontsize=13,
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.9)
    )

    # Figure-level title + legend (no overlap)
    handles, labels = ax.get_legend_handles_labels()
    if ax.legend_ is not None:
        ax.legend_.remove()

    fig.suptitle(
        f"DBP identification outcomes on the same compound set (N={N})",
        y=0.99, fontsize=24, fontweight="bold"
    )
    fig.legend(
        handles, labels,
        ncol=2,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.94),
        fontsize=16,
        handletextpad=0.6,
        columnspacing=1.6
    )
    fig.subplots_adjust(top=0.82)

    fig.savefig(OUT_GROUPED, dpi=300, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    print(f"Saved: {OUT_GROUPED}")

    # -----------------------------
    # 6) Plot 2: 100% stacked percent distribution
    # -----------------------------
    sns.set_theme(style="whitegrid", context="talk")

    pivot = (
        plot_data.pivot(index="Model", columns="Verdict", values="Percent")
                .loc[models_order, verdict_order]
    )

    xticklabels = ["MAS\n(Gemini Flash 2.5)", "Baseline\n(Gemini Flash 2.5)"]

    fig, ax = plt.subplots(figsize=(10, 5.4))
    bottom = np.zeros(len(pivot))

    palette_verdict = sns.color_palette("colorblind", n_colors=3)
    color_map = dict(zip(verdict_order, palette_verdict))

    for v in verdict_order:
        vals = pivot[v].values
        ax.bar(
            range(len(pivot)),
            vals,
            bottom=bottom,
            label=v,
            color=color_map[v],
            edgecolor="white",
            linewidth=1.4
        )

        for i, val in enumerate(vals):
            if val >= 5:
                ax.text(i, bottom[i] + val/2, f"{val:.1f}%", ha="center", va="center", fontsize=12)

        bottom += vals

    ax.set_title(f"Outcome distribution (percent of N={N})", pad=10, fontweight="bold")
    ax.set_ylabel("Percent (%)")
    ax.set_xlabel("")

    ax.set_xticks(range(len(pivot)))
    ax.set_xticklabels(xticklabels)

    ax.set_ylim(0, 100)
    ax.grid(axis="y", alpha=0.22)
    ax.grid(axis="x", visible=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.legend(frameon=False, bbox_to_anchor=(1.02, 1.0), loc="upper left", title=None, fontsize=14)

    fig.tight_layout()
    fig.savefig(OUT_STACKED, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {OUT_STACKED}")

    # -----------------------------
    # 7) Auto story summary
    # -----------------------------
    suspected_mas = get_count(plot_data, mas_model, "Suspected DBP")
    suspected_base = get_count(plot_data, base_model, "Suspected DBP")
    unresolved_mas = get_count(plot_data, mas_model, "Not Confirmed / Unclear")
    unresolved_base = get_count(plot_data, base_model, "Not Confirmed / Unclear")

    print("\n--- Story summary (auto) ---")
    print(f"Confirmed DBPs: MAS {agent_c} ({agent_c/N*100:.1f}%) vs Baseline {base_c} ({base_c/N*100:.1f}%) => +{agent_c-base_c}")
    print(f"Suspected DBPs: MAS {suspected_mas} ({suspected_mas/N*100:.1f}%) vs Baseline {suspected_base} ({suspected_base/N*100:.1f}%)")
    print(f"Not confirmed/unclear: MAS {unresolved_mas} ({unresolved_mas/N*100:.1f}%) vs Baseline {unresolved_base} ({unresolved_base/N*100:.1f}%) => {unresolved_mas-unresolved_base:+d}")


if __name__ == "__main__":
    main()
