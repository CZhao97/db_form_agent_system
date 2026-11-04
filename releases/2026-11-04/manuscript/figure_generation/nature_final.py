"""Produce Figures 2-6 and Supplementary Figures 2-3 from frozen data.

No model calls. Frozen input hashes are recorded in NATURE_FINAL_QA.json and
plotted values in PLOTTED_VALUES.json. Figure 1's existing artwork is unchanged.
Study-design notes belong in captions, not grey subtitles inside the figures.
"""
import argparse
from collections import Counter
import csv
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import re
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import gaussian_kde
from matplotlib.colors import LinearSegmentedColormap, to_rgb
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch, Rectangle
from matplotlib.text import Text

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'source_data'
STORY = DATA / 'story_panels'
CASES = ROOT.parent / 'source_data/final_confirmed_evidence_inspection/all_11_inspections.json'
CASE_SENTENCES = ROOT.parent / 'source_data/figure6_verbatim_20261103/sentences.json'
REVIEW = ROOT.parent / 'source_data/human_comment_recheck/color_review_summary_20261029.json'
CONSTRUCTION_RECALL = ROOT.parent / 'source_data/construction_recall_20261103/SUMMARY.json'
BENCHMARK_REVIEW = ROOT.parent / 'source_data/human_comment_recheck/benchmark_review_overlay_20261030.csv'
FEEDBACK = ROOT.parent / 'source_data/manuscript_clarity_20261101'
TABLE1 = DATA / 'merged_table1'
OUT = ROOT.parent / 'figures/nature'

# ---------------------------------------------------------------- visual constants
W = 180                                   # Nature double-column width, mm
INK, GREY, AXIS, GRID, PALE = '#27323A', '#65727A', '#67747C', '#E6EAEC', '#F1F4F5'
# Topic palette (checked for normal-vision and CVD separation; see NATURE_FINAL_QA.json)
TOPIC = ['#4D7893', '#C28570', '#66998D', '#B6A05E', '#978BA8']
TOPICS = ['dbp', 'blood_exposome', 'drug_compounds', 'human_endogenous_metabolites',
          'microbial_natural_products']
NAMES = ['DBPs', 'Blood exposome', 'Drugs', 'Endogenous', 'Microbial NP']
LONG = ['Disinfection by-products', 'Blood exposome', 'Drugs', 'Endogenous metabolites',
        'Microbial natural products']
# Evidence-depth sequence: one hue, light -> dark
ZERO, FROZEN, ADAPT, FULL = '#D4DADD', '#B1C4CF', '#7E9FB3', '#426D86'
STAGE = [ZERO, FROZEN, ADAPT, FULL]
SYSTEM = FULL                              # DB-Curator
BASE = '#8A8F94'                           # zero-shot / baseline
ROSE = '#B77573'                           # non-confirmed / unresolved
AMBER = '#AB8D58'                          # Critique
QA, VALUES = [], {}


def tint(color, strength):
    """Mix a colour towards white; strength 1 = colour, 0 = white."""
    return tuple(1 - strength * (1 - v) for v in to_rgb(color))


def style():
    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': ['Arial', 'Helvetica', 'Liberation Sans', 'Nimbus Sans', 'DejaVu Sans'],
        'font.size': 6.8, 'axes.labelsize': 6.8, 'xtick.labelsize': 6.4, 'ytick.labelsize': 6.7,
        'axes.linewidth': .5, 'axes.edgecolor': AXIS, 'axes.labelcolor': INK, 'text.color': INK,
        'xtick.color': AXIS, 'ytick.color': INK, 'xtick.major.width': .5, 'ytick.major.width': .5,
        'xtick.major.size': 2, 'ytick.major.size': 2, 'xtick.major.pad': 2, 'ytick.major.pad': 2,
        'axes.labelpad': 3, 'axes.spines.top': False, 'axes.spines.right': False,
        'legend.frameon': False, 'legend.fontsize': 6.5, 'legend.handlelength': 1.4,
        'svg.fonttype': 'none', 'pdf.fonttype': 42, 'savefig.facecolor': 'white',
        'mathtext.default': 'regular'})


def read(path):
    with path.open(encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


class Canvas:
    """Figure laid out in millimetres from the top-left corner."""

    def __init__(self, height):
        self.h = height
        self.fig = plt.figure(figsize=(W / 25.4, height / 25.4))

    def ax(self, x, y, w, h):
        return self.fig.add_axes([x / W, (self.h - y - h) / self.h, w / W, h / self.h])

    def text(self, x, y, s, **kw):
        kw.setdefault('va', 'baseline')
        return self.fig.text(x / W, (self.h - y) / self.h, s, **kw)

    def panel(self, x, y, letter, title=None):
        self.text(x, y, letter, fontsize=8.5, fontweight='bold')
        if title:
            self.text(x + 4.2, y, title, fontsize=7.3, fontweight='bold')

    def legend(self, y, handles, x=.5, **kw):
        kw.setdefault('ncol', len(handles))
        self.fig.legend(handles=handles, loc='center', bbox_to_anchor=(x, 1 - y / self.h),
                        handletextpad=.5, columnspacing=1.6, **kw)


def rows(ax, labels, xlim=(0, 100), ticks=(0, 50, 100), xlabel=None, pad=.5, show=True):
    n = len(labels)
    ax.set(xlim=xlim, ylim=(n - 1 + pad, -pad), yticks=range(n), xticks=ticks, xlabel=xlabel)
    ax.set_yticklabels(labels if show else [])
    ax.spines['left'].set_visible(False)
    ax.tick_params(axis='y', length=0, pad=3)
    ax.grid(axis='x', color=GRID, lw=.5)
    ax.set_axisbelow(True)
    return ax


def side(ax, x, y, s, **kw):
    """Text column beside an axis: x in axes fraction, y in data units."""
    return ax.text(x, y, s, transform=ax.get_yaxis_transform(), va='center',
                   ha=kw.pop('ha', 'left'), fontsize=kw.pop('fontsize', 6.3),
                   color=kw.pop('color', INK), clip_on=False, **kw)


def dot(ax, x, y, color, ms=4.6, marker='o', filled=True, z=4):
    ax.plot(x, y, marker, ms=ms, mfc=color if filled else 'white', mec=color if not filled else 'white',
            mew=.9 if not filled else .6, zorder=z, clip_on=False)
    if filled:                                   # white ring, then colour
        ax.plot(x, y, marker, ms=ms, mfc=color, mec=color, mew=.0, zorder=z + 1, clip_on=False)


def per_entry(records, retained):
    return str((Decimal(records) / Decimal(retained)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def checked_interval(ax, point, low, high, y, color, aggregate=False):
    xmin, xmax = ax.get_xlim()
    assert xmin < low <= point <= high < xmax, (point, low, high, (xmin, xmax))
    ax.plot([low, high], [y, y], color=color, lw=1.0 if aggregate else .8,
            solid_capstyle='butt', zorder=3)
    ax.plot(point, y, 's' if aggregate else 'o', ms=4.6 if aggregate else 3.8,
            mfc=color, mec='white', mew=.5, zorder=4)


def save(canvas, name):
    fig = canvas.fig
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    texts = [t for t in fig.findobj(Text) if t.get_visible() and t.get_text().strip()]
    boxes = [Text.get_window_extent(t, r) for t in texts]   # text only, leader lines excluded
    overlaps, outside, small = [], [], []
    for i, b in enumerate(boxes):
        if b.x0 < -.5 or b.y0 < -.5 or b.x1 > fig.bbox.width + .5 or b.y1 > fig.bbox.height + .5:
            outside.append(texts[i].get_text())
        if texts[i].get_fontsize() < 5:
            small.append(texts[i].get_text())
        for j in range(i + 1, len(boxes)):
            q = boxes[j]
            if min(b.x1, q.x1) - max(b.x0, q.x0) > 1 and min(b.y1, q.y1) - max(b.y0, q.y0) > 1:
                overlaps.append([texts[i].get_text(), texts[j].get_text()])
    for ext in ['pdf', 'svg', 'png', 'tiff']:
        kw = {'dpi': 600 if ext == 'tiff' else 300}
        if ext == 'tiff':
            kw['pil_kwargs'] = {'compression': 'tiff_lzw'}
        fig.savefig(OUT / f'{name}.{ext}', **kw)
    QA.append({'figure': name, 'size_mm': [W, canvas.h], 'text_overlaps': overlaps,
               'out_of_bounds_text': outside, 'text_below_5pt': small})
    plt.close(fig)


# ================================================================ Figure 1: schematic
class Draw:
    def __init__(self, ax):
        self.a = ax

    def box(self, x, y, w, h, fc='white', ec=GREY, lw=.5, r=1.0, ls='-', z=2):
        self.a.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f'round,pad=0,rounding_size={r}',
                                        fc=fc, ec=ec, lw=lw, ls=ls, zorder=z))

    def t(self, x, y, s, size=6.2, color=INK, ha='center', va='center', z=6, **kw):
        return self.a.text(x, y, s, fontsize=size, color=color, ha=ha, va=va, zorder=z, **kw)

    def arrow(self, p, q, color=AXIS, lw=.6, rad=0, style='-|>', ms=5, z=3, ls='-'):
        self.a.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=ms, color=color,
                                         lw=lw, ls=ls, connectionstyle=f'arc3,rad={rad}',
                                         zorder=z, shrinkA=1, shrinkB=1))

    def chip(self, x, y, s, color, size=5.2):
        self.a.add_patch(FancyBboxPatch((x - 1.6, y - 1.25), 3.2, 2.5, boxstyle='round,pad=0,rounding_size=.5',
                                        fc=tint(color, .18), ec='none', zorder=5))
        self.t(x, y, s, size=size, color=color, fontweight='bold')

    def state(self, x, y, kind):
        if kind == 'supported':
            self.a.plot(x, y, 'o', ms=3.6, mfc=SYSTEM, mec=SYSTEM, zorder=6, clip_on=False)
        elif kind == 'unresolved':
            self.a.plot(x, y, 'o', ms=3.6, mfc='white', mec=GREY, mew=.8, zorder=6, clip_on=False)
        elif kind == 'contradicted':
            self.a.plot(x, y, 'D', ms=3.1, mfc='white', mec=ROSE, mew=.8, zorder=6, clip_on=False)


