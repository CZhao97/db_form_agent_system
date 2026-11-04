"""Nature-style redraw of main Figures 1-5 from the existing frozen source tables.

Panel content matches the current captions; only layout, typography and colour change.
Outputs go to manuscript/figures/nature (PDF/SVG editable text, PNG preview, 600-dpi TIFF).
"""
import csv
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import patches as mp
from matplotlib.lines import Line2D
from matplotlib.text import Text

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'source_data'
STORY = DATA / 'story_panels'
OUT = ROOT.parent / 'figures/nature'
OUT.mkdir(exist_ok=True)

INK = '#1A1A1A'
GREY = '#6B6B6B'
AXIS = '#3A3A3A'
plt.rcParams.update({
    'font.family': 'sans-serif', 'font.sans-serif': ['Arial', 'Liberation Sans', 'DejaVu Sans'],
    'font.size': 6.5, 'axes.labelsize': 6.5, 'xtick.labelsize': 6, 'ytick.labelsize': 6.5,
    'axes.linewidth': .5, 'axes.spines.top': False, 'axes.spines.right': False,
    'axes.edgecolor': AXIS, 'axes.labelcolor': INK, 'text.color': INK,
    'xtick.color': AXIS, 'ytick.color': INK, 'xtick.major.width': .5, 'xtick.major.size': 2,
    'xtick.major.pad': 2, 'axes.labelpad': 2.5,
    'svg.fonttype': 'none', 'pdf.fonttype': 42, 'savefig.facecolor': 'white',
})

# Evidence depth: zero-shot -> frozen retrieval -> adaptive search -> full system.
ZERO, FROZEN, ADAPT, FULL = '#B4B4B4', '#AFCBE0', '#5D9AC6', '#1E5B88'
PALE = '#DCE6EE'
ROSE = '#C4675C'
CLAUDE, GPT, GEMINI = '#D08A2E', '#5B4E9C', '#2A9D8F'
GRID = '#E6E6E6'

TOPICS = ['dbp', 'blood_exposome', 'drug_compounds', 'human_endogenous_metabolites',
          'microbial_natural_products']
NAMES = ['DBPs', 'Blood', 'Drugs', 'Endogenous', 'Microbial NP']
W = 180
QA = []


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

    def panel(self, x, y, letter, title):
        self.text(x, y, letter, fontsize=8, fontweight='bold')
        self.text(x + 4, y, title, fontsize=7, fontweight='bold')


def rows_axis(ax, labels, xlim, ticks, xlabel, show_labels=True, ticklabels=None):
    n = len(labels)
    ax.set(xlim=xlim, ylim=(-.6, n - .4), yticks=np.arange(n)[::-1], xticks=ticks, xlabel=xlabel)
    ax.set_yticklabels(labels if show_labels else [])
    if ticklabels is not None:
        ax.set_xticklabels(ticklabels)
    ax.tick_params(axis='y', length=0, pad=3)
    ax.spines['left'].set_visible(False)
    ax.spines['bottom'].set_position(('outward', 2))
    return ax


def col(ax, x, y, s, color=INK, ha='left', **kw):
    """Text in a column beside the axes: x in axes fraction, y in data units."""
    return ax.text(x, y, s, transform=ax.get_yaxis_transform(), color=color, ha=ha,
                   va='center', fontsize=kw.pop('fontsize', 6), clip_on=False, **kw)


def lab(ax, x, y, s, color=INK, ha='left', **kw):
    return ax.text(x, y, s, color=color, ha=ha, va='center', fontsize=kw.pop('fontsize', 6),
                   clip_on=False, **kw)


def save(canvas, name):
    fig = canvas.fig
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    texts = [t for t in fig.findobj(Text) if t.get_visible() and t.get_text().strip()]
    boxes = [t.get_window_extent(r) for t in texts]
    overlaps, outside = [], []
    for i, b in enumerate(boxes):
        if b.x0 < -.5 or b.y0 < -.5 or b.x1 > fig.bbox.width + .5 or b.y1 > fig.bbox.height + .5:
            outside.append(texts[i].get_text())
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
               'out_of_bounds_text': outside})
    plt.close(fig)


# ----------------------------------------------------------------------------------------
# Figure 1: conceptual schematic
# ----------------------------------------------------------------------------------------

