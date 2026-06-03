from __future__ import annotations

from pathlib import Path
import textwrap

import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.backends.backend_pdf import PdfPages
from pptx import Presentation
from pptx.util import Inches

OUT = Path(__file__).resolve().parent
SLIDE_DIR = OUT / "rendered"
SLIDE_DIR.mkdir(parents=True, exist_ok=True)

W, H = 16, 9
DPI = 180

COL = {
    "ink": "#14212B",
    "muted": "#5A6672",
    "paper": "#F7F4EC",
    "panel": "#FFFFFF",
    "line": "#D7DEE4",
    "blue": "#4D82AC",
    "blue2": "#A6C2D6",
    "green": "#76AF8B",
    "green2": "#D8EAD9",
    "gold": "#E2B457",
    "orange": "#D58E43",
    "red": "#C96767",
    "gray": "#AAB5BE",
    "darkgray": "#53616D",
    "purple": "#8F7DBB",
}

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 16,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 1.0,
    "figure.facecolor": COL["paper"],
    "axes.facecolor": COL["panel"],
})


def fig_ax():
    fig = plt.figure(figsize=(W, H), dpi=DPI, facecolor=COL["paper"])
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")
    return fig, ax


def wrap(text, width=58):
    parts = []
    for part in str(text).splitlines():
        if not part.strip():
            parts.append("")
        else:
            parts.extend(textwrap.wrap(part, width=width))
    return "\n".join(parts)


def title(ax, text, subtitle=None):
    ax.text(0.72, 8.28, text, ha="left", va="top", fontsize=31, fontweight="bold", color=COL["ink"])
    if subtitle:
        ax.text(0.75, 7.62, wrap(subtitle, 92), ha="left", va="top", fontsize=15.5, color=COL["muted"], linespacing=1.25)


def pill(ax, x, y, text, fc, ec=None, color="white", fs=13):
    ax.text(x, y, text, ha="center", va="center", fontsize=fs, fontweight="bold", color=color,
            bbox=dict(boxstyle="round,pad=0.35,rounding_size=0.16", fc=fc, ec=ec or fc, lw=1))


def card(ax, x, y, w, h, heading, body, accent=COL["blue"], number=None):
    ax.add_patch(patches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.018,rounding_size=0.13",
                                        fc=COL["panel"], ec=COL["line"], lw=1.3))
    ax.add_patch(patches.Rectangle((x, y+h-0.08), w, 0.08, fc=accent, ec="none"))
    if number:
        ax.text(x+0.32, y+h-0.48, number, ha="left", va="top", fontsize=34, fontweight="bold", color=accent)
        yy = y+h-1.28
    else:
        yy = y+h-0.42
    ax.text(x+0.32, yy, heading, ha="left", va="top", fontsize=17, fontweight="bold", color=COL["ink"])
    ax.text(x+0.32, yy-0.48, wrap(body, 34), ha="left", va="top", fontsize=13.2, color=COL["muted"], linespacing=1.16)



def metric_card(ax, x, y, w, h, number, heading, body, accent):
    ax.add_patch(patches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.018,rounding_size=0.13",
                                        fc=COL["panel"], ec=COL["line"], lw=1.3))
    ax.add_patch(patches.Rectangle((x, y+h-0.08), w, 0.08, fc=accent, ec="none"))
    ax.text(x+0.32, y+h-0.34, number, ha="left", va="top", fontsize=30, fontweight="bold", color=accent)
    ax.text(x+0.32, y+h-1.00, heading, ha="left", va="top", fontsize=15.5, fontweight="bold", color=COL["ink"])
    ax.text(x+0.32, y+h-1.40, wrap(body, 34), ha="left", va="top", fontsize=11.8, color=COL["muted"], linespacing=1.08)