def figure1():
    H = 98
    c = Canvas(H)
    ax = c.ax(0, 0, W, H)
    ax.set(xlim=(0, W), ylim=(H, 0))
    ax.axis('off')
    d = Draw(ax)
    # Stage headers
    stages = [(2, 40, '1', 'Scope and rubric'), (46, 44, '2', 'Topic-level discovery'),
              (94, 50, '3', 'Candidate-level research loop'), (148, 30, '4', 'Decision and record')]
    for x, w, n, title in stages:
        d.t(x, 5, n, size=8, ha='left', fontweight='bold')
        d.t(x + 4.5, 5, title, size=7, ha='left', fontweight='bold')
        ax.plot([x, x + w], [8.2, 8.2], color=INK, lw=.6)
    # ---- Stage 1
    d.box(4, 12, 34, 7, fc=PALE, ec='none')
    d.t(21, 15.5, 'User request', size=6.3)
    d.arrow((21, 19.3), (21, 24.5))
    d.box(4, 25, 34, 7, fc='white', ec=GREY)
    d.t(21, 28.5, 'Refinement agent', size=6.3)
    d.arrow((21, 32.3), (21, 37.5))
    # specification card
    d.box(4, 38, 34, 38, fc='white', ec=INK, lw=.6)
    d.t(6, 42, 'Approved specification', size=6.3, ha='left', fontweight='bold')
    d.t(6, 47.5, 'Topic definition', size=6, ha='left')
    ax.plot([6, 36], [50.5, 50.5], color=GRID, lw=.6)
    d.t(6, 54, 'Rubric', size=6, ha='left', fontweight='bold')
    for k, (code, label, col) in enumerate([('M', 'Mandatory criteria', SYSTEM),
                                            ('X', 'Exclusions', ROSE),
                                            ('O', 'Optional guidance', GREY)]):
        y = 59 + k * 5.2
        d.chip(8.4, y, code, col)
        d.t(12, y, label, size=6, ha='left')
    d.t(21, 80, 'User inspects, edits and approves', size=5.6, color=GREY)
    # ---- Stage 2
    x0 = 46
    d.box(x0, 12, 44, 8, fc='white', ec=GREY)
    d.t(x0 + 22, 14.6, 'Rubric-derived queries', size=6.3)
    d.t(x0 + 22, 18, 'definition, evidence concepts, exclusions', size=5.3, color=GREY)
    d.arrow((x0 + 22, 20.3), (x0 + 22, 25.5))
    d.box(x0, 26, 44, 11, fc=PALE, ec='none')
    d.t(x0 + 22, 29.3, 'Literature sources', size=6.3)
    d.t(x0 + 22, 33.6, 'online APIs  ·  offline corpus (6.3 M records)', size=5.3, color=GREY)
    d.arrow((x0 + 22, 37.3), (x0 + 22, 42.5))
    d.box(x0, 43, 44, 11, fc='white', ec=GREY)
    d.t(x0 + 22, 46.3, 'Chemical entity recognition', size=6.3)
    d.t(x0 + 22, 50.6, 'source-linked mentions  ·  PubChem grounding', size=5.3, color=GREY)
    d.arrow((x0 + 22, 54.3), (x0 + 22, 59.5))
    d.box(x0, 60, 44, 16, fc='white', ec=INK, lw=.6)
    d.t(x0 + 22, 64, 'Candidate compounds', size=6.3, fontweight='bold')
    for k in range(7):
        ax.plot(x0 + 7 + k * 5, 69.5, 'o', ms=3.4, mfc=tint(SYSTEM, .25 + .1 * k), mec='none', zorder=6)
    d.t(x0 + 22, 73.5, 'seed compounds and classes expand the search', size=5.3, color=GREY)
    # ---- Stage 3
    x1 = 94
    d.box(x1, 12, 50, 30, fc=tint(SYSTEM, .06), ec=SYSTEM, lw=.6)
    d.t(x1 + 2.5, 16, 'Researcher', size=6.5, ha='left', fontweight='bold')
    d.t(x1 + 2.5, 20.5, 'search  →  read  →  assess each criterion', size=5.8, ha='left')
    # criterion state strip
    for k, (code, kind, label) in enumerate([('M', 'supported', 'supported'),
                                             ('M', 'unresolved', 'unresolved'),
                                             ('X', 'contradicted', 'contradicted')]):
        y = 26 + k * 4.4
        d.chip(x1 + 4.6, y, code, SYSTEM if code == 'M' else ROSE, size=5)
        ax.plot([x1 + 7.5, x1 + 25], [y, y], color=GRID, lw=1.6, solid_capstyle='butt', zorder=4)
        d.state(x1 + 27, y, kind)
        d.t(x1 + 29.5, y, label, size=5.6, ha='left', color=GREY)
    d.t(x1 + 2.5, 39.3, 'unresolved criteria become the next search targets', size=5.3, ha='left', color=GREY)
    # down to critique
    d.arrow((x1 + 25, 42.3), (x1 + 25, 49.5), color=INK)
    d.t(x1 + 23, 46, 'draft label + evidence', size=5.3, ha='right', color=GREY)
    d.box(x1, 50, 50, 20, fc=tint(AMBER, .08), ec=AMBER, lw=.6)
    d.t(x1 + 2.5, 54, 'Critique', size=6.5, ha='left', fontweight='bold')
    d.t(x1 + 2.5, 58.3, 'criterion-by-criterion re-review of the reasoning', size=5.8, ha='left')
    d.t(x1 + 2.5, 62.3, 'requests follow-up for a named unresolved criterion,', size=5.6, ha='left', color=GREY)
    d.t(x1 + 2.5, 66, 'or accepts the draft', size=5.6, ha='left', color=GREY)
    # follow-up loop back to researcher (right side)
    d.arrow((x1 + 40, 49.7), (x1 + 40, 42.3), color=AMBER, ms=5)
    d.t(x1 + 41.5, 46, 'follow-up', size=5.3, color=AMBER, ha='left')
    # accept arrow to stage 4
    d.arrow((x1 + 50.5, 64), (x1 + 53.5, 64), color=INK)
    d.t(x1 + 52, 68.5, 'accept', size=5.3, color=GREY)
    # ---- Stage 4
    x2 = 148
    d.box(x2, 12, 30, 24, fc='white', ec=INK, lw=.6)
    d.t(x2 + 2, 15.8, 'Decision contract', size=6.3, ha='left', fontweight='bold')
    for k, s in enumerate(['mandatory criteria supported', 'exclusions contradicted',
                           'every paper citation located', 'in its source']):
        y = 20.5 + k * 3.7
        if k != 3:
            d.state(x2 + 3.5, y, 'supported')
        d.t(x2 + 6, y, s, size=5.4, ha='left')
    d.arrow((x2 + 15, 36.3), (x2 + 15, 41.5), color=INK)
    d.box(x2, 42, 30, 7.5, fc=tint(SYSTEM, .12), ec='none')
    d.t(x2 + 15, 45.8, 'Confirmed  ·  released row', size=6.1, fontweight='bold', color=SYSTEM)
    d.t(x2 + 15, 53, 'otherwise', size=5.3, color=GREY)
    for k, s in enumerate(['Suspected', 'Insufficient Direct Evidence', 'Explicit Negative Evidence']):
        y = 56 + k * 4.2
        d.state(x2 + 3.5, y, 'unresolved' if k < 2 else 'contradicted')
        d.t(x2 + 6, y, s, size=5.6, ha='left', color=GREY)
    # record card
    d.box(x2, 69, 30, 20, fc=PALE, ec='none')
    d.t(x2 + 2, 72.5, 'Audit record', size=6, ha='left', fontweight='bold')
    for k, s in enumerate(['identity and label', 'criterion assessments', 'cited passages with sources']):
        d.t(x2 + 2, 76.8 + k * 3.8, s, size=5.4, ha='left')
    # ---- Shared rubric band
    yb = 92
    ax.plot([4, 178], [yb, yb], color=SYSTEM, lw=.8)
    d.t(4, yb + 3.5, 'One approved rubric guides search planning, evidence assessment, review and release',
        size=5.8, ha='left', color=SYSTEM)
    for xx in (68, 119, 163):
        d.arrow((xx, yb - .3), (xx, 89.5), color=SYSTEM, ms=5.5, lw=.6)
    # stage connectors
    d.arrow((38.5, 57), (45.5, 57), color=INK)
    ax.plot([90.5, 92.2, 92.2], [68, 68, 27], color=INK, lw=.6, zorder=3)
    d.arrow((92.2, 27), (93.8, 27), color=INK)
    d.t(91.2, 47, 'per candidate', size=5.1, color=GREY, rotation=90)
    save(c, 'Figure1')


# ================================================================ Figure 2
def figure2():
    data = {r['topic']: {k: int(v) for k, v in r.items() if k != 'topic'}
            for r in read(DATA / 'construction_final.csv')}
    processed = sum(r['processed_candidates'] for r in data.values())
    retained = sum(r['final_confirmed'] for r in data.values())
    c = Canvas(190)
    c.panel(2, 6, 'a', f'{processed:,} processed, {retained:,} retained')
    c.panel(2, 72, 'b', 'Benchmark-linked retention')
    c.panel(96, 72, 'c', 'Benchmark-matched entries')
    c.panel(2, 136, 'd', 'Paper and quotation checks')
    c.panel(96, 136, 'e', 'Precision and processed-pool recall')
    # a: trajectories and their endpoints are one construction result.
    a = draw_accumulation(c, (15, 16, 84, 39), None, compact=True)
    a.set_gid('construction_trajectory')
    a.set_xticks([0, 200, 400, 600])
    c.text(111, 16, 'Topic', fontsize=6.7)
    c.text(153, 16, 'Processed', fontsize=6.7, ha='right')
    c.text(178, 16, 'Per entry', fontsize=6.7, ha='right')
    for i, t in enumerate(TOPICS):
        r = data[t]
        y = 25 + i * 7
        c.fig.add_artist(Line2D([106/W, 109/W], [1-y/c.h]*2, color=TOPIC[i], lw=1.5))
        c.text(111, y, NAMES[i], fontsize=6.8, va='center')
        c.text(153, y, f"{r['processed_candidates']:,}", fontsize=7.2,
               fontweight='bold', ha='right', va='center')
        c.text(178, y, per_entry(r['processed_candidates'], r['final_confirmed']),
               fontsize=6.8, ha='right', va='center')
    # b: retained share of all encountered benchmark identities.
    b = rows(c.ax(26, 81, 44, 35), NAMES, xlabel='Retained benchmark identities (%)')
    b.set_gid('benchmark_retention')
    side(b, 1.05, -.95, 'Retained /\nencountered', color=INK, fontsize=6.7)
    for i, t in enumerate(TOPICS):
        r = data[t]
        n, dn = r['released_benchmark_linked'], r['processed_benchmark_linked']
        v = 100 * n / dn
        b.barh(i, 100, .62, color=PALE, lw=0)
        b.barh(i, v, .62, color=tint(TOPIC[i], .30), lw=0)
        b.plot(v, i, 'o', ms=4.2, mfc=TOPIC[i], mec='white', mew=.6, zorder=4)
        b.text(2.5, i, f'{v:.1f}%', va='center', fontsize=7, color=INK, fontweight='bold')
        side(b, 1.05, i, f'{n}/{dn}', fontsize=6.8)
    # c: paired bars encode method by tone, without competing marker shapes.
    cc = rows(c.ax(112, 81, 43, 35), NAMES, xlabel='Benchmark-matched entries (%)', show=False)
    cc.set_gid('benchmark_method_comparison')
    side(cc, 1.05, -.95, 'Matched / proposed', color=INK, fontsize=6.4)
    for i, t in enumerate(TOPICS):
        r = data[t]
        db, z = r['released_benchmark_linked'], r['zero_shot_benchmark_linked']
        for offset, n, denominator, strength in [(-.18, db, r['final_confirmed'], .85),
                                                  (.18, z, r['zero_shot_candidates'], .28)]:
            cc.barh(i + offset, 100 * n / denominator, .28, color=tint(TOPIC[i], strength), lw=0)
            side(cc, 1.05, i + offset, f'{n}/{denominator}', fontsize=6.5)
    c.legend(127.5, [Line2D([], [], lw=4, color=tint(SYSTEM, .85), label='DB-Curator'),
                    Line2D([], [], lw=4, color=tint(SYSTEM, .28), label='Zero-shot')],
             x=143/W, fontsize=6.5, handlelength=1.6)
    # d: citation traceability retains its independent citation denominator.
    d = c.ax(26, 150, 44, 21)
    d.set_gid('citation_traceability')
    d.set(xlim=(0, 100), ylim=(1.6, -.6), xticks=[0, 50, 100], yticks=[0, 1],
          xlabel='Matched paper and passage (%)')
    d.set_yticklabels(['DB-Curator', 'Zero-shot'])
    d.spines['left'].set_visible(False)
    d.tick_params(axis='y', length=0, pad=3)
    d.grid(axis='x', color=GRID, lw=.5)
    d.set_axisbelow(True)
    tot = {k: sum(r[k] for r in data.values()) for k in next(iter(data.values()))}
    for y, n, dn, col in [(0, tot['verified_citations'], tot['citation_instances'], SYSTEM),
                          (1, tot['zero_shot_verified'], tot['zero_shot_citations'], BASE)]:
        d.barh(y, 100, .55, color=PALE, lw=0)
        d.barh(y, 100 * n / dn, .55, color=tint(col, .35), lw=0)
        d.plot(100*n/dn, y, 'o', ms=5, mfc=col, mec='white', mew=.6, clip_on=False)
        side(d, 1.05, y, f'{n:,}/{dn:,}', fontsize=7.0)
    side(d, 1.05, -.9, 'Matched / cited', color=INK, fontsize=6.7)
    # e: a count matrix avoids magnifying small differences near 100%.
    draw_construction_review(c)
    VALUES['Figure2'] = data
    save(c, 'Figure2')