class Draw:
    """Vector glyphs in millimetre data coordinates."""

    def __init__(self, ax):
        self.a = ax

    def box(self, x, y, w, h, fc='white', ec='none', lw=.5, r=1.2, ls='-', z=1):
        self.a.add_patch(mp.FancyBboxPatch((x, y), w, h, boxstyle=f'round,pad=0,rounding_size={r}',
                                           fc=fc, ec=ec, lw=lw, ls=ls, zorder=z))

    def t(self, x, y, s, size=6.5, color=INK, ha='center', va='center', **kw):
        self.a.text(x, y, s, fontsize=size, color=color, ha=ha, va=va, zorder=5, **kw)

    def arrow(self, p, q, color=GREY, lw=.7, style='-|>', rad=0, ms=6):
        self.a.add_patch(mp.FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=ms, color=color,
                                            lw=lw, shrinkA=0, shrinkB=0, zorder=4,
                                            connectionstyle=f'arc3,rad={rad}'))

    def person(self, x, y, s, color):
        self.a.add_patch(mp.Circle((x, y + .32 * s), .2 * s, fc=color, ec='none', zorder=3))
        self.a.add_patch(mp.Wedge((x, y - .38 * s), .42 * s, 0, 180, fc=color, ec='none', zorder=3))

    def doc(self, x, y, w, h, color, fc='white', lines=3):
        f = .3 * w
        pts = [(x, y), (x + w, y), (x + w, y + h - f), (x + w - f, y + h), (x, y + h)]
        self.a.add_patch(mp.Polygon(pts, closed=True, fc=fc, ec=color, lw=.7, zorder=3,
                                    joinstyle='round'))
        self.a.plot([x + w - f, x + w - f, x + w], [y + h, y + h - f, y + h - f], color=color,
                    lw=.7, zorder=3, solid_joinstyle='round')
        for i in range(lines):
            yy = y + h * (.62 - i * .2)
            self.a.plot([x + .2 * w, x + .8 * w - (i == lines - 1) * .2 * w], [yy, yy],
                        color=color, lw=.6, zorder=3)

    def db(self, x, y, w, h, color):
        e = .26 * w
        self.a.add_patch(mp.Rectangle((x, y), w, h, fc='white', ec='none', zorder=3))
        for yy in [y, y + h / 2]:
            self.a.add_patch(mp.Arc((x + w / 2, yy), w, e, theta1=180, theta2=360, color=color,
                                    lw=.7, zorder=3))
        self.a.add_patch(mp.Ellipse((x + w / 2, y + h), w, e, fc='white', ec=color, lw=.7, zorder=3))
        self.a.plot([x, x], [y, y + h], color=color, lw=.7, zorder=3)
        self.a.plot([x + w, x + w], [y, y + h], color=color, lw=.7, zorder=3)

    def globe(self, x, y, r, color):
        self.a.add_patch(mp.Circle((x, y), r, fc='white', ec=color, lw=.7, zorder=3))
        self.a.add_patch(mp.Ellipse((x, y), r, 2 * r, fc='none', ec=color, lw=.6, zorder=3))
        for dy in [-.45 * r, 0, .45 * r]:
            half = np.sqrt(r ** 2 - dy ** 2)
            self.a.plot([x - half, x + half], [y + dy, y + dy], color=color, lw=.6, zorder=3)

    def lens(self, x, y, r, color, lw=.8):
        self.a.add_patch(mp.Circle((x, y), r, fc='white', ec=color, lw=lw, zorder=4))
        self.a.plot([x + .7 * r, x + 1.6 * r], [y - .7 * r, y - 1.6 * r], color=color, lw=lw * 1.6,
                    solid_capstyle='round', zorder=4)

    def funnel(self, x, y, w, h, color):
        pts = [(x, y + h), (x + w, y + h), (x + .6 * w, y + .4 * h), (x + .6 * w, y),
               (x + .4 * w, y), (x + .4 * w, y + .4 * h)]
        self.a.add_patch(mp.Polygon(pts, closed=True, fc='white', ec=color, lw=.7, zorder=3,
                                    joinstyle='round'))

    def badge(self, x, y, r, kind, color):
        self.a.add_patch(mp.Circle((x, y), r, fc=color, ec='none', zorder=4))
        k = dict(color='white', lw=.75, zorder=5, solid_capstyle='round', solid_joinstyle='round')
        if kind == 'check':
            self.a.plot([x - .45 * r, x - .1 * r, x + .5 * r], [y, y - .38 * r, y + .4 * r], **k)
        elif kind == 'cross':
            self.a.plot([x - .4 * r, x + .4 * r], [y - .4 * r, y + .4 * r], **k)
            self.a.plot([x - .4 * r, x + .4 * r], [y + .4 * r, y - .4 * r], **k)
        elif kind == 'minus':
            self.a.plot([x - .45 * r, x + .45 * r], [y, y], **k)
        elif kind == 'q':
            self.a.text(x, y - .05 * r, '?', color='white', fontsize=5.6, fontweight='bold',
                        ha='center', va='center', zorder=5)
        elif kind == 'loop':
            self.a.add_patch(mp.Arc((x, y), 1.1 * r, 1.1 * r, theta1=40, theta2=330, color='white',
                                    lw=.75, zorder=5))