def arrow(ax, x1, y1, x2, y2, color=COL["darkgray"], lw=2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", lw=lw, color=color, shrinkA=4, shrinkB=4))


def save_slide(fig, idx, name):
    path = SLIDE_DIR / f"slide_{idx:02d}_{name}.png"
    fig.savefig(path, dpi=DPI, facecolor=COL["paper"], bbox_inches=None, pad_inches=0)
    plt.close(fig)
    return path


slides = []

# Slide 1
fig, ax = fig_ax()
title(ax, "Agentic scientific curation", "DB-Curator turns open-ended scientific requests into auditable database entries, not just plausible answers.")
pill(ax, 12.6, 8.1, "dynamic literature construction", COL["blue"])
pill(ax, 12.6, 7.55, "predicate-state verification", COL["green"])
card(ax, 0.78, 4.82, 4.55, 2.15, "Scientific need", "Specialized databases are still built by experts who search papers, interpret context and record evidence row by row.", COL["blue"])
card(ax, 5.75, 4.82, 4.55, 2.15, "AI gap", "LLMs can summarize papers, but database release needs candidate-level decisions and traceable evidence.", COL["gold"])
card(ax, 10.72, 4.82, 4.55, 2.15, "Core idea", "Use agents as a controlled verification loop: retrieve, inspect, critique, and stop only when the rubric is satisfied.", COL["green"])
ax.text(0.85, 2.72, "What changes for scientists?", fontsize=22, fontweight="bold", color=COL["ink"])
for i, txt in enumerate(["less manual literature triage", "explicit inclusion/exclusion rules", "database rows with provenance", "human review focused on edge cases"]):
    pill(ax, 2.55 + i*3.72, 2.02, txt, [COL["blue"], COL["green"], COL["orange"], COL["purple"]][i], fs=12.2)
ax.text(0.78, 0.55, "Audience takeaway: the agentic part is not chat. It is dynamic corpus construction plus entry-level evidence checking.", fontsize=13.8, color=COL["muted"])
slides.append(save_slide(fig, 1, "core_idea"))

# Slide 2
fig, ax = fig_ax()
title(ax, "How the agentic workflow works", "The system builds the evidence set during the run, then verifies each candidate against a user-defined acceptance contract.")
xs = [0.8, 4.05, 7.35, 10.7, 13.25]
labels = [
    ("1. Scope", "request → rubric\ninclusion / exclusion"),
    ("2. Literature", "broad search\nseed expansion\nfollow-up"),
    ("3. Candidates", "NER + grounding\nranking + queue"),
    ("4. Verification", "Researcher reads\nCritique audits"),
    ("5. Database", "accepted rows\nspans + IDs"),
]
colors = [COL["blue"], COL["blue2"], COL["gold"], COL["orange"], COL["green"]]
for i, (x, (h, b)) in enumerate(zip(xs, labels)):
    card(ax, x, 4.9, 2.35, 2.18, h, b, colors[i])
    if i < len(xs)-1:
        arrow(ax, x+2.35, 5.95, xs[i+1], 5.95)
# zoom loop
ax.add_patch(patches.FancyBboxPatch((3.1, 1.0), 9.85, 2.65, boxstyle="round,pad=0.02,rounding_size=0.18", fc="#FBFAF4", ec=COL["line"], lw=1.5))
ax.text(3.42, 3.28, "Predicate-state loop", fontsize=19, fontweight="bold", color=COL["ink"])
loop = [("supported", COL["green"]), ("unresolved", COL["gold"]), ("exclusion triggered", COL["red"]), ("exhausted", COL["gray"])]
for i, (lab, c) in enumerate(loop):
    pill(ax, 4.35+i*2.22, 2.45, lab, c, fs=12.4)
ax.text(3.42, 1.72, "Critique asks: which required predicate is unsupported, which evidence is missing, and what should be searched next?", fontsize=14.2, color=COL["muted"])
slides.append(save_slide(fig, 2, "workflow"))

# Slide 3
fig, ax = fig_ax()
title(ax, "Application: release-ready database rows", "Fixed 50-row cohorts test whether the system can produce useful entries, including valid compounds absent from existing benchmarks.")
# stacked bars
plot = fig.add_axes([0.58, 0.28, 0.38, 0.50], facecolor=COL["panel"])
plot.set_title("Release audit over five domains", loc="left", fontsize=17, fontweight="bold", color=COL["ink"], pad=12)
vals = {"benchmark overlap":178, "benchmark-missing true":68, "false":4}
left = 0
for lab, val, c in [("benchmark overlap",178,COL["blue"]),("benchmark-missing true",68,COL["green"]),("false",4,COL["red"] )]:
    plot.barh([0], [val], left=left, color=c, edgecolor="white", height=0.42, label=lab)
    plot.text(left+val/2, 0, str(val), ha="center", va="center", fontsize=17, fontweight="bold", color="white" if val>20 else COL["ink"])
    left += val
plot.set_xlim(0,250); plot.set_yticks([]); plot.set_xlabel("rows out of 250"); plot.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5,-0.34), ncol=3, fontsize=10)
plot.spines[['left','top','right']].set_visible(False); plot.grid(axis='x', color=COL['line'], lw=0.8); plot.set_axisbelow(True)
metric_card(ax, 0.78, 4.85, 4.75, 2.05, "178", "Known entries", "Matched benchmark compounds after identity normalization.", COL["blue"])
metric_card(ax, 0.78, 2.62, 4.75, 2.05, "68", "Benchmark-missing valid", "Non-overlap compounds judged valid by human experts.", COL["green"])
metric_card(ax, 0.78, 0.39, 4.75, 2.05, "4", "Low release error", "Non-overlap errors in the fixed-cohort audit.", COL["red"])
ax.text(6.0, 0.68, wrap("Scientific punchline: the system recovers known entries and surfaces literature-buried additions with auditable evidence.", 68), fontsize=13.8, color=COL["muted"], linespacing=1.16)
slides.append(save_slide(fig, 3, "application_release"))