def draw_construction_review(c):
    review = json.loads(REVIEW.read_text())['cohorts']
    cohorts = [review['construction_250_labeled_version'], review['zero_shot_250']]
    recall = json.loads(CONSTRUCTION_RECALL.read_text())
    recall_topics = {row['topic']: row for row in recall['topic_results']}
    overall = recall['overall']
    assert overall['TP'] == cohorts[0]['agreement']
    assert overall['TP'] + overall['FP'] == cohorts[0]['n']
    centers = [128.5, 149, 170]
    columns = [
        ('DB-Curator\nprecision', cohorts[0]['agreement'], cohorts[0]['n']),
        ('Zero-shot\nprecision', cohorts[1]['agreement'], cohorts[1]['n']),
        ('DB-Curator\nrecall', overall['TP'], overall['TP'] + overall['FN']),
    ]
    ax = c.ax(96, 140, 83, 47)
    ax.set_gid('construction_expert_review')
    ax.set(xlim=(96, 179), ylim=(187, 140))
    ax.axis('off')
    for x, (method, n, total) in zip(centers, columns):
        ax.text(x, 144, method, ha='center', va='center', fontsize=6.4, linespacing=1.1)
        ax.text(x, 153.3, f'{n}/{total}', ha='center', va='center', fontsize=6.5)
    for i, topic in enumerate(TOPICS):
        y = 158.8 + 6 * i
        ax.text(117.5, y, NAMES[i], ha='right', va='center', fontsize=6.5)
        r = recall_topics[topic]
        assert r['TP'] == cohorts[0]['topics'][topic]['agreement']
        assert r['TP'] + r['FP'] == cohorts[0]['topics'][topic]['n']
        counts = [(cohort['topics'][topic]['agreement'], cohort['topics'][topic]['n'])
                  for cohort in cohorts] + [(r['TP'], r['TP'] + r['FN'])]
        for x, (n, total) in zip(centers, counts):
            assert 0 <= n <= total
            ax.text(x, y-.3, f'{n}/{total}', ha='center', va='center', fontsize=6.8)
            width = 18 * n / total
            ax.add_patch(Rectangle((x-9, y+1.3), width, 1.35,
                                   facecolor=tint(TOPIC[i], .6), edgecolor='none'))
            ax.add_patch(Rectangle((x-9+width, y+1.3), 18-width, 1.35,
                                   facecolor=ROSE, edgecolor='none'))
    c.legend(188, [Line2D([], [], lw=3, color=tint(SYSTEM, .6), label='Qualifying retained entries'),
                  Line2D([], [], lw=3, color=ROSE, label='Other')],
             x=143/W, fontsize=6.3)
    VALUES['Figure2_review'] = review
    VALUES['Figure2_recall'] = {'overall': overall, 'topics': recall_topics}


def benchmark_review_topics():
    mapping = dict(zip(['dbp_full_loop_merged_BL','blood_full_loop_gpu1_BL','drug_full_loop_gpu0_BL',
                        'endogenous_full_loop_BL','microbial_np_full_loop_gpu0_BL'], TOPICS))
    data = read(BENCHMARK_REVIEW)
    result = {t:dict(n=0,agreement=0) for t in TOPICS}
    for row in data:
        assert row['analysis_record_status'] == 'candidate_record'
        values = result[mapping[row['topic']]]
        values['n'] += 1
        values['agreement'] += row['review_20261030_agreement'] == 'True'
    assert sum(v['n'] for v in result.values()) == 1886
    assert sum(v['agreement'] for v in result.values()) == 1870
    return result


# ================================================================ Figure 3
def figure3():
    bench = {r['topic']: r for r in read(DATA / 'benchmark_final.csv')}
    labels = {r['topic']: json.loads(r['final_label_counts']) for r in read(DATA / 'benchmark_labels.csv')}
    experts = {r['cohort']: r for r in read(STORY / 'expert_review.csv')}
    review = json.loads(REVIEW.read_text())['cohorts']
    cats = [('Confirmed', SYSTEM), ('Suspected', tint(SYSTEM, .45)), ('Insufficient Direct Evidence', '#D9DDE1'),
            ('Explicit Negative Evidence', ROSE), ('Out of scope or class-level only', tint(ROSE, .35))]
    c = Canvas(189)
    c.panel(2, 6, 'a', 'Final Researcher predictions for 1,887 candidates')
    c.panel(2, 66, 'b', 'Expert-reviewed benchmark decisions')
    # a: stacked composition
    a = rows(c.ax(26, 14, 118, 36), NAMES, (0, 100), (0, 25, 50, 75, 100), 'Candidates (%)')
    side(a, 1.04, -.95, 'Confirmed', color=INK, fontsize=6.7)
    comp = {}
    for i, t in enumerate(TOPICS):
        lc = labels[t]
        n = int(bench[t]['candidates'])
        assert sum(lc.values()) == n and lc['Confirmed'] == int(bench[t]['final_confirmed'])
        other = lc.get('Out of Scope Matrix or Context', 0) + lc.get('Indirect or Class-Level Only', 0)
        parts = [lc['Confirmed'], lc.get('Suspected', 0), lc.get('Insufficient Direct Evidence', 0),
                 lc.get('Explicit Negative Evidence', 0), other]
        comp[t] = dict(zip([k for k, _ in cats], parts))
        left = 0
        for (name, col), v in zip(cats, parts):
            if v:
                a.barh(i, 100 * v / n, .62, left=left, color=tint(col, .65), lw=0)
                if 100 * v / n > 9:
                    a.text(left + 50 * v / n, i, f'{v}', ha='center', va='center', fontsize=6.7,
                           color=INK, fontweight='bold' if name == 'Confirmed' else 'normal')
                left += 100 * v / n
        side(a, 1.04, i, f"{lc['Confirmed']}/{n}  ({100 * lc['Confirmed'] / n:.1f}%)")
    c.legend(58, [Patch(fc=tint(col, .65), label=name) for name, col in cats], x=.5, ncol=5,
             handlelength=1.1, handleheight=.8)
    # b: keep the expert-reviewed benchmark cohort separate from new run labels.
    topic_review = benchmark_review_topics()
    b = rows(c.ax(26, 77, 118, 32), NAMES, xlabel='Agreement (%)', pad=.6)
    side(b, 1.04, -1.0, 'Agreed / reviewed', color=INK, fontsize=6.7)
    for i, topic in enumerate(TOPICS):
        r, col = topic_review[topic], TOPIC[i]
        n, dn = r['agreement'], r['n']
        b.barh(i, 100, .55, color=PALE, lw=0)
        b.barh(i, 100 * n / dn, .55, color=tint(col, .3), lw=0)
        b.plot(100*n/dn, i, 'o', ms=4.5, mfc=col, mec='white', mew=.6, clip_on=False)
        b.text(2.5, i, f'{100 * n / dn:.1f}%', va='center', fontsize=7, color=INK, fontweight='bold')
        side(b, 1.04, i, f'{n:,}/{dn:,}')
    VALUES['Figure3_benchmark_review'] = topic_review
    VALUES['Figure3'] = {'composition': comp, 'expert': experts,
                         'topic_review': {k: review[k]['topics'] for k in
                                          ('construction_250_labeled_version', 'zero_shot_250')}}
    operational_panels(c)
    save(c, 'Figure3')


def operational_rows():
    data = read(DATA / 'benchmark_operational_current.csv')
    assert len(data) == len({r['case_id'] for r in data}) == 1887
    labels = {r['topic']: json.loads(r['final_label_counts']) for r in read(DATA / 'benchmark_labels.csv')}
    for topic in TOPICS:
        assert Counter(r['final_label'] for r in data if r['topic'] == topic) == labels[topic]
    return data