def figure1():
    H = 70
    c = Canvas(H)
    ax = c.ax(0, 0, W, H)
    ax.set(xlim=(0, W), ylim=(0, H))
    ax.axis('off')
    d = Draw(ax)
    stages = [(1.5, 40, 'Define the rubric'), (45.5, 42, 'Discover candidates'),
              (91.5, 46, 'Research–Critique loop'), (141.5, 37, 'Audit and release')]
    top, bottom = 66, 2
    for i, (x, w, title) in enumerate(stages):
        d.box(x, bottom, w, top - bottom, fc='#F4F6F8', r=1.8, z=0)
        d.a.add_patch(mp.Circle((x + 4.2, top - 4.6), 2.2, fc=FULL, ec='none', zorder=3))
        d.t(x + 4.2, top - 4.65, str(i + 1), 6.5, 'white', fontweight='bold')
        d.t(x + 8, top - 4.6, title, 7.2, INK, ha='left', fontweight='bold')
        if i < 3:
            nx = stages[i + 1][0]
            d.arrow((x + w + .4, 34), (nx - .4, 34), color=FULL, lw=1.1, ms=7)

    # Stage 1: user and refinement agent agree a rubric.
    d.person(9.5, 47.5, 6, '#7A8793')
    d.t(9.5, 41.6, 'User', 6)
    d.person(32, 47.5, 6, FULL)
    d.t(32, 41.6, 'Refinement\nagent', 6, va='top', linespacing=1.05)
    d.arrow((14, 50.5), (27.5, 50.5), rad=-.3)
    d.arrow((27.5, 45.5), (14, 45.5), rad=-.3)
    d.t(20.75, 48, 'scope', 5.5, GREY, style='italic')
    d.box(4, 5, 35, 26, fc='white', ec='#C9D3DB', lw=.5, r=1.2)
    d.doc(6.5, 22.6, 4.2, 5.6, FULL)
    d.t(12.6, 25.4, 'User-approved rubric', 6.3, ha='left', fontweight='bold')
    items = [('T', 'Topic definition', '#7A8793'), ('M', 'Mandatory criteria', FULL),
             ('X', 'Exclusions', ROSE), ('O', 'Optional guidance', ADAPT)]
    for k, (tag, s, colr) in enumerate(items):
        yy = 18.4 - k * 3.9
        d.box(7, yy - 1.45, 4.2, 2.9, fc=colr, r=.6, z=3)
        d.t(9.1, yy - .05, tag, 5.6, 'white', fontweight='bold')
        d.t(13, yy, s, 6.1, ha='left')

    # Stage 2: topic-level literature discovery.
    x0 = 45.5
    d.globe(x0 + 7.5, 51.5, 3.6, FULL)
    d.t(x0 + 7.5, 45.6, 'Online APIs', 6)
    d.db(x0 + 3.9, 33.5, 7.2, 6.2, FULL)
    d.t(x0 + 7.5, 29.8, 'Offline corpus', 6)
    d.doc(x0 + 21.5, 47.2, 6.2, 8, FULL)
    d.lens(x0 + 27.3, 48.7, 1.9, FULL)
    d.t(x0 + 25, 43.4, 'Chemical NER\nand grounding', 6, va='top', linespacing=1.05)
    d.funnel(x0 + 21.8, 29.6, 7.4, 6.6, FULL)
    d.t(x0 + 25.5, 26.6, 'Ranking and triage', 6)
    d.arrow((x0 + 12.4, 51.5), (x0 + 20.5, 51.5))
    d.arrow((x0 + 12.4, 36.6), (x0 + 20.5, 49.5))
    d.arrow((x0 + 25.5, 38.6), (x0 + 25.5, 37.1))
    d.box(x0 + 3.5, 5, 35, 15.5, fc='white', ec='#C9D3DB', lw=.5, r=1.2)
    d.t(x0 + 21, 17.3, 'Candidate queue', 6.3, fontweight='bold')
    for k, s in enumerate(['Compound + context', 'Compound + context', '…']):
        yy = 13.2 - k * 3.4
        if s != '…':
            d.box(x0 + 7, yy - 1.3, 28, 2.6, fc=PALE, r=1.2, z=3)
        d.t(x0 + 21, yy, s, 5.8, GREY if s == '…' else INK)
    d.arrow((x0 + 25.5, 24.6), (x0 + 25.5, 20.9))

    # Stage 3: candidate-level Researcher-Critique loop.
    x0 = 91.5
    cx = [x0 + 11.5, x0 + 34.5]
    cy = [50, 33]
    d.person(cx[0], cy[0] + 1, 5.5, FULL)
    d.lens(cx[0] + 3, cy[0] - .8, 1.5, INK, lw=.7)
    d.t(cx[0], cy[0] - 4.7, 'Researcher', 6.2, fontweight='bold')
    d.t(cx[0], cy[0] - 7.4, 'searches and reads', 5.6, GREY)
    d.doc(cx[1] - 3, cy[0] - 2.3, 6, 7.4, FULL)
    d.t(cx[1], cy[0] - 4.7, 'Draft row', 6.2, fontweight='bold')
    d.t(cx[1], cy[0] - 7.4, 'provisional label', 5.6, GREY)
    d.person(cx[1], cy[1] + 1, 5.5, '#4A5A68')
    d.badge(cx[1] + 3.2, cy[1] - .9, 1.5, 'check', FULL)
    d.t(cx[1], cy[1] - 4.7, 'Critique', 6.2, fontweight='bold')
    d.t(cx[1], cy[1] - 7.4, 'checks the rubric', 5.6, GREY)
    d.badge(cx[0], cy[1] + 1, 2.6, 'loop', ADAPT)
    d.t(cx[0], cy[1] - 4.7, 'Follow-up', 6.2, fontweight='bold')
    d.t(cx[0], cy[1] - 7.4, 'next search target', 5.6, GREY)
    d.arrow((cx[0] + 5.5, cy[0] + 1.5), (cx[1] - 5, cy[0] + 1.5))
    d.arrow((cx[1], cy[0] - 9.3), (cx[1], cy[1] + 5.3))
    d.arrow((cx[1] - 6, cy[1] + 1), (cx[0] + 4.5, cy[1] + 1))
    d.arrow((cx[0], cy[1] + 5.3), (cx[0], cy[0] - 9.3))
    d.a.plot([x0 + 3, x0 + 43], [20.6, 20.6], color='#C9D3DB', lw=.5, ls=(0, (2, 1.5)))
    d.t(x0 + 23, 17.3, 'Critique decision', 6.3, fontweight='bold')
    decisions = [('check', 'Approve', FULL), ('loop', 'Follow-up', ADAPT),
                 ('cross', 'Exclude', ROSE), ('minus', 'Exhausted', '#8E8E8E')]
    for k, (kind, s, colr) in enumerate(decisions):
        xx = x0 + 6.5 + k * 11
        d.badge(xx, 11.2, 2.1, kind, colr)
        d.t(xx, 6.8, s, 5.8)

    # Stage 4: release checks and row labels.
    x0 = 141.5
    d.box(x0 + 3, 32.5, 31, 23.5, fc='white', ec='#C9D3DB', lw=.5, r=1.2)
    checks = ['Traceable source', 'Evidence matches claim', 'All criteria assessed',
              'Exclusions checked']
    for k, s in enumerate(checks):
        yy = 52 - k * 5.2
        d.badge(x0 + 6.8, yy, 1.6, 'check', FULL)
        d.t(x0 + 9.6, yy, s, 6, ha='left')
    d.t(x0 + 18.5, 27.4, 'Row labels', 6.3, fontweight='bold')
    outs = [('check', 'Confirmed', FULL), ('q', 'Unresolved', '#C99A3A'),
            ('cross', 'Explicit\nnegative', ROSE), ('minus', 'Limited\nevidence', '#8E8E8E')]
    for k, (kind, s, colr) in enumerate(outs):
        xx = x0 + 1.6 + (k % 2) * 17.4
        yy = 20.6 - (k // 2) * 10
        d.box(xx, yy - 3.8, 16.4, 7.6, fc='white', ec=colr, lw=.6, r=1.2)
        d.badge(xx + 2.9, yy, 1.7, kind, colr)
        d.t(xx + 5.3, yy, s, 5.7, ha='left', linespacing=1.0)
    save(c, 'Figure1')


# ----------------------------------------------------------------------------------------
# Figure 2: construction
# ----------------------------------------------------------------------------------------

def figure2():
    rows = {r['topic']: {k: int(v) for k, v in r.items() if k != 'topic'}
            for r in read(DATA / 'construction_final.csv')}
    c = Canvas(104)
    a = rows_axis(c.ax(19, 10, 44, 33), NAMES, (0, 640), [0, 200, 400, 600], 'Candidates')
    b = rows_axis(c.ax(109, 10, 44, 33), NAMES, (0, 100), [0, 50, 100],
                  'Encountered benchmark links retained (%)')
    cc = rows_axis(c.ax(19, 62, 44, 33), NAMES, (0, 100), [0, 50, 100], 'Benchmark-linked rows (%)')
    d = rows_axis(c.ax(109, 62, 44, 33), NAMES, (0, 100), [0, 50, 100], 'Located paper citations (%)')
    c.panel(2, 5, 'a', 'Evaluated and retained candidates')
    c.panel(92, 5, 'b', 'Known-compound retention')
    c.panel(2, 57, 'c', 'Benchmark linkage')
    c.panel(92, 57, 'd', 'Citation provenance')
    col(a, 1.17, 4.75, 'Evaluated per\nretained row', GREY, 'center', fontsize=5.5, linespacing=1)
    col(b, 1.04, 4.75, 'Retained', GREY, fontsize=5.5)
    for ax in (cc, d):
        col(ax, 1.035, 4.75, 'DB-Curator', FULL, fontsize=5.5, fontweight='bold')
        col(ax, 1.36, 4.75, 'Zero-shot', GREY, fontsize=5.5, fontweight='bold')
        ax.plot(1.015, 4.75, 'o', color=FULL, ms=3.4, mec='white', mew=.3,
                transform=ax.get_yaxis_transform(), clip_on=False)
        ax.plot(1.335, 4.75, 's', mfc='white', mec=GREY, ms=3.1, mew=.7,
                transform=ax.get_yaxis_transform(), clip_on=False)
    d.tick_params(axis='y', pad=6)
    for ax in (b, cc, d):
        for v in (50, 100):
            ax.axvline(v, color=GRID, lw=.5, zorder=0)
    for i, t in enumerate(TOPICS):
        r, y = rows[t], 4 - i
        n, ret = r['processed_candidates'], r['final_confirmed']
        a.barh(y, n, .62, color=PALE, lw=0)
        a.barh(y, ret, .62, color=FULL, lw=0)
        lab(a, ret - 8, y, str(ret), 'white', 'right', fontweight='bold')
        lab(a, n + 8, y, str(n), GREY)
        col(a, 1.17, y, f'{n / ret:.2f}×', INK, 'center')
        num, den = r['released_benchmark_linked'], r['processed_benchmark_linked']
        v = 100 * num / den
        b.hlines(y, 0, v, color=FULL, lw=.8)
        b.plot(v, y, 'o', color=FULL, ms=4.2, mec='white', mew=.4)
        col(b, 1.04, y, f'{v:.1f}%', INK, fontweight='bold')
        col(b, 1.23, y, f'{num}/{den}', GREY)
        zs = r['zero_shot_benchmark_linked']
        cv, zv = 100 * num / ret, 100 * zs / 200
        cc.plot([zv, cv], [y, y], color='#C8C8C8', lw=1, zorder=1)
        cc.plot(zv, y, 's', mfc='none', mec=GREY, ms=3.9, mew=.8, zorder=4)
        cc.plot(cv, y, 'o', color=FULL, ms=4.2, mec='white', mew=.4, zorder=3)
        col(cc, 1.04, y, f'{num}/{ret}', FULL)
        col(cc, 1.36, y, f'{zs}/200', GREY)
        yes, tot = r['verified_citations'], r['citation_instances']
        v = 100 * yes / tot
        d.plot([0, v], [y, y], color='#C8C8C8', lw=1, zorder=1)
        d.plot(0, y, 's', mfc='white', mec=GREY, ms=3.9, mew=.8, zorder=2, clip_on=False)
        d.plot(v, y, 'o', color=FULL, ms=4.2, mec='white', mew=.4, zorder=3, clip_on=False)
        col(d, 1.04, y, f'{yes:,}/{tot:,}', FULL)
        col(d, 1.36, y, f"0/{r['zero_shot_citations']}", GREY)
    save(c, 'Figure2')


# ----------------------------------------------------------------------------------------
# Figure 3: benchmark decisions and evidence assessment
# ----------------------------------------------------------------------------------------

def figure3():
    bench = {r['topic']: r for r in read(DATA / 'benchmark_final.csv')}
    model = read(STORY / 'model_support.csv')
    reasons = read(STORY / 'non_support_reasons.csv')
    expert = {r['cohort']: r for r in read(STORY / 'expert_review.csv')}
    assert sum(int(r['total']) for r in reasons) == 170
    c = Canvas(110)
    r1, r2, h = 10, 60, 30
    a = rows_axis(c.ax(17, r1, 30, h), NAMES, (0, 75), [0, 25, 50, 75], 'Final Confirmed (%)')
    b = rows_axis(c.ax(75, r1, 26, h), NAMES, (0, 100), [0, 50, 100], 'Located citations (%)',
                  show_labels=False)
    e3 = rows_axis(c.ax(144, r1, 24, h), ['Construction', 'Benchmark', 'Zero-shot'], (0, 100),
                   [0, 50, 100], 'Expert agreement (%)')
    d = rows_axis(c.ax(17, r2, 30, h), NAMES, (40, 100), [40, 70, 100], 'Supported packets (%)')
    e = rows_axis(c.ax(75, r2, 26, h), NAMES, (0, 100), [0, 50, 100], 'Packets per topic',
                  show_labels=False)
    reason_names = ['Direct evidence', 'Exact identity', 'Reaction role', 'Rubric meaning',
                    'Biological origin']
    f = rows_axis(c.ax(144, r2, 24, h), reason_names, (0, 120), [0, 50, 100],
                  'Non-support judgments')
    c.panel(2, 5, 'a', 'Benchmark decisions')
    c.panel(71, 5, 'b', 'Citation provenance')
    c.panel(120, 5, 'c', 'Expert review')
    c.panel(2, 55, 'd', 'Model evidence assessment')
    c.panel(71, 55, 'e', 'Joint model assessment')
    c.panel(120, 55, 'f', 'Why support was withheld')
    for ax in (b,):
        for v in (50, 100):
            ax.axvline(v, color=GRID, lw=.5, zorder=0)
    for i, t in enumerate(TOPICS):
        r, y = bench[t], 4 - i
        n, yes = int(r['candidates']), int(r['final_confirmed'])
        v = 100 * yes / n
        a.barh(y, v, .62, color=FULL, lw=0)
        lab(a, v + 1.5, y, f'{v:.1f}%', fontweight='bold')
        col(a, 1.02, y, f'{yes}/{n}', GREY)
        n, yes = int(r['citation_instances']), int(r['verified_citations'])
        v = 100 * yes / n
        b.hlines(y, 0, v, color=FULL, lw=.8)
        b.plot(v, y, 'o', color=FULL, ms=4.2, mec='white', mew=.4)
        col(b, 1.04, y, f'{v:.1f}%', fontweight='bold')
        col(b, 1.33, y, f'{yes:,}/{n:,}', GREY)
    for y, key, colr in [(2, 'DB-Curator construction', FULL), (1, 'Benchmark verification', FULL),
                         (0, 'Zero-shot construction', ZERO)]:
        r = expert[key]
        n, ok = int(r['n']), int(r['agreement'])
        v = 100 * ok / n
        e3.barh(y, v, .62, color=colr, lw=0)
        lab(e3, 3, y, f'{ok:,}/{n:,}', 'white' if colr == FULL else INK)
        col(e3, 1.03, y, f'{v:.1f}%', fontweight='bold')
    col(a, 1.02, 4.85, 'n', GREY, fontsize=5.5, style='italic')
    col(d, 1.03, 4.85, 'Claude', CLAUDE, fontsize=5.5, fontweight='bold')
    col(d, 1.30, 4.85, 'GPT', GPT, fontsize=5.5, fontweight='bold')
    for v in (70, 100):
        d.axvline(v, color=GRID, lw=.5, zorder=0)
    for y, r in zip(range(4, -1, -1), model):
        cv, gv = int(r['claude']), int(r['gpt'])
        d.plot([cv, gv], [y, y], color='#C8C8C8', lw=1, zorder=1)
        d.plot(gv, y, 's', mfc='white', mec=GPT, ms=3.9, mew=.9, zorder=2)
        d.plot(cv, y, 'o', color=CLAUDE, ms=4, mec='white', mew=.3, zorder=3)
        col(d, 1.03, y, str(cv), CLAUDE)
        col(d, 1.30, y, str(gv), GPT)
        left = 0
        for v, colr, tc in [(int(r['both']), FULL, 'white'), (int(r['differ']), '#9EC3DD', INK),
                            (int(r['neither']), '#E2E2E2', INK)]:
            e.barh(y, v, .62, left=left, color=colr, edgecolor='white', lw=.4)
            if v >= 8:
                lab(e, left + v / 2, y, str(v), tc, 'center')
            left += v
        assert left == 100
    e.legend(handles=[mp.Patch(color=FULL, label='Both'), mp.Patch(color='#9EC3DD', label='One'),
                      mp.Patch(color='#E2E2E2', label='Neither')],
             loc='upper center', bbox_to_anchor=(.5, -.36), ncol=3, frameon=False, fontsize=5.8,
             handlelength=1, handleheight=.7, columnspacing=.9, handletextpad=.3)
    for y, r in zip(range(4, -1, -1), reasons):
        v = int(r['total'])
        f.barh(y, v, .62, color=ROSE, lw=0)
        lab(f, v + 3, y, str(v))
    save(c, 'Figure3')


# ----------------------------------------------------------------------------------------
# Figure 4: evidence acquisition, consistency and cost
# ----------------------------------------------------------------------------------------

def figure4():
    rep = read(STORY / 'repeats.csv')
    swap = read(STORY / 'model_swap.csv')
    costs = {r['condition']: r for r in read(STORY / 'costs.csv')}
    contrasts = [r for r in read(DATA / 'repeated_contrasts.csv') if r['topic'] == 'all']
    counts = [317, 475, 645, 671]
    assert sorted({int(r[k]) for r in contrasts for k in ['a_confirmed', 'b_confirmed']}) == counts
    c = Canvas(114)
    r1, r2, h = 10, 64, 30
    stages = ['Zero-shot', 'Frozen retrieval', 'Adaptive search', 'Full']
    a = rows_axis(c.ax(22, r1, 26, h), stages, (0, 60), [0, 20, 40, 60], 'Confirmed labels (%)')
    b = rows_axis(c.ax(83, r1, 32, h), NAMES, (0, 32), [0, 10, 20, 30],
                  'Change (percentage points)')
    cc = rows_axis(c.ax(126, r1, 40, h), NAMES, (0, 100), [0, 25, 50, 75, 100],
                   'Full-system Confirmed (%)', show_labels=False)
    d = rows_axis(c.ax(17, r2, 36, h), NAMES, (0, 9), [0, 3, 6, 9], 'Adaptive-to-full change (pp)')
    e = rows_axis(c.ax(87, r2, 34, h), ['Zero-shot', 'Frozen retrieval', 'Full'], (2, 6), [2, 3, 4, 5, 6],
                  'Mean tokens per candidate', ticklabels=['10$^2$', '10$^3$', '10$^4$', '10$^5$', '10$^6$'])
    g = rows_axis(c.ax(131, r2, 34, h), ['Zero-shot', 'Frozen retrieval', 'Full'], (0, 320),
                  [0, 100, 200, 300], 'Mean time per candidate (s)', show_labels=False)
    c.panel(2, 5, 'a', 'Stages of evidence acquisition')
    c.panel(68, 5, 'b', 'Where yield increases')
    c.panel(124, 5, 'c', 'Consistency across repeats')
    c.panel(2, 59, 'd', 'Two Critique configurations')
    c.panel(68, 59, 'e', 'Token investment')
    c.panel(129, 59, 'f', 'Time to a decision')
    for y, n, colr in zip(range(3, -1, -1), counts, [ZERO, FROZEN, ADAPT, FULL]):
        v = 100 * n / 1500
        a.barh(y, v, .62, color=colr, lw=0)
        lab(a, v + 1.2, y, f'{v:.1f}%', fontweight='bold')
        col(a, 1.03, y, f'{n}', GREY)
    col(a, 1.03, 3.85, 'n', GREY, fontsize=5.5, style='italic')
    paired = read(DATA / 'repeated_contrasts.csv')
    full_adapt = {r['topic']: float(r['difference_pp']) for r in paired if r['contrast'] == 'Full-Dynamic'}
    full_static = {r['topic']: float(r['difference_pp']) for r in paired if r['contrast'] == 'Full-Static'}
    for y, r, t in zip(range(4, -1, -1), rep, TOPICS):
        # Paired contrasts, as in the previous figure and Table 1, not differences of rounded means.
        full = full_adapt[t]
        adaptive = full_static[t] - full
        for yy, v, colr in [(y + .17, adaptive, ADAPT), (y - .17, full, FULL)]:
            b.barh(yy, v, .3, color=colr, lw=0)
            lab(b, v + .5, yy, f'+{v:.1f}', fontsize=5.6)
        lo, hi, mean = int(r['min']), int(r['max']), float(r['full'])
        cc.hlines(y, lo, hi, color=FULL, lw=2.6, alpha=.35, capstyle='round')
        cc.plot(mean, y, 'o', color=FULL, ms=4.2, mec='white', mew=.4)
        col(cc, 1.05, y, f"{r['agreement']}%", INK)
    for v in (25, 50, 75, 100):
        cc.axvline(v, color=GRID, lw=.5, zorder=0)
    col(cc, 1.05, 4.85, 'Same label', GREY, fontsize=5.5)
    b.legend(handles=[mp.Patch(color=ADAPT, label='Frozen → adaptive'),
                      mp.Patch(color=FULL, label='Adaptive → full')],
             loc='upper center', bbox_to_anchor=(.5, -.36), ncol=2, frameon=False, fontsize=5.8,
             handlelength=1, handleheight=.7, handletextpad=.3, columnspacing=.9)
    for i in range(5):
        y = 4 - i
        for j, colr in [(0, GPT), (1, GEMINI)]:
            r = swap[2 * i + j]
            yy = y + .17 if j == 0 else y - .17
            v = float(r['change_pp'])
            d.barh(yy, v, .3, color=colr, lw=0)
            lab(d, v + .15, yy, f'+{v:.1f}', fontsize=5.6)
    d.legend(handles=[mp.Patch(color=GPT, label='GPT-5-mini'),
                      mp.Patch(color=GEMINI, label='Gemini 2.5 Flash')],
             loc='upper center', bbox_to_anchor=(.5, -.36), ncol=2, frameon=False, fontsize=5.8,
             handlelength=1, handleheight=.7, handletextpad=.3, columnspacing=.9)
    rows = [('Zero-shot', ZERO), ('Static RAG', FROZEN), ('Full DB-Curator', FULL)]
    for y, (k, colr) in zip([2, 1, 0], rows):
        tok = int(costs[k]['mean_tokens'])
        x = np.log10(tok)
        e.hlines(y, 2, x, color=colr, lw=.8)
        e.plot(x, y, 'o', color=colr, ms=4.4, mec='white', mew=.4)
        lab(e, x + .12, y, f'{tok:,}')
        sec = costs[k]['mean_seconds']
        if sec == '--':
            lab(g, 4, y, 'not recorded', GREY, style='italic')
        else:
            g.barh(y, float(sec), .55, color=colr, lw=0)
            lab(g, float(sec) + 5, y, f'{float(sec):.1f}')
    save(c, 'Figure4')


# ----------------------------------------------------------------------------------------
# Figure 5: criterion profiles
# ----------------------------------------------------------------------------------------

def figure5():
    data = read(DATA / 'criterion_indicators.csv')
    short = [
        ['Direct treatment attribution', 'Disinfectant–precursor reaction',
         'Disinfection or oxidation', 'Specific chemical'],
        ['Blood / systemic circulation', 'Human blood specimen', 'Endogenous / exogenous allowed',
         'Literature or dataset support'],
        ['Drug modality*', 'Formulation exclusion', 'Pharmacological effect', 'Specific drug entity'],
        ['Host / microbiota allowed', 'Human production', 'Human biochemical function',
         'Small molecule'],
        ['Analytical evidence', 'Unambiguous structure', 'Non-secondary exclusion',
         'Specific chemical'],
    ]
    full = ['Disinfection by-products', 'Blood exposome', 'Drugs', 'Endogenous metabolites',
            'Microbial natural products']
    tag_colour = {'M': FULL, 'X': ROSE, 'O': ADAPT}
    c = Canvas(112)
    for j, t in enumerate(TOPICS):
        rows = [r for r in data if r['topic'] == t]
        cx, cy = (j % 2) * 91, 9 + (j // 2) * 35
        ax = rows_axis(c.ax(cx + 38, cy + 4, 38, 20), ['', '', '', ''], (0, 100), [0, 50, 100],
                       'Criterion indicator (%)' if j >= 3 else '')
        ax.tick_params(axis='x', labelbottom=True)
        for v in (0, 50, 100):
            ax.axvline(v, color=GRID, lw=.5, zorder=0)
        nconf, noth = int(float(rows[0]['rows_confirmed'])), int(float(rows[0]['rows_other']))
        c.panel(cx + 2, cy, chr(97 + j), full[j])
        c.text(cx + 87, cy, f'{nconf} Confirmed / {noth} other', fontsize=5.5, color=GREY, ha='right')
        for i, (r, name) in enumerate(zip(rows, short[j])):
            y = 3 - i
            co, ot = 100 * float(r['pass_rate_confirmed']), 100 * float(r['pass_rate_other'])
            ax.plot([ot, co], [y, y], color='#C8C8C8', lw=1, zorder=1)
            ax.plot(ot, y, 'D', mfc='white', mec=ROSE, ms=3.6, mew=.9, zorder=2)
            ax.plot(co, y, 'o', color=FULL, ms=4.2, mec='white', mew=.4, zorder=3)
            col(ax, -.075, y, name, INK, 'right')
            tag = r['gate_type']
            ax.text(-.02, y, tag, transform=ax.get_yaxis_transform(), ha='center', va='center',
                    fontsize=4.8, color='white', fontweight='bold', clip_on=False,
                    bbox=dict(boxstyle='round,pad=.18,rounding_size=.3', fc=tag_colour[tag], ec='none'))
            col(ax, 1.2, y, f'{co - ot:+.1f}', INK, 'right', fontweight='bold' if co - ot >= 50 else None)
        col(ax, 1.2, 3.95, 'Δ (pp)', GREY, 'right', fontsize=5.5)
    # Key in the empty sixth cell.
    k = c.ax(91 + 6, 9 + 70 + 2, 80, 22)
    k.axis('off')
    k.set(xlim=(0, 80), ylim=(0, 22))
    k.plot(4, 18, 'o', color=FULL, ms=4.2, mec='white', mew=.4)
    k.text(7, 18, 'Confirmed', va='center', fontsize=6)
    k.plot(30, 18, 'D', mfc='white', mec=ROSE, ms=3.6, mew=.9)
    k.text(33, 18, 'Other outcomes', va='center', fontsize=6)
    for n, (tag, s) in enumerate([('M', 'Mandatory'), ('X', 'Exclusion'), ('O', 'Optional')]):
        x = 4 + n * 22
        k.text(x, 11, tag, ha='center', va='center', fontsize=4.8, color='white', fontweight='bold',
               bbox=dict(boxstyle='round,pad=.18,rounding_size=.3', fc=tag_colour[tag], ec='none'))
        k.text(x + 3, 11, s, va='center', fontsize=6)
    k.text(1.5, 4, '* Either-branch aggregate for drug modality', va='center', fontsize=5.5, color=GREY)
    save(c, 'Figure5')


if __name__ == '__main__':
    for fn in (figure1, figure2, figure3, figure4, figure5):
        fn()
    (ROOT / 'NATURE_RENDER_QA.json').write_text(json.dumps(QA, indent=2) + '\n')
    for q in QA:
        print(q['figure'], 'overlaps:', q['text_overlaps'], 'outside:', q['out_of_bounds_text'])