# Slide 4
fig, ax = fig_ax()
title(ax, "Verification: evidence trails survive paper-level audit", "The strongest result is not name generation. It is whether citations resolve to real papers and contain candidate-relevant support.")
card(ax, 0.78, 4.72, 4.5, 2.45, "DB-Curator fixed-cohort audit", "All cited primary-paper references contained the quoted span or equivalent local context.", COL["green"], "2,166/2,166")
card(ax, 5.78, 4.72, 4.5, 2.45, "Zero-shot direct generation", "The baseline produced plausible rows, but only a small fraction had usable content support.", COL["red"], "11/257")
card(ax, 10.78, 4.72, 4.5, 2.45, "Benchmark-scale audit", "Across supplied candidates, DB-Curator maintained quote/context support for almost all cited references.", COL["blue"], "7,430/7,453")
# visual contrast
plot = fig.add_axes([0.08, 0.14, 0.84, 0.28], facecolor=COL["panel"])
plot.set_xlim(0,1); plot.set_ylim(0,3); plot.axis('off')
rows = [("DB-Curator release audit",1.0,COL["green"],"100%"),("Zero-shot generation",11/257,COL["red"],"4.3%"),("DB-Curator benchmark-scale",7430/7453,COL["blue"],"99.7%")]
for i,(lab,v,c,pct) in enumerate(rows):
    y=2.55-i*0.9
    plot.text(0.02,y,lab,ha='left',va='center',fontsize=14,fontweight='bold',color=COL['ink'])
    plot.add_patch(patches.Rectangle((0.34,y-0.17),0.52,0.34,fc="#EEF2F4",ec='none'))
    plot.add_patch(patches.Rectangle((0.34,y-0.17),0.52*v,0.34,fc=c,ec='none'))
    plot.text(0.89,y,pct,ha='left',va='center',fontsize=15,fontweight='bold',color=c)
ax.text(0.82, 0.55, "Verification rule: resolve paper identity → search recovered text → accept exact quote or equivalent local context → exclude database lookup pages.", fontsize=13.4, color=COL["muted"])
slides.append(save_slide(fig, 4, "verification"))

# Slide 5
fig, ax = fig_ax()
title(ax, "Benchmark-scale verification across scientific domains", "Five chemistry and biomedicine domains test whether agentic verification generalizes beyond one curated task.")
plot = fig.add_axes([0.38, 0.26, 0.57, 0.50], facecolor=COL["panel"])
topics = ["DBP", "Blood", "Drug", "Endog.", "Microbial\nNP"]
confirmed = [321,86,210,123,237]
total = [687,300,300,300,300]
baseline = [137,5,120,69,44]
x = range(len(topics))
plot.bar([i-0.18 for i in x], [c/t for c,t in zip(confirmed,total)], width=0.34, color=COL["blue"], label="DB-Curator")
plot.bar([i+0.18 for i in x], [c/t for c,t in zip(baseline,total)], width=0.34, color=COL["gray"], label="zero-shot baseline")
for i,(c,t) in enumerate(zip(confirmed,total)):
    plot.text(i-0.18, c/t+0.035, f"{c}/{t}", ha='center', fontsize=10.5, fontweight='bold', color=COL['blue'])
plot.set_ylim(0,0.9); plot.set_ylabel("Confirmed fraction"); plot.set_xticks(list(x), topics); plot.legend(frameon=False, loc='upper left', fontsize=10); plot.grid(axis='y', color=COL['line']); plot.set_axisbelow(True)
metric_card(ax, 0.78, 5.10, 3.7, 1.75, "1,887", "Scale", "Five scientific database domains.", COL["blue"])
metric_card(ax, 0.78, 3.18, 3.7, 1.75, "977", "Confirmed", "Evidence-supported entries.", COL["green"])
metric_card(ax, 0.78, 1.26, 3.7, 1.75, "375", "Baseline", "Direct labeling without retrieval.", COL["gray"])
ax.text(5.2, 0.62, wrap("ML takeaway: this is not one classifier threshold. Different topic definitions create different predicate gates and failure modes.", 92), fontsize=13.4, color=COL["muted"])
slides.append(save_slide(fig, 5, "benchmark_scale"))