def operational_panels(c):
    data = operational_rows()
    c.panel(2, 125, 'c', 'Tokens by Researcher prediction')
    c.panel(96, 125, 'd', 'Tokens and runtime')
    d = c.ax(14, 136, 69, 39)
    d.set_gid('prediction_token_density')
    groups = [('Confirmed', SYSTEM), ('Other outcomes', ROSE)]
    x = np.linspace(3.5, 6.8, 350)
    summary = {'tokens': {}, 'runtime': {}}
    for label, col in groups:
        group = [r for r in data if (r['final_label'] == 'Confirmed') == (label == 'Confirmed')
                 and r['token_status'] == 'complete_recorded_usage']
        vals = np.array([float(r['tokens']) for r in group])
        density = gaussian_kde(np.log10(vals))(x)
        d.fill_between(x, density, color=tint(col, .15))
        d.plot(x, density, color=tint(col, .85), lw=1.3)
        med = np.median(vals)
        d.plot([np.log10(med)]*2, [0, float(gaussian_kde(np.log10(vals))([np.log10(med)])[0])],
               color=col, lw=.7, ls=(0, (3, 2)))
        summary['tokens'][label] = {'n': len(vals), 'median': float(med)}
    d.set(xlim=(3.5, 6.8), ylim=(0, None), xticks=[4, 5, 6],
          xlabel='Recorded tokens per candidate', ylabel='Density')
    d.set_xticklabels(['10k', '100k', '1M'])
    d.set_yticks([0, 1, 2])
    c.legend(131, [Line2D([], [], color=col, lw=1.4, label=label) for label, col in groups], x=.27, ncol=2)
    _, summary['runtime'] = runtime_by_topic(data)
    assert sum(r['n'] for r in summary['tokens'].values()) == 1887
    assert sum(r['n'] for r in summary['runtime'].values()) == 1887
    VALUES['Figure3_resources'] = summary
    VALUES['Figure3_resource_relationship'] = draw_resource_relationship(
        c, (110, 136, 53, 39), (168, 140, 2.5, 31))


def runtime_by_topic(data):
    runtime, summary = [], {}
    for topic in TOPICS:
        vals = np.array([float(r['duration_sec'])/60 for r in data
                         if r['topic'] == topic and r['runtime_status'] == 'recorded'])
        runtime.append(np.log10(vals))
        summary[topic] = {'n': len(vals), 'median_minutes': float(np.median(vals))}
    return runtime, summary


def supplementary_runtime():
    runtime, summary = runtime_by_topic(operational_rows())
    c = Canvas(94)
    ax = c.ax(20, 7, 149, 69)
    ax.set_gid('topic_runtime_distribution')
    violin = ax.violinplot(runtime, positions=range(5), widths=.72, showextrema=False, bw_method=.3)
    for body, col in zip(violin['bodies'], TOPIC):
        body.set_facecolor(tint(col, .32)); body.set_edgecolor('none'); body.set_alpha(1)
    for i, vals in enumerate(runtime):
        q1, med, q3 = np.quantile(vals, [.25, .5, .75])
        ax.plot([i, i], [q1, q3], color=tint(TOPIC[i], .7), lw=1.2)
        ax.plot(i, med, 'o', ms=4.3, mfc=TOPIC[i], mec='white', mew=.5)
    runtime_limits = (min(v.min() for v in runtime) - .12, max(v.max() for v in runtime) + .12)
    ax.set(xlim=(-.6, 4.6), ylim=runtime_limits, xticks=range(5), yticks=[0, 1, 2], ylabel='Runtime (min)')
    ax.set_xticklabels(['DBPs', 'Blood\nexposome', 'Drugs', 'Endogenous\nmetabolites', 'Microbial\nnatural products'])
    ax.set_yticklabels(['1', '10', '100'])
    assert sum(r['n'] for r in summary.values()) == 1887
    VALUES['SupplementaryRuntime'] = summary
    save(c, 'SupplementaryRuntime')


def draw_resource_relationship(c, rectangle, colorbar_rectangle, show_n=False):
    data = [r for r in operational_rows() if r['token_status'] == 'complete_recorded_usage'
            and r['runtime_status'] == 'recorded']
    assert len(data) == 1887
    x = np.log10([float(r['tokens']) for r in data])
    y = np.log10([float(r['duration_sec']) / 60 for r in data])
    ax = c.ax(*rectangle)
    ax.set_gid('token_runtime_relationship')
    palette = LinearSegmentedColormap.from_list('resource_density', [tint(SYSTEM, .08), tint(SYSTEM, .5), SYSTEM])
    bins = ax.hexbin(x, y, gridsize=32, mincnt=1, cmap=palette, linewidths=0)
    ax.set(xlim=(4, 6.5), ylim=(-.35, 2.1), xticks=[4, 5, 6], yticks=[0, 1, 2],
           xlabel='Recorded tokens per candidate', ylabel='Runtime (min)')
    ax.set_xticklabels(['10k', '100k', '1M'])
    ax.set_yticklabels(['1', '10', '100'])
    correlation = float(np.corrcoef(x, y)[0, 1])
    label = (f'n = {len(data):,}\n' if show_n else '') + f'r = {correlation:.2f}'
    ax.text(.04, .95, label, transform=ax.transAxes, va='top', fontsize=7)
    cb = c.fig.colorbar(bins, cax=c.ax(*colorbar_rectangle))
    cb.set_ticks([1, 10, 20, 30])
    cb.set_label('Candidates per bin', fontsize=6.4)
    cb.outline.set_visible(False)
    assert int(np.sum(bins.get_array())) == len(data)
    return {'n': len(data), 'pearson_r_log10': correlation,
            'case_ids': [r['case_id'] for r in data]}


def supplementary_operational():
    c = Canvas(99)
    VALUES['SupplementaryOperational'] = draw_resource_relationship(
        c, (18, 8, 132, 74), (156, 23, 3, 43), show_n=True)
    save(c, 'SupplementaryOperational')


# ================================================================ Figure 4
def place_labels(values, min_gap):
    """Shift label positions apart (1-D) while keeping their order; returns new positions."""
    order = np.argsort(values)
    pos = np.array(values, dtype=float)[order]
    for k in range(1, len(pos)):
        if pos[k] - pos[k - 1] < min_gap:
            pos[k] = pos[k - 1] + min_gap
    # recentre to reduce total drift
    pos -= (pos - np.array(values)[order]).mean()
    out = np.empty_like(pos)
    out[order] = pos
    return out


def feedback_summary():
    summary = {r['arm']: r for r in read(FEEDBACK / 'feedback_operational_summary.csv')
               if r['subset'] == 'all100'}
    raw = read(FEEDBACK / 'feedback_all100_operational.csv')
    output, case_sets = [], []
    for arm in 'ABC':
        rows_ = [r for r in raw if r['arm'] == arm]
        case_sets.append({r['case_id'] for r in rows_})
        assert len(rows_) == len(case_sets[-1]) == 100
        assert all(sum(r['topic'] == topic for r in rows_) == 20 for topic in TOPICS)
        record = dict(arm=arm, n=100, confirmed=sum(r['confirmed'] == 'True' for r in rows_),
                      unfinished=sum(r['completed'] != 'True' for r in rows_),
                      mean_rounds=sum(float(r['rounds']) for r in rows_) / 100,
                      mean_tokens=sum(float(r['tokens']) for r in rows_) / 100,
                      mean_accounted_usd=sum(float(r['accounted_usd']) for r in rows_) / 100,
                      mean_source_files=sum(float(r['new_source_files']) for r in rows_) / 100)
        assert record['confirmed'] == int(summary[arm]['confirmed'])
        assert record['unfinished'] == 100 - int(summary[arm]['completed'])
        for key in ('mean_rounds', 'mean_tokens', 'mean_accounted_usd', 'mean_source_files'):
            assert abs(record[key] - float(summary[arm][key])) < 1e-6
        output.append(record)
    assert case_sets[0] == case_sets[1] == case_sets[2]
    return output


def figure4():
    rep = read(STORY / 'repeats.csv')
    paired = read(DATA / 'adjacent_stage_contrasts.csv')
    costs = {r['condition']: r for r in read(STORY / 'costs.csv')}
    keys = ['Zero-shot', 'Static RAG', 'Adaptive search', 'Full DB-Curator']
    counts = [int(costs[k]['confirmed'].split('/')[0]) for k in keys]
    clusters = read(DATA / 'repeated500_candidate_clusters.csv')
    arms = ['zero_shot', 'static_rag', 'dynamic_retrieval_only', 'full_dbcurator']
    assert len(clusters) == 500
    assert counts == [sum(int(r[arm + '_confirmed_count']) for r in clusters) for arm in arms]
    for topic, row in zip(TOPICS, rep):
        group = [r for r in clusters if r['topic'] == topic]
        assert len(group) == 100
        for key, arm in zip(('zero', 'static', 'adaptive', 'full'), arms):
            expected = sum(int(r[arm + '_confirmed_count']) for r in group) / 3
            assert abs(float(row[key]) - expected) < .051, (topic, arm)
    overall = [v / 15 for v in counts]
    swap = read(STORY / 'model_swap.csv')
    component_table = read(TABLE1 / 'component_statistics.csv')
    model_table = read(TABLE1 / 'model_statistics.csv')
    for topic, saved, row in zip(TOPICS, component_table, rep):
        group = [r for r in clusters if r['topic'] == topic]
        for key, arm in zip(('zero', 'static', 'adaptive', 'full'), arms):
            totals = [sum(r[f'repeat{repeat}_{arm}_claim'] == 'Confirmed' for r in group)
                      for repeat in (2, 3, 4)]
            assert f'{np.mean(totals):.1f}' == f'{float(saved[key]):.1f}'
            assert f'{np.std(totals, ddof=1):.1f}' == f'{float(saved[key + "_sd"]):.1f}'
        for key in ('min', 'max', 'agreement'):
            assert float(saved[key]) == float(row[key])
    for saved, row in zip(model_table, swap):
        assert (saved['topic'], saved['critic']) == (row['topic'], row['critic'])
        for key in ('adaptive', 'full', 'change_pp'):
            assert abs(float(saved[key]) - float(row[key])) < .051

    c = Canvas(198)
    bg = c.ax(0, 0, W, c.h)
    bg.set(xlim=(0, W), ylim=(c.h, 0))
    bg.axis('off')
    bg.set_gid('figure4_numeric_tables')

    def rule(x0, x1, y, heavy=False):
        bg.plot([x0, x1], [y, y], color=AXIS if heavy else GRID,
                lw=.55 if heavy else .35)

    def cell(x, y, value, width=20, fill=None, bold=False, bar=None):
        if fill is not None:
            bg.add_patch(Rectangle((x-width/2, y-2.6), width, 5.2,
                                   facecolor=tint(fill, .07), edgecolor='none'))
            if bar is not None:
                bg.add_patch(Rectangle((x-width/2, y+1.6), width*bar/100, .8,
                                       facecolor=tint(fill, .55), edgecolor='none'))
        c.text(x, y, value, ha='center', va='center', fontsize=7.1,
               fontweight='bold' if bold else 'normal', color=INK)

    # Numeric cells replace duplicate plots and tables, retaining all reported spread.
    c.panel(2, 5, 'a', 'Evidence-acquisition stages and repeat stability')
    centers = [45, 69, 93, 117, 143, 168]
    headers = ['Zero-shot', 'Frozen\nretrieval', 'Adaptive\nsearch', 'Full',
               'Full range\n(%)', 'Same label\n(%)']
    c.text(4, 17, 'Topic', fontsize=7, fontweight='bold')
    for x, header in zip(centers, headers):
        c.text(x, 17, header, ha='center', va='bottom', fontsize=7, fontweight='bold')
    rule(2, 178, 20, True)
    for i, row in enumerate(component_table):
        y = 26 + i*7
        bg.plot(3.5, y, 'o', ms=3.6, color=TOPIC[i], mec='none')
        c.text(7, y, NAMES[i], va='center', fontsize=7.1)
        for x, key in zip(centers, ('zero', 'static', 'adaptive', 'full')):
            value, sd = float(row[key]), float(row[key+'_sd'])
            cell(x, y, f'{value:.1f} ± {sd:.1f}', fill=TOPIC[i], bar=value,
                 bold=key == 'full')
        cell(143, y, f'{float(row["min"]):.0f}–{float(row["max"]):.0f}')
        cell(168, y, f'{float(row["agreement"]):.1f}')
    rule(2, 178, 58)
    c.text(7, 63, 'All topics', va='center', fontsize=7.1, fontweight='bold')
    for x, value in zip(centers, overall):
        cell(x, 63, f'{value:.1f}', bold=True)
    rule(2, 178, 67, True)

    c.panel(2, 76, 'b', 'Gains between stages')
    c.panel(63, 76, 'c', 'Critique-model comparison')
    contrasts = [('Static-Zero', 'Frozen −\nzero-shot'),
                 ('Dynamic-Static', 'Adaptive −\nfrozen'),
                 ('Full-Dynamic', 'Full −\nadaptive')]
    forest = {}
    f = rows(c.ax(20, 91, 34, 43), [label for _, label in contrasts], (-.6, 13.5),
             (0, 5, 10), 'Confirmed increase\n(percentage points)', pad=.6)
    f.set_gid('overall_stage_contrasts')
    f.axvline(0, color=AXIS, lw=.5, zorder=1)
    for i, (key, _) in enumerate(contrasts):
        r = next(r for r in paired if r['topic'] == 'all' and r['contrast'] == key)
        m, lo, hi = (float(r[k]) for k in ('difference_pp', 'ci95_low_pp', 'ci95_high_pp'))
        f.barh(i, m, .38, color=tint(SYSTEM, .35), lw=0, zorder=2)
        f.plot(m, i, 'o', ms=4.6, mfc=SYSTEM, mec='white', mew=.5, zorder=3)
        f.annotate(f'+{m:.1f}', (m, i), xytext=(0, 8), textcoords='offset points',
                   ha='center', fontsize=7, fontweight='bold', color=SYSTEM)
        forest[(key, 'all')] = (m, lo, hi)
    for x, header, align in [(64, 'Topic', 'left'), (87, 'Critique', 'left'),
                             (118, 'Adaptive', 'center'), (143, 'Full', 'center'),
                             (168, 'Change\n(pp)', 'center')]:
        c.text(x, 85, header, ha=align, va='bottom', fontsize=7, fontweight='bold')
    rule(63, 178, 87, True)
    for i in range(5):
        y = 92 + 11*i
        bg.add_patch(Rectangle((63, y-3), 115, 10.2,
                               facecolor=tint(TOPIC[i], .055), edgecolor='none'))
        name = {'Blood exposome': 'Blood\nexposome', 'Microbial NP': 'Microbial\nNP'}.get(NAMES[i], NAMES[i])
        c.text(65, y+2.5, name, va='center', fontsize=6.9)
        for j in range(2):
            row = model_table[2*i+j]
            yy = y+5*j
            c.text(87, yy, 'GPT' if j == 0 else 'Gemini', va='center', fontsize=7)
            for x, key in [(118, 'adaptive'), (143, 'full')]:
                cell(x, yy, f'{float(row[key]):.1f} ± {float(row[key+"_sd"]):.1f}')
            cell(168, yy, f'{float(row["change_pp"]):+.1f}')
        rule(63, 178, y+8)

    # One shared row per arm carries every resource field from the former Table 1c.
    c.panel(2, 156, 'd', 'Feedback mechanisms and research activity')
    feedback = feedback_summary()
    xs = [63, 88, 115, 143, 168]
    c.text(4, 166, 'Critique feedback', fontsize=7, fontweight='bold')
    for x, header in zip(xs, ['Confirmed\n(%)', 'Rounds', 'Tokens', 'Cost (US$)', 'New files']):
        c.text(x, 166, header, ha='center', va='bottom', fontsize=7, fontweight='bold')
    rule(2, 178, 169, True)
    labels = ['A  Criterion-directed', 'B  General review', 'C  No explicit rubric']
    for i, (record, color) in enumerate(zip(feedback, [FULL, ADAPT, FROZEN])):
        y = 175 + i*8
        c.text(4, y, labels[i], va='center', fontsize=7.1)
        cell(63, y, f'{record["confirmed"]:.1f}', fill=color, bar=record['confirmed'], bold=True)
        for x, key, fmt in [(88, 'mean_rounds', '.2f'), (115, 'mean_tokens', ',.0f'),
                            (143, 'mean_accounted_usd', '.4f'), (168, 'mean_source_files', '.1f')]:
            cell(x, y, format(record[key], fmt))
    rule(2, 178, 195, True)
    VALUES['Figure4'] = {'counts': counts, 'overall_per_100': overall, 'repeats': rep,
                         'forest': {f'{k}|{t}': v for (k, t), v in forest.items()},
                         'feedback_all100': feedback, 'model_swap': swap,
                         'component_table': component_table, 'model_table': model_table,
                         'merged_table1': True}
    # Compress vertical whitespace, not type size, to keep the caption on this page.
    c.fig.set_size_inches(W / 25.4, 180 / 25.4)
    c.h = 180
    save(c, 'Figure4')


def supplementary_robustness():
    rep = read(STORY / 'repeats.csv')
    swap = read(STORY / 'model_swap.csv')
    costs = {r['condition']: r for r in read(STORY / 'costs.csv')}
    keys = ['Zero-shot', 'Static RAG', 'Adaptive search', 'Full DB-Curator']
    overall = [int(costs[k]['confirmed'].split('/')[0]) / 15 for k in keys]
    c = Canvas(148)
    c.panel(2, 6, 'a', 'Repeat consistency')
    c.panel(94, 6, 'b', 'Critique configurations')
    c.panel(2, 82, 'c', 'Yield and computation')
    cc = rows(c.ax(28, 20, 42, 43), NAMES, (0, 80), (0, 40, 80), 'Full Confirmed per 100', pad=.6)
    side(cc, 1.1, -1.05, 'Same label', color=INK, fontsize=6.3)
    for i, r in enumerate(rep):
        lo, hi, m = float(r['min']), float(r['max']), float(r['full'])
        cc.plot([lo, hi], [i, i], color=tint(TOPIC[i], .4), lw=3.2, solid_capstyle='round', zorder=2)
        cc.plot(m, i, 'o', ms=4.2, mfc=TOPIC[i], mec='white', mew=.6, zorder=4)
        side(cc, 1.1, i, f"{float(r['agreement']):.1f}%")
    gains = [float(r['change_pp']) for r in swap]
    gain_limits = (min(-.35, min(gains)-.35), max(4.35, max(gains)+.35))
    d = rows(c.ax(120, 20, 52, 43), NAMES, gain_limits, (0, 2, 4), 'Adaptive to Full (percentage points)', pad=.6)
    for i in range(5):
        g0, g1 = float(swap[2 * i]['change_pp']), float(swap[2 * i + 1]['change_pp'])
        assert swap[2 * i]['critic'] == 'GPT-5-mini'
        d.plot([g0, g1], [i, i], color=tint(TOPIC[i], .45), lw=1.4, zorder=2)
        d.plot(g1, i, 's', ms=4, mfc='white', mec=TOPIC[i], mew=.9, zorder=3)
        d.plot(g0, i, 'o', ms=4.4, mfc=TOPIC[i], mec='white', mew=.6, zorder=4)
    d.legend(handles=[Line2D([], [], ls='', marker='o', ms=4, mfc=GREY, mec='white', label='GPT-5-mini Critique'),
                      Line2D([], [], ls='', marker='s', ms=3.8, mfc='white', mec=GREY, label='Gemini 2.5 Flash Critique')],
             loc='upper left', bbox_to_anchor=(-.02, 1.26), ncol=2, fontsize=6.2, handletextpad=.3, columnspacing=.8)
    e = c.ax(28, 91, 144, 42)
    e.set_xscale('log')
    e.set(xlim=(250, 1.5e6), ylim=(0, 60), xticks=[1e3, 1e4, 1e5, 1e6], yticks=[0, 20, 40, 60],
          xlabel='Mean recorded tokens\nper candidate', ylabel='Confirmed (%)')
    e.set_xticklabels(['$10^3$', '$10^4$', '$10^5$', '$10^6$'])
    e.minorticks_off()
    e.grid(axis='y', color=GRID, lw=.5)
    e.set_axisbelow(True)
    pts = []
    for key, i, label, dxy, ha, va in [('Zero-shot', 0, 'Zero-shot', (0, -8), 'left', 'top'),
                                       ('Static RAG', 1, 'Frozen retrieval', (0, 18), 'center', 'bottom'),
                                       ('Full DB-Curator', 3, 'Full', (-4, -9), 'right', 'top')]:
        r = costs[key]
        x, y = int(r['mean_tokens']), overall[i]
        txt = f"{label}\n{x:,} tokens"
        e.annotate(txt, (x, y), xytext=dxy, textcoords='offset points', ha=ha, va=va,
                   fontsize=6.3, color=INK, linespacing=1.2)
        pts.append((x, y, STAGE[i]))
    e.plot([p[0] for p in pts], [p[1] for p in pts], color=GRID, lw=.8, zorder=1)
    for x, y, col in pts:
        e.scatter(x, y, s=28, color=col, edgecolor='white', lw=.6, zorder=3)
    VALUES['SupplementaryFigure3'] = {'repeats': rep, 'model_swap': swap, 'costs': costs,
                                      'overall_per_100': overall}
    save(c, 'SupplementaryFigure3')


def supplementary_cost():
    costs = {r['condition']: r for r in read(STORY / 'costs.csv')}
    c = Canvas(81)
    ax = c.ax(17, 8, 145, 54)
    ax.set_xscale('log')
    ax.set(xlim=(250, 1.5e6), ylim=(0, 60), xticks=[1e3, 1e4, 1e5, 1e6],
           yticks=[0, 20, 40, 60], xlabel='Mean recorded tokens per candidate', ylabel='Confirmed (%)')
    ax.minorticks_off()
    ax.set_axisbelow(True)
    ax.grid(axis='y', color=GRID, lw=.5)
    points = []
    for key, color, offset, ha in [('Zero-shot', ZERO, (0, -10), 'left'),
                                   ('Static RAG', FROZEN, (0, 14), 'center'),
                                   ('Full DB-Curator', FULL, (-4, -10), 'right')]:
        r = costs[key]
        x, y = int(r['mean_tokens']), int(r['confirmed'].split('/')[0])/15
        label = {'Static RAG': 'Frozen retrieval', 'Full DB-Curator': 'Full'}.get(key, key)
        ax.annotate(f'{label}\n{x:,} tokens', (x, y), xytext=offset, textcoords='offset points',
                    ha=ha, va='bottom' if offset[1] > 0 else 'top', fontsize=7)
        points.append((x, y))
        ax.scatter(x, y, s=38, color=color, edgecolor='white', lw=.6, zorder=3)
    ax.plot(*zip(*points), color=GRID, lw=.8, zorder=1)
    VALUES['SupplementaryCost'] = costs
    save(c, 'SupplementaryCost')