# Slide 6
fig, ax = fig_ax()
title(ax, "Why the agentic loop matters", "Critique-guided retrieval changes decisions and leaves uncertain cases evidence-limited rather than hallucinated.")
plot = fig.add_axes([0.62, 0.50, 0.35, 0.30], facecolor=COL["panel"])
labels = ["Researcher\nfirst", "After\ncritique"]
vals = [933,977]
plot.bar(labels, vals, color=[COL["gray"], COL["orange"]], width=0.55)
for i,v in enumerate(vals): plot.text(i, v+18, str(v), ha='center', fontsize=14, fontweight='bold')
plot.set_ylim(0,1080); plot.set_ylabel("Confirmed rows"); plot.set_title("Critique revises verification", loc="left", fontsize=16, fontweight="bold"); plot.grid(axis='y', color=COL['line']); plot.set_axisbelow(True)
plot2 = fig.add_axes([0.62, 0.12, 0.35, 0.28], facecolor=COL["panel"])
plot2.bar(["Aligned", "Need more\nevidence"], [51,3], color=[COL["green"], COL["gold"]], width=0.55)
plot2.text(0,53,"51/54",ha='center',fontsize=14,fontweight='bold'); plot2.text(1,5,"3/54",ha='center',fontsize=14,fontweight='bold')
plot2.set_ylim(0,58); plot2.set_ylabel("changed decisions"); plot2.set_title("Human audit of changed labels", loc="left", fontsize=16, fontweight="bold"); plot2.grid(axis='y', color=COL['line']); plot2.set_axisbelow(True)
# left mechanism
card(ax, 0.78, 5.35, 4.55, 1.55, "1. Researcher", "Finds papers, reads context and proposes a label with evidence.", COL["blue"])
card(ax, 0.78, 3.45, 4.55, 1.55, "2. Critique", "Checks the claim against rubric predicates and asks for targeted follow-up.", COL["orange"])
card(ax, 0.78, 1.55, 4.55, 1.55, "3. Terminal state", "Accept only when supported; otherwise return evidence-limited or explicit negative.", COL["green"])
arrow(ax, 3.05, 5.35, 3.05, 5.08, COL["darkgray"]); arrow(ax, 3.05, 3.45, 3.05, 3.20, COL["darkgray"])
ax.text(0.82, 0.62, "Scientific takeaway: the user receives inspectable database rows, not a hidden chain-of-thought or an unverified answer.", fontsize=13.4, color=COL["muted"])
slides.append(save_slide(fig, 6, "agentic_loop"))

# PDF
pdf_path = OUT / "dbcurator_agentic_science_demo.pdf"
with PdfPages(pdf_path) as pdf:
    for png in slides:
        img = plt.imread(png)
        fig = plt.figure(figsize=(W,H), dpi=DPI)
        ax = fig.add_axes([0,0,1,1])
        ax.imshow(img)
        ax.axis('off')
        pdf.savefig(fig, bbox_inches=None, pad_inches=0)
        plt.close(fig)

# PPTX with full-slide images
pptx_path = OUT / "dbcurator_agentic_science_demo.pptx"
prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
blank = prs.slide_layouts[6]
for png in slides:
    slide = prs.slides.add_slide(blank)
    slide.shapes.add_picture(str(png), 0, 0, width=prs.slide_width, height=prs.slide_height)
prs.save(pptx_path)

notes = OUT / "dbcurator_agentic_science_demo_outline.md"
notes.write_text("""# DB-Curator agentic science demo outline

Audience: ML experts and scientists interested in agentic systems for scientific domains.

## Slide 1 — Agentic scientific curation
Core message: scientific database construction is not Q&A. It is a controlled curation workflow with dynamic literature construction and predicate-state verification.

## Slide 2 — How the workflow works
Core message: the paper set is built during the run, and each candidate is checked against explicit acceptance predicates.

## Slide 3 — Application: release-ready database rows
Core message: DB-Curator recovers known entries and also finds 68 valid benchmark-missing compounds, while keeping non-overlap errors low.

## Slide 4 — Verification: evidence trails survive paper-level audit
Core message: the key win is evidence support, not name generation. DB-Curator citations survive paper/context audit; zero-shot generation mostly does not.

## Slide 5 — Benchmark-scale verification across scientific domains
Core message: the system verifies 1,887 candidate rows across five domains, assigning 977 Confirmed labels with topic-specific evidence standards.

## Slide 6 — Why the agentic loop matters
Core message: critique-guided retrieval changes labels and makes uncertainty explicit. The output is an auditable database row, not an unverified answer.
""")

print(pptx_path)
print(pdf_path)
print(notes)