def supplementary_profiles():
    data = read(DATA / 'criterion_full_profiles.csv')
    c = Canvas(184)
    ax = c.ax(76, 10, 70, 158)
    total_height = len(data) + 5 * 1.5
    ax.set(xlim=(-2, 102), ylim=(total_height-.2, -.8), xticks=[0, 25, 50, 75, 100],
           yticks=[], xlabel='Recorded criterion indicator (%)')
    ax.spines['left'].set_visible(False)
    ax.grid(axis='x', color=GRID, lw=.5)
    ax.set_axisbelow(True)
    side(ax, 1.08, -1, 'Difference', color=INK, fontsize=6.3)
    h = 0
    for j, topic in enumerate(TOPICS):
        subset = sorted([r for r in data if r['topic'] == topic], key=lambda r: -float(r['delta']))
        ax.text(-112, h, LONG[j], va='center', fontsize=7, weight='bold', clip_on=False)
        side(ax, 1.08, h, f"{int(float(subset[0]['rows_confirmed']))} / {int(float(subset[0]['rows_other']))}",
             color=INK, fontsize=6.3)
        for k, r in enumerate(subset):
            y = h + 1 + k
            label = r['criterion_label'].replace('--', '-').replace('Eligible drug modality (ANY)', 'Drug modality (ANY)')
            ax.text(-10, y, label, ha='right', va='center', fontsize=6.3, clip_on=False)
            role = r['gate_type']
            color = SYSTEM if role == 'M' else ROSE if role == 'X' else GREY
            ax.text(-5, y, role, ha='center', va='center', fontsize=5.6, color=color, weight='bold',
                    bbox={'boxstyle': 'round,pad=.22', 'fc': tint(color, .14), 'ec': 'none'}, clip_on=False)
            co, ot = 100*float(r['pass_rate_confirmed']), 100*float(r['pass_rate_other'])
            ax.plot([ot, co], [y, y], color=tint(TOPIC[j], .4), lw=1.3)
            ax.plot(ot, y, 'D', ms=3.8, mfc='white', mec=ROSE, mew=.9)
            ax.plot(co, y, 'o', ms=4.2, mfc=SYSTEM, mec='white', mew=.5)
            side(ax, 1.08, y, f'{co-ot:+.1f} pp', fontsize=6.3)
        h += len(subset) + 1.5
        if j < 4:
            ax.plot([-112, 145], [h-.65]*2, color=GRID, lw=.5, clip_on=False)
    c.legend(181, [Line2D([], [], ls='', marker='o', ms=4.2, mfc=SYSTEM, mec='white', label='Confirmed rows'),
                   Line2D([], [], ls='', marker='D', ms=3.8, mfc='white', mec=ROSE, label='Other outcomes'),
                   Line2D([], [], ls='', label='M mandatory  ·  X exclusion  ·  O optional')], ncol=3)
    VALUES['SupplementaryProfiles'] = data
    save(c, 'SupplementaryProfiles')


# ================================================================ Figure 5
# Final-label categories in the order and colours of Figure 3a (distribution-table names -> display names)
OUTCOME_STACK = [('Confirmed', SYSTEM), ('Suspected', tint(SYSTEM, .45)), ('Insufficient evidence', '#D9DDE1'),
                 ('Explicit negative', ROSE), ('Other scope / identity', tint(ROSE, .35))]
OUTCOME_NAMES = {'Confirmed': 'Confirmed', 'Suspected': 'Suspected',
                 'Insufficient evidence': 'Insufficient Direct Evidence',
                 'Explicit negative': 'Explicit Negative Evidence',
                 'Other scope / identity': 'Out of scope or class-level only'}


def criterion_distribution():
    raw = read(DATA / 'criterion_count_rows.csv')
    dist = read(DATA / 'criterion_count_distribution.csv')
    assert len(raw) == len({(r['topic'], r['row_index']) for r in raw}) == 1887
    counts = Counter((r['topic'], int(r['criteria_passed']), r['outcome']) for r in raw)
    totals = Counter(r['topic'] for r in raw)
    assert sum(r['outcome'] == 'Confirmed' for r in raw) == 975
    for r in raw:
        assert 0 <= int(r['criteria_passed']) <= int(r['criteria_total'])
    for r in dist:
        n = counts[(r['topic'], int(r['criteria_passed']), r['outcome'])]
        assert n == int(r['row_count'])
        assert abs(float(r['topic_fraction_percent']) - 100*n/totals[r['topic']]) < 1e-9
    assert sum(int(r['row_count']) for r in dist) == len(raw)
    return raw, dist


def figure5():
    data = read(DATA / 'criterion_indicators.csv')
    short_names = {'Disinfectant--precursor reaction': 'Disinfectant-precursor link',
                   'External-environment relation': 'External-environment link',
                   'Pharmacologically relevant effect': 'Pharmacological effect',
                   'Blood or systemic circulation': 'Blood / systemic circulation'}
    raw, dist = criterion_distribution()
    c = Canvas(190)
    c.panel(2, 6, 'a', 'Criterion-specific separation')
    c.panel(130, 6, 'b', 'Indicators per row')
    ax = c.ax(49, 15, 54, 150)
    ax.set(xlim=(-2, 102), ylim=(27.4, -.9), xticks=[0, 25, 50, 75, 100], yticks=[],
           xlabel='Recorded criterion indicator (%)')
    ax.spines['left'].set_visible(False)
    ax.grid(axis='x', color=GRID, lw=.5)
    ax.set_axisbelow(True)
    side(ax, 1.06, -1.0, 'Difference', fontsize=6.4, color=INK)
    vals = []
    for j, t in enumerate(TOPICS):
        subset = [r for r in data if r['topic'] == t]
        assert len(subset) == 4
        h = j * 5.5
        ax.text(-92, h, LONG[j], va='center', fontsize=7.2, fontweight='bold', color=INK, clip_on=False)
        nco, notr = int(float(subset[0]['rows_confirmed'])), int(float(subset[0]['rows_other']))
        side(ax, 1.06, h, f'{nco} / {notr}', fontsize=6.1, color=INK)
        for k, r in enumerate(subset):
            name = short_names.get(r['criterion_label'], r['criterion_label'])
            y = h + k + 1.05
            co, ot = 100 * float(r['pass_rate_confirmed']), 100 * float(r['pass_rate_other'])
            ax.text(-10, y, name, ha='right', va='center', fontsize=6.5, clip_on=False)
            role = r['gate_type']
            rc = SYSTEM if role == 'M' else ROSE if role == 'X' else GREY
            ax.text(-5, y, role, ha='center', va='center', fontsize=6.0, color=rc, fontweight='bold',
                    bbox={'boxstyle': 'round,pad=.22', 'fc': tint(rc, .14), 'ec': 'none'}, clip_on=False)
            ax.plot([ot, co], [y, y], color=tint(TOPIC[j], .4), lw=1.3, zorder=2)
            ax.plot(ot, y, 'D', ms=3.8, mfc='white', mec=ROSE, mew=.9, zorder=3)
            ax.plot(co, y, 'o', ms=4.2, mfc=SYSTEM, mec='white', mew=.5, zorder=4)
            side(ax, 1.06, y, f'{co - ot:+.1f} pp', fontsize=6.5)
            vals.append({'topic': t, 'criterion': r['criterion'], 'role': role,
                         'confirmed_indicator': co, 'other_indicator': ot, 'difference_pp': co - ot})
        if j < 4:
            ax.plot([-92, 142], [h + 4.9, h + 4.9], color=GRID, lw=.5, clip_on=False, transform=ax.transData)
        top = 15 + (h + 1.0 + .9) / 28.3 * 150
        d = c.ax(133, top, 44, 18.8)
        subset_raw = [r for r in raw if r['topic'] == t]
        assert len(subset_raw) == nco + notr
        maximum = max(int(r['criteria_total']) for r in subset_raw)
        x = np.arange(maximum + 1)
        bottom = np.zeros(len(x))
        for outcome, color in OUTCOME_STACK:
            lookup = {int(r['criteria_passed']): float(r['topic_fraction_percent'])
                      for r in dist if r['topic'] == t and r['outcome'] == outcome}
            ys = [lookup.get(int(k), 0) for k in x]
            d.bar(x, ys, bottom=bottom, width=.76, color=tint(color, .65), edgecolor='white', linewidth=.2)
            bottom += ys
        assert abs(sum(bottom) - 100) < 1e-8
        d.set(xlim=(-.6, maximum+.6), ylim=(0, 100), xticks=x, yticks=[0, 50, 100])
        d.set_axisbelow(True)
        d.grid(axis='y', color=GRID, lw=.45)
        d.tick_params(labelsize=6.5)
        if j == 0:
            d.set_ylabel('Rows (%)', fontsize=6.3)
        if j == 4:
            d.set_xlabel('Recorded criterion indicators', fontsize=6.3)
    c.legend(175, [Line2D([], [], ls='', marker='o', ms=4.2, mfc=SYSTEM, mec='white', label='Confirmed rows'),
                   Line2D([], [], ls='', marker='D', ms=3.8, mfc='white', mec=ROSE, label='Other outcomes'),
                   Line2D([], [], ls='', marker='', label='M mandatory  ·  X exclusion  ·  O optional')],
             x=.5, ncol=3)
    c.legend(184, [Patch(fc=tint(color, .65), label=OUTCOME_NAMES[outcome]) for outcome, color in OUTCOME_STACK],
             ncol=5, handlelength=1.1, handleheight=.8)
    VALUES['Figure5'] = vals
    VALUES['Figure5_distribution'] = dist
    save(c, 'Figure5')


# ================================================================ Figure 6
def case_specs():
    cases = {r['candidate']: r for r in json.loads(CASES.read_text())}

    def anchors(name, stage):
        return [a for ins in cases[name]['inspections'] for a in ins['source_anchors'] if a['stage'] == stage]
    hb = next(k for k in cases if 'Hydroxybenzene' in k)
    iso = 'Isoterrelumamide A'
    pc = next(k for k in cases if k.startswith('PC('))
    entries = [
        (hb, '4-Hydroxyphthalic acid', 'Disinfection by-products', 'Organic precursor',
         'Chlorination formation is shown. Find the link to an organic precursor.',
         'Same source: precursor link made explicit', SYSTEM),
        (iso, iso, 'Microbial natural products', 'Secondary-metabolite status',
         'Fungal isolation and structure are shown. Find secondary-metabolite evidence.',
         'Added source: classification made explicit', SYSTEM),
        (pc, 'PC(20:2(11Z,14Z)/20:1(11Z))', 'Endogenous metabolites', 'Exact molecular species',
         'Target: PC(20:2/20:1). Cited: PC(20:3/20:1). Find the exact lipid species.',
         'Class-level synthesis: target still unresolved', ROSE)]
    spec = []
    for key, title, domain, criterion, request, outcome, color in entries:
        assert cases[key]['canonical_final_label'] == 'Confirmed' and cases[key]['canonical_accepted']
        a0, a1 = anchors(key, 'initial_report')[0], anchors(key, 'response')[1]
        assert a0['location_status'] == a1['location_status'] == 'exact'
        context = anchors(key, 'initial_report')[1] if key == iso else None
        spec.append(dict(candidate=key, title=title, domain=domain, criterion=criterion,
                         quote0=a0['quote'], quote1=a1['quote'],
                         context_quote0=context['quote'] if context else '',
                         source_anchors=[a0, a1] + ([context] if context else []),
                         identifier0=a0['supplied_identifier'], identifier1=a1['supplied_identifier'],
                         request=request, outcome=outcome, color=color,
                         critique_label=cases[key]['critique_label'], final_label='Confirmed'))
    return spec


def highlighted_text(ax, x, top, width, text, highlights, size=6.6, italic=False, draw=True):
    """Wrap measured text runs, preserving wording while emphasizing exact substrings."""
    spans = []
    for phrase, color in highlights:
        start = text.find(phrase)
        assert start >= 0, phrase
        spans.append((start, start + len(phrase), color))
    renderer = ax.figure.canvas.get_renderer()
    px = abs(ax.transData.transform((1, 0))[0] - ax.transData.transform((0, 0))[0])
    py = abs(ax.transData.transform((0, 1))[1] - ax.transData.transform((0, 0))[1])
    props = {bold: FontProperties(family='sans-serif', size=size,
                                 weight='bold' if bold else 'normal', style='italic' if italic else 'normal')
             for bold in (False, True)}

    def measure(string, bold):
        return renderer.get_text_width_height_descent(string, props[bold], ismath=False)[0] / px

    lines, line, used = [], [], 0
    for match in re.finditer(r'\S+\s*', text):
        word = match.group()
        color = next((color for lo, hi, color in spans if match.start() < hi and match.end() > lo), None)
        bold = color is not None
        length = measure(word, bold)
        assert measure(word.rstrip(), bold) <= width, word
        if line and used + measure(word.rstrip(), bold) > width:
            lines.append(line)
            line, used = [], 0
        line.append((word, bold, color or INK))
        used += length
    if line:
        lines.append(line)
    spacing = size * ax.figure.dpi / 72 * 1.24 / py
    for row, words in enumerate(lines):
        cursor = x
        runs = []
        for word, bold, color in words:
            if runs and runs[-1][1:] == (bold, color):
                runs[-1] = (runs[-1][0] + word, bold, color)
            else:
                runs.append((word, bold, color))
        for string, bold, color in runs:
            if draw:
                direction = 1 if ax.yaxis_inverted() else -1
                ax.text(cursor, top + direction * row * spacing, string, fontproperties=props[bold],
                        va='top', color=color)
            cursor += measure(string, bold)
    assert ''.join(word for line in lines for word, _, _ in line) == text
    return len(lines)


def figure6_full_quotes_archive():
    spec = case_specs()
    size, column_width = 7.3, 85
    line_mm = size * 25.4 / 72 * 1.24
    probe = Canvas(100)
    probe_ax = probe.ax(0, 0, W, 100)
    probe_ax.set(xlim=(0, W), ylim=(0, 100))
    for i, r in enumerate(spec):
        highlights = [
            {'quote0': [('chlorination', SYSTEM), ('4-hydroxyphthalic acid', INK)],
             'request': [('organic precursor', SYSTEM)],
             'quote1': [('intermediates between NOM', SYSTEM)]},
            {'quote0': [('isoterrelumamide A (2)', INK), ('NMR', INK), ('HRESIMS', INK)],
             'request': [('secondary-metabolite', SYSTEM)],
             'quote1': [('Isoterrelumamide A (67)', SYSTEM), ('secondary metabolites', SYSTEM)]},
            {'quote0': [('PC (20:3(8Z,11Z,14Z)/20:1(11Z))', ROSE)],
             'request': [('PC(20:2/20:1)', SYSTEM), ('PC(20:3/20:1)', ROSE)],
             'quote1': [('phosphatidylcholine (PC) biosynthesis', ROSE)]},
        ][i]
        r['highlighted_phrases'] = highlights
        r['display_quote0'] = ('“' + r['context_quote0'] + '” ' if r['context_quote0'] else '') + '“' + r['quote0'] + '”'
        r['display_quote1'] = '“' + r['quote1'] + '”'
        counts = [highlighted_text(probe_ax, 0, 90, column_width - 6, r['display_' + field],
                                   highlights[field], size=size, draw=False)
                  for field in ('quote0', 'quote1')]
        r['quote_line_counts'] = counts
        r['card_height_mm'] = max(counts) * line_mm + 8
        r['row_height_mm'] = r['card_height_mm'] + 29
    plt.close(probe.fig)
    c = Canvas(sum(r['row_height_mm'] for r in spec) + 2)
    y = 2
    for i, r in enumerate(spec):
        highlights = r['highlighted_phrases']
        c.panel(2, y + 2, chr(97 + i), r['title'])
        c.text(178, y + 2, r['domain'], ha='right', fontsize=6.7, color=GREY)
        c.text(2, y + 6.5, 'Criterion: ' + r['criterion'], fontsize=6.8, color=INK)
        review_label = 'Insufficient Direct Evidence' if r['critique_label'] == 'Insufficient Direct Evidence' else r['critique_label']
        c.text(178, y + 6.5, f"Critique: {review_label}  ·  Final: Confirmed", fontsize=6.5, ha='right', color=GREY)
        request_ax = c.ax(2, y + 9, 176, 6)
        request_ax.set(xlim=(0, 176), ylim=(0, 6))
        request_ax.axis('off')
        request_ax.add_patch(Rectangle((0, 0), 176, 6, fc=tint(AMBER, .10), ec='none'))
        request_ax.text(2, 3, 'Critique request', va='center', fontsize=6.9, fontweight='bold', color=INK)
        highlighted_text(request_ax, 24, 4.25, 149, r['request'], highlights['request'], size=7.0)
        c.text(4, y + 19, 'Initial cited evidence', fontsize=7.1, fontweight='bold')
        c.text(95, y + 19, 'Revised cited evidence', fontsize=7.1, fontweight='bold')
        h = r['card_height_mm']
        ax = c.ax(2, y + 21, 176, h)
        ax.set(xlim=(0, 176), ylim=(0, h))
        ax.axis('off')
        for j, (x, col, field) in enumerate([(0, SYSTEM, 'quote0'), (91, r['color'], 'quote1')]):
            ax.add_patch(FancyBboxPatch((x, 0), column_width, h, boxstyle='round,pad=0,rounding_size=1.0',
                                        fc=tint(col, .035), ec='none'))
            ax.add_patch(Rectangle((x, 0), .7, h, fc=col, ec='none'))
            highlighted_text(ax, x + 3, h - 2.3, column_width - 6, r['display_' + field],
                             highlights[field], size=size)
            anchor = r['source_anchors'][j]
            kind = 'Abstract' if anchor['full_text_equals_abstract'] else 'Full text'
            ident = r['identifier' + str(j)]
            ax.text(x + 3, 2.1, kind + '  |  DOI: ' + ident, fontsize=6.1, color=GREY)
        ax.add_patch(FancyArrowPatch((86, h / 2), (90, h / 2), arrowstyle='-|>',
                                    mutation_scale=6, color=GREY, lw=.7))
        c.text(4, y + 21 + h + 4.0, r['outcome'], fontsize=7.0, color=r['color'], fontweight='bold')
        y += r['row_height_mm']
    VALUES['Figure6'] = spec
    evidence_rows = []
    for r in spec:
        for anchor in r['source_anchors']:
            evidence_rows.append({'candidate': r['candidate'], **anchor})
    (OUT / 'Figure6_evidence_full.json').write_text(json.dumps(evidence_rows, indent=2, ensure_ascii=False) + '\n')
    with (OUT / 'Figure6_evidence_full.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        fields = ['candidate', 'stage', 'evidence_id', 'quote_number', 'quote', 'supplied_title',
                  'supplied_identifier', 'source_locator', 'source_sha256', 'offset',
                  'text_field', 'full_text_equals_abstract']
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(evidence_rows)
    save(c, 'Figure6')


def criterion_case_specs():
    """Verbatim follow-up sentences with source-linked criterion assessments."""
    specs = case_specs()
    sentences = {row['candidate']: row for row in json.loads(CASE_SENTENCES.read_text())}
    layouts = [
        dict(initial_summary='Initial evidence names the compound among products formed during chlorination. [a1]',
             criteria=[('Formed during\ndisinfection', True, True,
                        'Chlorination formation already documented. [a1]'),
                       ('Formed from\norganic precursors', False, True, '')],
             request='Link formation to an organic precursor.',
             source_labels=['a1'], source_ids=[specs[0]['identifier0']],
             source_mode='Same-source context', color=SYSTEM),
        dict(initial_summary='Initial evidence establishes fungal isolation and molecular structure. [b1]',
             criteria=[('Fungal origin', True, True, 'Isolated from Aspergillus carneus. [b1]'),
                       ('Named compound\nand structure', True, True, 'Structure established by NMR and HRESIMS. [b1]'),
                       ('Secondary-metabolite\nclassification', False, True, '')],
             request='Establish secondary-metabolite status.',
             source_labels=['b1', 'b2'], source_ids=[specs[1]['identifier0'], specs[1]['identifier1']],
             source_mode='Additional-source context', color=SYSTEM),
        dict(initial_summary='Initial evidence names PC(20:3/20:1), a different lipid from the target. [c1]',
             criteria=[('Human-sample context\nfor related PCs', True, True, 'Related PCs measured in human samples. [c1]'),
                       ('Exact target species\nPC(20:2/20:1)', False, False, '')],
             request='Find evidence for the exact target lipid.',
             source_labels=['c1', 'c2'], source_ids=[specs[2]['identifier0'], specs[2]['identifier1']],
             source_mode='Exact identity remains unresolved', color=ROSE),
    ]
    for record, layout in zip(specs, layouts):
        record.update(layout)
        # Keep established context in source data, but plot only the reviewed gap.
        record['context_criteria'] = record['criteria'][:-1]
        record['criteria'] = record['criteria'][-1:]
        source = sentences[record['candidate']]
        sentence = source['sentence']
        assert sentence in source['source_context']
        assert source['doi'] == record['identifier1']
        record['evidence_sentence'] = sentence
        record['evidence_summary'] = '“' + sentence + '” [' + source['source_key'] + ']'
        record['evidence_highlights'] = [(phrase, record['color']) for phrase in source['highlight_phrases']]
        record['verbatim_source'] = source
        record['state_basis'] = 'Source-linked inspection of the displayed evidence, not a new model or expert judgment.'
    return specs


def figure6():
    """Criterion -> initial support -> focused review/evidence -> later support."""
    spec = criterion_case_specs()
    size, evidence_x, evidence_width = 7.1, 72, 82
    line_mm = size * 25.4 / 72 * 1.24
    probe = Canvas(100)
    probe_ax = probe.ax(0, 0, W, 100)
    probe_ax.set(xlim=(0, W), ylim=(100, 0))
    for r in spec:
        lines = highlighted_text(probe_ax, evidence_x, 20, evidence_width,
                                 r['evidence_summary'], r['evidence_highlights'], size=size, draw=False)
        r['evidence_line_count'] = lines
        r['evidence_band_height_mm'] = max(18, 6.5 + lines * line_mm + 2)
        r['case_height_mm'] = 21 + r['evidence_band_height_mm'] + 6.5
    plt.close(probe.fig)
    c = Canvas(3 + sum(r['case_height_mm'] + 3 for r in spec) + 7)
    ax = c.ax(0, 0, W, c.h)
    ax.set(xlim=(0, W), ylim=(c.h, 0)); ax.axis('off')
    support = SYSTEM

    def status(x, y, supported, accent):
        if supported:
            ax.add_patch(plt.Circle((x, y), 2.0, fc=tint(support, .12), ec='none'))
            ax.plot([x-.9, x-.15, x+1.05], [y+.05, y+.85, y-1], color=support,
                    lw=1.25, solid_capstyle='round', solid_joinstyle='round')
        else:
            ax.add_patch(plt.Circle((x, y), 1.45, fc='white', ec=accent, lw=1.15))

    def arrow(x1, x2, y, color):
        ax.add_patch(FancyArrowPatch((x1,y),(x2,y),arrowstyle='-|>',
            mutation_scale=6.5,color=color,lw=.8,shrinkA=0,shrinkB=0))

    y = 3
    for i, r in enumerate(spec):
        height = r['case_height_mm']
        col = r['color']
        c.panel(3, y+3, chr(97+i), r['title'])
        c.text(177,y+3,r['domain'],ha='right',fontsize=6.8,color=INK)
        c.text(7,y+9,r['initial_summary'],fontsize=7.0)
        for x, text, ha in [(7,'Criterion','left'),(58,'Initial','center'),
                             (evidence_x,'Critique and evidence','left'),(168,'After review','center')]:
            ax.text(x,y+16,text,ha=ha,va='center',fontsize=6.8,color=INK)
        ax.plot([7,177],[y+19]*2,color=GRID,lw=.6)
        (criterion, before, after, _), = r['criteria']
        band_top = y + 21
        band_height = r['evidence_band_height_mm']
        cy = band_top + band_height/2
        ax.add_patch(FancyBboxPatch((4,band_top),173,band_height,
            boxstyle='round,pad=0,rounding_size=1.2',fc=tint(col,.07),ec='none',zorder=0))
        ax.add_patch(Rectangle((4,band_top),.7,band_height,fc=col,ec='none'))
        ax.text(7,cy,criterion,fontsize=7.2,va='center',color=col,
                fontweight='bold',linespacing=1.25)
        status(58,cy,before,col)
        status(168,cy,after,col)
        arrow(62,69,cy,col); arrow(156,163,cy,col)
        ax.text(evidence_x,band_top+2,r['request'],fontsize=6.7,color=col,
                va='top',fontweight='bold')
        lines = highlighted_text(ax, evidence_x, band_top+6.5, evidence_width,
                                 r['evidence_summary'], r['evidence_highlights'], size=size)
        assert lines == r['evidence_line_count']
        sources='   '.join(f'[{key}] {doi}' for key,doi in zip(r['source_labels'],r['source_ids']))
        c.text(7,y+height-3,sources,fontsize=6.1,color=INK)
        if i<2:ax.plot([3,177],[y+height+1]*2,color=GRID,lw=.7)
        y += height+3
    legend_y = c.h-4
    status(7,legend_y,True,SYSTEM)
    ax.text(11,legend_y,'Explicit support in cited evidence',fontsize=6.9,va='center')
    status(91,legend_y,False,GREY)
    ax.text(95,legend_y,'Not established by cited evidence',fontsize=6.9,va='center')
    VALUES['Figure6'] = spec
    evidence_rows = [{'candidate':r['candidate'],**a} for r in spec for a in r['source_anchors']]
    (OUT/'Figure6_evidence_full.json').write_text(json.dumps(evidence_rows,indent=2,ensure_ascii=False)+'\n')
    with (OUT/'Figure6_evidence_full.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        fields=['candidate','stage','evidence_id','quote_number','quote','supplied_title',
                'supplied_identifier','source_locator','source_sha256','offset','text_field','full_text_equals_abstract']
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
        writer.writeheader(); writer.writerows(evidence_rows)
    (OUT/'Figure6_criterion_evidence_map.json').write_text(json.dumps(spec,indent=2,ensure_ascii=False)+'\n')
    save(c,'Figure6')


# ================================================================ Supplementary Figure 2
def draw_accumulation(c, rectangle, legend_y, compact=False):
    data = read(DATA / 'construction_accumulation.csv')
    ax = c.ax(*rectangle)
    ends = []
    for t, name, col in zip(TOPICS, NAMES, TOPIC):
        rs = [r for r in data if r['topic'] == t]
        x = [0] + [int(r['processed_records']) for r in rs]
        y = [0] + [int(r['retained_rows']) for r in rs]
        assert y[-1] == 200 and all(a <= b for a, b in zip(y, y[1:]))
        ax.step(x, y, where='post', lw=1.2, color=col)
        ax.plot(x[-1], 200, 'o', ms=3.8, mfc=col, mec='white', mew=.5, zorder=4)
        ends.append((x[-1], name, col))
    ax.set(xlim=(0, 740), ylim=(0, 224), xticks=range(0, 701, 100), yticks=[0, 50, 100, 150, 200],
           xlabel='Processed candidate records', ylabel='Final retained entries')
    ax.grid(axis='y', color=GRID, lw=.5)
    ax.set_axisbelow(True)
    ax.axhline(200, color=GREY, lw=.5, ls=(0, (3, 2)))
    if compact:
        ax.set_xticks([0,350,700])
        ax.set_yticks([0,100,200])
    place = {321: ((-5, 6), 'right'), 331: ((0, 19), 'center'), 360: ((2, 6), 'center'),
             403: ((5, 6), 'left'), 707: ((0, 6), 'center')}
    for xe, name, col in ([] if compact else ends):
        ax.annotate(f'{name}  {xe}', (xe, 200), xytext=place[xe][0], textcoords='offset points', ha=place[xe][1],
                    fontsize=5.8, color=INK,
                    arrowprops={'arrowstyle': '-', 'color': tint(col, .6), 'lw': .5, 'shrinkA': 0, 'shrinkB': 1})
    if legend_y is not None:
        c.legend(legend_y, [Line2D([], [], color=col, lw=1.2, label=n) for n, col in zip(NAMES, TOPIC)], ncol=5)
    VALUES['construction_accumulation'] = {t: [r for r in data if r['topic'] == t][-1] for t in TOPICS}
    return ax


def accumulation():
    c = Canvas(100)
    draw_accumulation(c, (16, 6, 140, 80), 95)
    VALUES['SupplementaryFigure2'] = VALUES['construction_accumulation']
    save(c, 'SupplementaryFigure2')


# ================================================================ main
def main():
    functions = dict(zip(['Figure2', 'Figure3', 'Figure4', 'Figure5', 'Figure6', 'SupplementaryFigure2',
                          'SupplementaryFigure3', 'SupplementaryCost', 'SupplementaryProfiles', 'SupplementaryOperational',
                          'SupplementaryRuntime'],
                         [figure2, figure3, figure4, figure5, figure6, accumulation, supplementary_robustness,
                          supplementary_cost, supplementary_profiles, supplementary_operational, supplementary_runtime]))
    parser = argparse.ArgumentParser()
    parser.add_argument('--figures', nargs='+', choices=list(functions), default=list(functions))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    style()
    inputs = [DATA / p for p in ['construction_final.csv', 'benchmark_final.csv', 'benchmark_labels.csv',
                                 'criterion_indicators.csv', 'repeated_contrasts.csv',
                                 'adjacent_stage_contrasts.csv', 'repeated500_candidate_clusters.csv',
                                 'construction_accumulation.csv', 'criterion_count_distribution.csv',
                                 'criterion_count_rows.csv', 'criterion_full_profiles.csv',
                                 'benchmark_operational_current.csv']]
    inputs += sorted(STORY.glob('*.csv')) + [CASES, CASE_SENTENCES, REVIEW, CONSTRUCTION_RECALL, BENCHMARK_REVIEW,
                FEEDBACK / 'feedback_operational_summary.csv', FEEDBACK / 'feedback_all100_operational.csv']
    inputs += [ROOT.parent / row['source_file'] for row in json.loads(CASE_SENTENCES.read_text())]
    inputs += sorted(TABLE1.glob('*.csv')) + [TABLE1 / 'table1_original.tex']
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    before = {str(p.relative_to(ROOT.parent)): sha(p) for p in inputs}
    # Figure 1 is imported workshop artwork in figures/workshop_style.
    if (OUT / 'PLOTTED_VALUES.json').exists():
        VALUES.update(json.loads((OUT / 'PLOTTED_VALUES.json').read_text()))
    if (ROOT / 'NATURE_FINAL_QA.json').exists():
        previous = json.loads((ROOT / 'NATURE_FINAL_QA.json').read_text())
        QA.extend(q for q in previous['figures'] if q['figure'] not in args.figures)
    for name in args.figures:
        functions[name]()
    QA.sort(key=lambda q: list(functions).index(q['figure']))
    assert before == {str(p.relative_to(ROOT.parent)): sha(p) for p in inputs}, 'source data changed'
    (OUT / 'PLOTTED_VALUES.json').write_text(json.dumps(VALUES, indent=2, default=str) + '\n')
    manifest = {'input_hashes': before, 'script_sha256': sha(Path(__file__)), 'figures': QA,
                'topic_palette': dict(zip(TOPICS, TOPIC)), 'stage_palette': STAGE,
                'new_model_calls': 0,
                'outputs': {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.suffix in ('.pdf', '.svg', '.png', '.tiff')}}
    (ROOT / 'NATURE_FINAL_QA.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for q in QA:
        print(q['figure'], q['size_mm'], 'overlaps:', len(q['text_overlaps']), 'outside:', q['out_of_bounds_text'],
              'small:', q['text_below_5pt'])
        for o in q['text_overlaps']:
            print('   overlap:', o)


if __name__ == '__main__':
    main()
