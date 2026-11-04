"""Second Nature-style pass: varied chart forms for Figs 2-5 and a case-study Fig 6.

Reuses the layout helpers and palette of nature_figures.py. Figure 1 keeps the original artwork.
Case quotations are copied verbatim from source_data/final_confirmed_evidence_inspection.
"""
import json
import textwrap

import numpy as np
from matplotlib import patches as mp
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from matplotlib.path import Path as MPath

from nature_figures import (ADAPT, CLAUDE, DATA, FROZEN, FULL, GEMINI, GPT, GREY, GRID, INK, NAMES,
                            OUT, PALE, QA, ROOT, ROSE, STORY, TOPICS, ZERO, Canvas, col, lab, read,
                            rows_axis, save)

CASES = ROOT.parent / 'source_data/final_confirmed_evidence_inspection/all_11_inspections.json'
BLUES = LinearSegmentedColormap.from_list('blues', ['#F2F6FA', '#AFCBE0', '#5D9AC6', '#1E5B88', '#0F3553'])
DIVERGE = LinearSegmentedColormap.from_list('div', ['#B2453B', '#E8B9B2', '#F4F4F4', '#AFCBE0', '#1E5B88'])
AMBER = '#C99A3A'


def bare(ax):
    ax.axis('off')
    return ax


def ribbon(ax, x0, y0a, y0b, x1, y1a, y1b, color, alpha=.45):
    """Smooth band from a vertical span at x0 to one at x1."""
    xm = (x0 + x1) / 2
    verts = [(x0, y0a), (xm, y0a), (xm, y1a), (x1, y1a), (x1, y1b), (xm, y1b), (xm, y0b), (x0, y0b),
             (x0, y0a)]
    codes = [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4, MPath.LINETO, MPath.CURVE4,
             MPath.CURVE4, MPath.CURVE4, MPath.CLOSEPOLY]
    ax.add_patch(mp.PathPatch(MPath(verts, codes), fc=color, ec='none', alpha=alpha, zorder=1))


def donut(ax, x, y, r, frac, color, w=.32):
    ax.add_patch(mp.Wedge((x, y), r, 0, 360, width=w * r, fc='#E9EEF2', ec='none'))
    ax.add_patch(mp.Wedge((x, y), r, 90 - 360 * frac, 90, width=w * r, fc=color, ec='none'))


def waffle(ax, x0, y0, filled, color, cell=1.0, gap=.22, empty='#E6E9EC'):
    for k in range(100):
        i, j = k % 10, k // 10
        ax.add_patch(mp.FancyBboxPatch((x0 + i * (cell + gap), y0 + j * (cell + gap)), cell, cell,
                                       boxstyle='round,pad=0,rounding_size=.18',
                                       fc=color if k < filled else empty, ec='none'))


# ----------------------------------------------------------------------------------------
# Figure 2
# ----------------------------------------------------------------------------------------

def figure2():
    rows = {r['topic']: {k: int(v) for k, v in r.items() if k != 'topic'}
            for r in read(DATA / 'construction_final.csv')}
    c = Canvas(112)
    c.panel(2, 5, 'a', 'From discovery to retained rows')
    c.panel(104, 5, 'b', 'Known-compound retention')
    c.panel(2, 62, 'c', 'Benchmark linkage')
    c.panel(74, 62, 'd', 'Citation provenance')

    # a: recorded processing effort and the final 200-row databases.
    a = bare(c.ax(2, 9, 98, 48))
    a.set(xlim=(0, 100), ylim=(0, 100))
    proc = [rows[t]['processed_candidates'] for t in TOPICS]
    ret = [rows[t]['final_confirmed'] for t in TOPICS]
    assert all(n == 200 for n in ret)
    scale = 76 / sum(proc)
    gap = 2.2
    colx = [28, 80]
    tops = []
    for vals, x in zip([proc, ret], colx):
        y = 96
        spans = []
        tot = sum(vals) * scale + gap * 4
        y = 46 + tot / 2 if x != colx[0] else 90
        for v in vals:
            h = v * scale
            spans.append((y - h, y))
            y -= h + gap
        tops.append(spans)
    for i in range(5):
        for k in range(1):
            (p0, p1), (q0, q1) = tops[k][i], tops[k + 1][i]
            h = (q1 - q0)
            ribbon(a, colx[k] + 1.2, p1, p1 - h, colx[k + 1] - 1.2, q1, q0, FULL if k else ADAPT,
                   .28 if k == 0 else .45)
    for k, (spans, vals) in enumerate(zip(tops, [proc, ret])):
        for (y0, y1), v, name in zip(spans, vals, NAMES):
            a.add_patch(mp.Rectangle((colx[k] - 1.2, y0), 2.4, y1 - y0,
                                     fc=FULL if k else '#8FB5D3', ec='none'))
            if k == 0:
                a.text(colx[k] - 2.4, (y0 + y1) / 2, name, ha='right', va='center', fontsize=6.3)
            a.text(colx[k] + 2.4, (y0 + y1) / 2, f'{v}', ha='left', va='center', fontsize=5.8,
                   color=GREY if k == 0 else INK, fontweight='bold' if k == 1 else None)
    for x, top, bottom in zip(colx, ['Processed records', 'Retained entries'],
                              [f'{sum(proc):,}', f'{sum(ret):,}']):
        a.text(x, 99, top, ha='center', va='center', fontsize=6, fontweight='bold')
        a.text(x, 95, bottom, ha='center', va='center', fontsize=5.8, color=GREY)

    # b: retention rings.
    b = bare(c.ax(104, 9, 74, 48))
    b.set(xlim=(0, 74), ylim=(0, 48), aspect='equal')
    for i, t in enumerate(TOPICS):
        r = rows[t]
        num, den = r['released_benchmark_linked'], r['processed_benchmark_linked']
        x, y = 9 + (i % 3) * 25, 34 - (i // 3) * 23
        donut(b, x, y, 8.2, num / den, FULL)
        b.text(x, y + .9, f'{100 * num / den:.0f}%', ha='center', va='center', fontsize=7.2,
               fontweight='bold')
        b.text(x, y - 2.4, f'{num}/{den}', ha='center', va='center', fontsize=5.4, color=GREY)
        b.text(x, y - 10.6, NAMES[i], ha='center', va='center', fontsize=6.2)
    b.text(59, 11, 'Distinct benchmark\nidentities encountered\nthat entered\nthe database',
           ha='center', va='center', fontsize=5.6, color=GREY, linespacing=1.15)

    # c: slope chart, zero-shot vs DB-Curator benchmark linkage.
    cc = c.ax(16, 70, 38, 32)
    cc.set(xlim=(-.35, 1.35), ylim=(0, 105), xticks=[0, 1], yticks=[0, 50, 100])
    cc.set_xticklabels(['Zero-shot', 'DB-Curator'])
    cc.set_ylabel('Benchmark-linked rows (%)')
    cc.spines['bottom'].set_visible(False)
    cc.tick_params(axis='x', length=0)
    for i, t in enumerate(TOPICS):
        r = rows[t]
        zv = 100 * r['zero_shot_benchmark_linked'] / 200
        cv = 100 * r['released_benchmark_linked'] / r['final_confirmed']
        cc.plot([0, 1], [zv, cv], color='#9BB7CC', lw=1)
        cc.plot(0, zv, 's', mfc='white', mec=GREY, ms=3.6, mew=.8)
        cc.plot(1, cv, 'o', color=FULL, ms=4, mec='white', mew=.4)
    lab_y = {name:100 * rows[t]['released_benchmark_linked'] / rows[t]['final_confirmed']
             for name, t in zip(NAMES, TOPICS)}
    nudge = {'Drugs': -4, 'DBPs': 4}
    for name, v in lab_y.items():
        lab(cc, 1.1, v + nudge.get(name, 0), name, fontsize=5.6)

    # d: waffles, each cell 1% of paper citations.
    d = bare(c.ax(74, 66, 104, 44))
    d.set(xlim=(0, 104), ylim=(0, 44), aspect='equal')
    yes = sum(rows[t]['verified_citations'] for t in TOPICS)
    tot = sum(rows[t]['citation_instances'] for t in TOPICS)
    zero_tot = sum(rows[t]['zero_shot_citations'] for t in TOPICS)
    assert yes == tot and tot > 0 and zero_tot > 0
    for x0, filled, colr, title, sub in [(4, int(100 * yes / tot), FULL, 'DB-Curator retained rows',
                                          f'{yes:,} / {tot:,} located'),
                                         (56, 0, FULL, 'Zero-shot', f'0/{zero_tot} located (0%)')]:
        waffle(d, x0, 1, filled, colr, cell=2.6, gap=.55)
        d.text(x0, 39.5, title, fontsize=6.6, fontweight='bold', va='center')
        d.text(x0, 36, sub, fontsize=5.8, color=GREY, va='center')
    d.text(104, 39.5, 'Each square = 1% of paper citations', ha='right', va='center', fontsize=5.4,
           color=GREY)
    save(c, 'Figure2')


# ----------------------------------------------------------------------------------------
# Figure 3
# ----------------------------------------------------------------------------------------

def treemap(ax, items, x, y, w, h, colors):
    """Slice-and-dice treemap: largest item takes the left block, the rest stack on the right."""
    total = sum(v for _, v in items)
    first = items[0]
    w0 = w * first[1] / total
    blocks = [(first, x, y, w0, h)]
    rest = items[1:]
    rt = sum(v for _, v in rest)
    yy = y + h
    for it in rest:
        hh = h * it[1] / rt
        blocks.append((it, x + w0, yy - hh, w - w0, hh))
        yy -= hh
    for ((name, v), bx, by, bw, bh), colr in zip(blocks, colors):
        ax.add_patch(mp.Rectangle((bx, by), bw, bh, fc=colr, ec='white', lw=1))
        if bh > 6:
            ax.text(bx + 1.2, by + bh - 1.4, name, fontsize=5.8, va='top', color='white')
            ax.text(bx + 1.2, by + bh - 1.6 - 2.9 * (name.count('\n') + 1), str(v), fontsize=7,
                    va='top', color='white', fontweight='bold')
        else:
            ax.text(x + w, y - 3.4, f'{name}: {v} (bottom strip)', fontsize=5.4, va='center',
                    ha='right', color=GREY)


def figure3():
    """Benchmark output and expert review, with no model-judge panels."""
    bench = {r['topic']: r for r in read(DATA / 'benchmark_final.csv')}
    expert = {r['cohort']: r for r in read(STORY / 'expert_review.csv')}
    review = json.loads((ROOT.parent / 'source_data/human_comment_recheck/'
                         'color_review_summary_20261029.json').read_text())['cohorts']
    c = Canvas(110)
    c.panel(2, 5, 'a', 'Benchmark decisions')
    c.panel(100, 5, 'b', 'Expert review')
    c.panel(2, 61, 'c', 'Construction review by topic')
    a = c.ax(14, 13, 80, 37)
    a.set(xlim=(-.6, 4.6), ylim=(0, 62), xticks=range(5), yticks=[0, 20, 40, 60])
    a.set_xticklabels(NAMES)
    a.set_ylabel('Final Confirmed (%)')
    a.tick_params(axis='x', length=0)
    for v in (20, 40, 60):
        a.axhline(v, color=GRID, lw=.5, zorder=0)
    for i, t in enumerate(TOPICS):
        r = bench[t]
        n, yes = int(r['candidates']), int(r['final_confirmed'])
        v = 100 * yes / n
        a.bar(i, v, .56, color=FULL, lw=0)
        lab(a, i, v + 2.4, f'{v:.1f}%', ha='center', fontweight='bold')
        lab(a, i, 2.8, f'{yes}/{n}', 'white', 'center', fontsize=5.4)
    b = bare(c.ax(100, 9, 78, 46))
    b.set(xlim=(0, 78), ylim=(0, 46), aspect='equal')
    for k, (key, name, color) in enumerate([
            ('DB-Curator construction', 'Construction', FULL),
            ('Benchmark verification', 'Benchmark', FULL),
            ('Zero-shot construction', 'Zero-shot', ZERO)]):
        r = expert[key]
        n, ok = int(r['n']), int(r['agreement'])
        x = 13 + k * 26
        donut(b, x, 26, 10, ok / n, color, w=.26)
        b.text(x, 27.3, f'{100 * ok / n:.1f}%', ha='center', va='center',
               fontsize=7.4, fontweight='bold')
        b.text(x, 23.4, f'{ok:,}/{n:,}', ha='center', va='center', fontsize=5.4, color=GREY)
        b.text(x, 12.6, name, ha='center', va='center', fontsize=6.3)
    ax = c.ax(31, 69, 107, 28)
    ax.set(xlim=(85, 102), ylim=(-.55, 4.55), yticks=range(5), xticks=[85, 90, 95, 100])
    ax.set_yticklabels(NAMES[::-1])
    ax.set_xlabel('Reviewer agreement (%)')
    ax.spines['left'].set_visible(False)
    ax.tick_params(axis='y', length=0)
    ax.axvline(100, color=GRID, lw=.6, zorder=0)
    for i, t in enumerate(TOPICS):
        y = 4 - i
        rc = review['construction_250_labeled_version']['topics'][t]
        rz = review['zero_shot_250']['topics'][t]
        cv, zv = 100 * rc['agreement']/rc['n'], 100 * rz['agreement']/rz['n']
        ax.plot([cv, zv], [y, y], color=ADAPT, lw=1.3, zorder=1)
        ax.scatter(cv, y+.10, s=22, color=FULL, marker='o', zorder=3)
        ax.scatter(zv, y-.10, s=22, facecolors='white', edgecolors=GREY, marker='s', zorder=3)
        col(ax, 1.04, y, f"{rc['agreement']}/50   |   {rz['agreement']}/50", fontsize=6.2)
    c.text(143, 66, 'DB-Curator | Zero-shot', fontsize=6, color=GREY)
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], marker='o', color=FULL, ls='', label='DB-Curator'),
                       Line2D([], [], marker='s', mfc='white', color=GREY, ls='', label='Zero-shot')],
              loc='lower left', bbox_to_anchor=(.03, 1.02), ncol=2, frameon=False, fontsize=6)
    save(c, 'Figure3')


# ----------------------------------------------------------------------------------------
# Figure 4
# ----------------------------------------------------------------------------------------

def figure4():
    rep = read(STORY / 'repeats.csv')
    swap = read(STORY / 'model_swap.csv')
    costs = {r['condition']: r for r in read(STORY / 'costs.csv')}
    paired = read(DATA / 'repeated_contrasts.csv')
    counts = [317, 475, 645, 671]
    c = Canvas(118)
    c.panel(2, 5, 'a', 'Where confirmations come from')
    c.panel(80, 5, 'b', 'Stage gains by topic')
    c.panel(2, 64, 'c', 'Consistency across repeats')
    c.panel(64, 64, 'd', 'Critique configurations')
    c.panel(122, 64, 'e', 'Yield and computation')

    # a: waterfall.
    a = c.ax(14, 12, 58, 40)
    labels = ['Zero-shot', 'Frozen\nretrieval', 'Adaptive\nsearch', 'Critique', 'Full']
    a.set(xlim=(-.6, 4.6), ylim=(0, 760), xticks=range(5), yticks=[0, 250, 500, 750])
    a.set_xticklabels(labels, fontsize=5.8)
    a.set_ylabel('Confirmed labels (of 1,500)')
    a.tick_params(axis='x', length=0)
    for v in (250, 500, 750):
        a.axhline(v, color=GRID, lw=.5, zorder=0)
    steps = [(0, 317, ZERO), (317, 475, FROZEN), (475, 645, ADAPT), (645, 671, FULL)]
    for i, (lo, hi, colr) in enumerate(steps):
        a.bar(i, hi - lo, .6, bottom=lo, color=colr, lw=0)
        txt = f'{hi}' if i == 0 else f'+{hi - lo}'
        lab(a, i, hi + 22, txt, ha='center', fontweight='bold')
        if i < 3:
            a.plot([i + .3, i + .7], [hi, hi], color=GREY, lw=.5, ls=(0, (2, 1.5)))
    a.plot([3.3, 3.7], [671, 671], color=GREY, lw=.5, ls=(0, (2, 1.5)))
    a.bar(4, 671, .6, color=FULL, lw=0)
    lab(a, 4, 693, '671', ha='center', fontweight='bold')
    lab(a, 4, 330, '44.7%', 'white', 'center', fontweight='bold')
    lab(a, 0, 150, '21.1%', INK, 'center')

    # b: diverging heatmap topic x stage gain.
    hm = c.ax(98, 14, 50, 38)
    mat = []
    zero_static = {r['topic']: r for r in rep}
    fa = {r['topic']: float(r['difference_pp']) for r in paired if r['contrast'] == 'Full-Dynamic'}
    fs = {r['topic']: float(r['difference_pp']) for r in paired if r['contrast'] == 'Full-Static'}
    sz = {r['topic']: float(r['difference_pp']) for r in paired if r['contrast'] == 'Static-Zero'}
    for t in TOPICS:
        mat.append([sz[t], fs[t] - fa[t], fa[t]])
    mat = np.array(mat)
    hm.imshow(mat, cmap=DIVERGE, norm=TwoSlopeNorm(0, -15, 30), aspect='auto')
    hm.set(xticks=range(3), yticks=range(5))
    hm.set_xticklabels(['Zero-shot\n→ frozen', 'Frozen\n→ adaptive', 'Adaptive\n→ full'],
                       fontsize=5.8)
    hm.set_yticklabels(NAMES)
    hm.xaxis.tick_top()
    hm.tick_params(length=0)
    for s in hm.spines.values():
        s.set_visible(False)
    for i in range(5):
        for j in range(3):
            v = mat[i, j]
            hm.text(j, i, f'{v:+.1f}', ha='center', va='center', fontsize=6.2,
                    color='white' if abs(v) > 18 else INK, fontweight='bold')
        hm.axhline(i + .5, color='white', lw=1.2)
    for j in range(2):
        hm.axvline(j + .5, color='white', lw=1.2)
    cb = c.ax(152, 20, 2.2, 26)
    grad = np.linspace(30, -15, 100)[:, None]
    cb.imshow(grad, cmap=DIVERGE, norm=TwoSlopeNorm(0, -15, 30), aspect='auto',
              extent=(0, 1, -15, 30))
    cb.set(xticks=[], yticks=[-15, 0, 15, 30])
    cb.yaxis.tick_right()
    cb.tick_params(labelsize=5.4, length=1.5, width=.4)
    for s in cb.spines.values():
        s.set_visible(False)
    c.text(150, 49.5, 'Change (pp)', fontsize=5.4, color=GREY)

    # c: repeat strip with range bars, vertical.
    cc = c.ax(12, 74, 44, 30)
    cc.set(xlim=(-.6, 4.6), ylim=(0, 85), xticks=range(5), yticks=[0, 40, 80])
    cc.set_xticklabels(NAMES, fontsize=5.6, rotation=30, ha='right', rotation_mode='anchor')
    cc.set_ylabel('Full Confirmed (%)')
    cc.tick_params(axis='x', length=0)
    for v in (40, 80):
        cc.axhline(v, color=GRID, lw=.5, zorder=0)
    for i, r in enumerate(rep):
        lo, hi, mean = int(r['min']), int(r['max']), float(r['full'])
        cc.add_patch(mp.FancyBboxPatch((i - .16, lo), .32, hi - lo, boxstyle='round,pad=0,rounding_size=.1',
                                       fc=FROZEN, ec='none', mutation_aspect=20))
        cc.plot(i, mean, 'o', color=FULL, ms=4, mec='white', mew=.4)
        lab(cc, i, hi + 6, f"{r['agreement']}%", ha='center', fontsize=5.6)
    c.text(12, 72, 'Labels above: same binary label in all three repeats', fontsize=5.2, color=GREY)

    # d: slope chart, adaptive -> full within each Critique configuration.
    d = c.ax(70, 74, 44, 30)
    d.set(xlim=(-.3, 1.3), ylim=(0, 9), xticks=[0, 1], yticks=[0, 3, 6, 9])
    d.set_xticklabels(['GPT-5-mini', 'Gemini 2.5\nFlash'], fontsize=5.8)
    d.set_ylabel('Adaptive → full (pp)')
    d.tick_params(axis='x', length=0)
    for i in range(5):
        g, m = float(swap[2 * i]['change_pp']), float(swap[2 * i + 1]['change_pp'])
        d.plot([0, 1], [g, m], color='#BBBBBB', lw=.9, zorder=1)
        d.plot(0, g, 'o', color=GPT, ms=4, mec='white', mew=.4, zorder=2)
        d.plot(1, m, 'o', color=GEMINI, ms=4, mec='white', mew=.4, zorder=2)
    for name, v in zip(NAMES, [7.3, 4.3, 1.3, 2.7, 2.3]):
        off = {'Endogenous': .35, 'Microbial NP': -.35}.get(name, 0)
        lab(d, 1.08, v + off, name, fontsize=5.4)

    # e: bubble chart, tokens vs yield, bubble area = runtime.
    e = c.ax(134, 74, 42, 30)
    e.set(xlim=(2, 6), ylim=(0, 60), xticks=[2, 3, 4, 5, 6], yticks=[0, 20, 40, 60])
    e.set_xticklabels(['10$^2$', '10$^3$', '10$^4$', '10$^5$', '10$^6$'])
    e.set_xlabel('Mean tokens per candidate')
    e.set_ylabel('Confirmed (%)')
    for v in (20, 40, 60):
        e.axhline(v, color=GRID, lw=.5, zorder=0)
    pts = []
    for key, n, colr, name in [('Zero-shot', 317, ZERO, 'Zero-shot'),
                               ('Static RAG', 475, FROZEN, 'Frozen'),
                               ('Full DB-Curator', 671, FULL, 'Full')]:
        x = np.log10(int(costs[key]['mean_tokens']))
        y = 100 * n / 1500
        sec = costs[key]['mean_seconds']
        size = 18 if sec == '--' else 18 + float(sec) * 1.4
        e.scatter(x, y, s=size, color=colr, edgecolor='white', lw=.5, zorder=3)
        pts.append((x, y))
        lab(e, x, y - 7.5 if name != 'Full' else y - 10, name, ha='center', fontsize=5.6)
    e.plot(*zip(*pts), color='#BBBBBB', lw=.7, zorder=2)
    lab(e, 4.62, 49.5, '271 s', GREY, 'center', fontsize=5.2)
    lab(e, 3.59, 38.5, '30 s', GREY, 'center', fontsize=5.2)
    lab(e, 2.1, 57, 'Bubble area: mean runtime', GREY, fontsize=5.2)
    save(c, 'Figure4')


# ----------------------------------------------------------------------------------------
# Figure 5: criterion heatmap with separation bars
# ----------------------------------------------------------------------------------------

def figure5():
    data = read(DATA / 'criterion_indicators.csv')
    short = [
        ['Direct treatment attribution', 'Disinfectant\u2013precursor reaction',
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
    entries, ypos, heads = [], [], []
    y = 0
    for j, t in enumerate(TOPICS):
        rows = [r for r in data if r['topic'] == t]
        heads.append((y, j, rows[0]))
        y += 1.25
        for r, name in zip(rows, short[j]):
            entries.append((name, r['gate_type'], 100 * float(r['pass_rate_confirmed']),
                            100 * float(r['pass_rate_other'])))
            ypos.append(y)
            y += 1
        y += .45
    H = y - .45
    c = Canvas(124)
    top, height = 8, 104
    lbl = c.ax(2, top, 58, height)
    hm = c.ax(64, top, 28, height)
    bar = c.ax(98, top, 62, height)
    for ax in (lbl, hm, bar):
        ax.set_ylim(H - .5, -.5)
    lbl.set_xlim(0, 58)
    lbl.axis('off')
    hm.set(xlim=(-.5, 1.5))
    hm.axis('off')
    hm.text(0, -1.0, 'Confirmed', ha='center', fontsize=5.8)
    hm.text(1, -1.0, 'Other', ha='center', fontsize=5.8)
    for yy, j, r0 in heads:
        lbl.text(0, yy, chr(97 + j), fontsize=8, fontweight='bold', va='center')
        lbl.text(4, yy, full[j], fontsize=6.6, fontweight='bold', va='center')
        hm.text(1.52, yy, f"{int(float(r0['rows_confirmed']))} / {int(float(r0['rows_other']))}",
                fontsize=5.3, color=GREY, va='center', ha='right')
    for (name, tag, co, ot), yy in zip(entries, ypos):
        lbl.text(53.5, yy, name, ha='right', va='center', fontsize=6)
        lbl.text(56.2, yy, tag, ha='center', va='center', fontsize=4.8, color='white',
                 fontweight='bold', bbox=dict(boxstyle='round,pad=.18,rounding_size=.3',
                                              fc=tag_colour[tag], ec='none'))
        for jj, v in enumerate((co, ot)):
            hm.add_patch(mp.Rectangle((jj - .48, yy - .44), .96, .88, fc=BLUES(v / 100), ec='none'))
            hm.text(jj, yy, f'{v:.0f}', ha='center', va='center', fontsize=5.6,
                    color='white' if v > 60 else INK)
        dv = co - ot
        bar.barh(yy, dv, .6, color=FULL, lw=0)
        lab(bar, dv + 1.5, yy, f'{dv:+.1f}', fontsize=5.6)
    bar.set(xlim=(0, 100), xticks=[0, 50, 100], yticks=[])
    bar.set_xlabel('Separation, Confirmed \u2212 other (pp)')
    bar.spines['left'].set_visible(False)
    for v in (50, 100):
        bar.axvline(v, color=GRID, lw=.5, zorder=0)
    c.text(98, top - 2, 'Criterion indicator (%) by outcome', fontsize=5.6, color=GREY)
    c.text(2, 121, 'M mandatory   X exclusion   O optional   * either-branch aggregate   '
           'Counts: Confirmed / other rows', fontsize=5.4, color=GREY)
    save(c, 'Figure5')


# ----------------------------------------------------------------------------------------
# Figure 6: evidence trajectories for three accepted records
# ----------------------------------------------------------------------------------------

def excerpt(q, *parts):
    """Join verbatim fragments of a quote in order, marking omissions with ellipses."""
    pos, out = 0, []
    for part in parts:
        i = q.find(part, pos)
        assert i >= 0, part[:40]
        out.append(('\u2026' if i > pos or (i > 0 and not out) else '') + part)
        pos = i + len(part)
    return ' '.join(out) + ('\u2026' if pos < len(q.rstrip()) else '')


def figure6():
    cases = {r['candidate']: r for r in json.loads(CASES.read_text())}

    def anchors(name, stage):
        return [a for ins in cases[name]['inspections'] for a in ins['source_anchors']
                if a['stage'] == stage]

    hb = next(k for k in cases if 'Hydroxybenzene' in k)
    iso = 'Isoterrelumamide A'
    pc = next(k for k in cases if k.startswith('PC('))
    for k in (hb, iso, pc):
        assert cases[k]['canonical_final_label'] == 'Confirmed' and cases[k]['canonical_accepted']
    a_hb0, a_hb1 = anchors(hb, 'initial_report')[0], anchors(hb, 'response')[1]
    a_iso0, a_iso1 = anchors(iso, 'initial_report')[0], anchors(iso, 'response')[1]
    a_pc0, a_pc1 = anchors(pc, 'initial_report')[0], anchors(pc, 'response')[1]
    assert all(a['location_status'] == 'exact' for a in (a_hb0, a_hb1, a_iso0, a_iso1, a_pc0, a_pc1))
    spec = [
        ('4-Hydroxyphthalic acid', 'Disinfection by-products', 'Precursor reaction',
         cases[hb]['critique_label'], True,
         a_hb0, excerpt(a_hb0['quote'], 'nine nonhalogenated aromatic compounds were identified as new '
                        'intermediate DBPs in chlorination, including', '4-hydroxyphthalic acid'),
         'Make the precursor link explicit: the cited passage shows chlorination formation but not '
         'the natural-organic-matter precursor.',
         a_hb1, excerpt(a_hb1['quote'], 'demonstrating that they somewhat acted as intermediates '
                        'between NOM and halogenated aromatic DBPs.'),
         'Same source now supports the precursor criterion'),
        ('Isoterrelumamide A', 'Microbial natural products', 'Secondary-metabolite status',
         'Insufficient evidence', True,
         a_iso0, excerpt(a_iso0['quote'], 'isoterrelumamide A (2)', 'The structures of the new compounds '
                         'were established by 1D and 2D NMR spectroscopic analysis as well as by HRESIMS.'),
         'Fungal isolation and structure are supported; secondary-metabolite status needs explicit '
         'evidence.',
         a_iso1, excerpt(a_iso1['quote'], 'Isoterrelumamide A (67)',
                         'the secondary metabolites detected are not always the same'),
         'Added literature names it as a secondary metabolite'),
        ('PC(20:2(11Z,14Z)/20:1(11Z))', 'Endogenous metabolites', 'Exact molecular species',
         'Insufficient evidence', False,
         a_pc0, excerpt(a_pc0['quote'], 'Eighteen metabolites associated with GPL metabolism were '
                        'identified', 'PC (20:3(8Z,11Z,14Z)/20:1(11Z))'),
         'Target: PC(20:2/20:1). Cited: PC(20:3/20:1). These differ in fatty-acyl unsaturation. Find evidence for the exact target.',
         a_pc1, excerpt(a_pc1['quote'], 'The Kennedy pathway represents the primary route for '
                        'phosphatidylcholine (PC) biosynthesis'),
         'PC class synthesis shown; exact target still unresolved'),
    ]
    rowh = 32
    c = Canvas(6 + 3 * rowh)
    for k, (name, domain, crit, mid_label, ok, a0, q0, req, a1, q1, note) in enumerate(spec):
        y0 = 4 + k * rowh
        c.panel(2, y0 + 2.4, chr(97 + k), name)
        ax = bare(c.ax(2, y0 + 4.5, 176, rowh - 6))
        h = rowh - 6
        ax.set(xlim=(0, 176), ylim=(0, h))
        ax.text(176, h + 3.3, f'{domain}  \u00b7  criterion: {crit}', ha='right', va='center',
                fontsize=5.6, color=GREY)
        cards = [(0, 60, 'Initial report', 'Confirmed', FULL, q0, a0, None),
                 (65, 46, 'Critique review', mid_label, AMBER, req, None, None),
                 (116, 60, 'Revised report', 'Confirmed', FULL, q1, a1, (ok, note))]
        for x, w, title, label, accent, body, anchor, outcome in cards:
            ax.add_patch(mp.FancyBboxPatch((x, 0), w, h, boxstyle='round,pad=0,rounding_size=1.4',
                                           fc='#F4F6F8' if accent == FULL else '#FBF5EA', ec='none'))
            ax.add_patch(mp.Rectangle((x, 0), .9, h, fc=accent, ec='none'))
            ax.text(x + 3, h - 3.4, title, fontsize=6.4, fontweight='bold', va='center')
            ax.text(x + w - 2.4, h - 3.4, label, fontsize=5.5, va='center', ha='right', color='white',
                    fontweight='bold', bbox=dict(boxstyle='round,pad=.28,rounding_size=.6',
                                                 fc=accent, ec='none'))
            width = 54 if w > 50 else 40
            if anchor is None:
                ax.text(x + 3, h - 8, textwrap.fill(body, width=width), fontsize=6, va='top',
                        linespacing=1.3)
            else:
                ax.text(x + 3, h - 8, textwrap.fill('\u201c' + body + '\u201d', width=width),
                        fontsize=6, va='top', style='italic', linespacing=1.3)
                ident = anchor['supplied_identifier']
                ident = ('doi:' if ident.startswith('10.') else 'PMID ') + ident
                ax.text(x + 3, 8 if outcome else 3.2, f'{ident}  \u00b7  passage located',
                        fontsize=5.2, color=GREY, va='center')
            if outcome:
                good, txt = outcome
                colr = FULL if good else ROSE
                ax.plot(x + 4, 3.2, 'o', ms=4.4, mfc=colr if good else 'white', mec=colr, mew=.9)
                ax.text(x + 6.2, 3.2, txt, fontsize=5.6, color=colr, va='center', fontweight='bold')
        for x0, x1 in [(60.6, 64.4), (111.6, 115.4)]:
            ax.add_patch(mp.FancyArrowPatch((x0, h / 2), (x1, h / 2), arrowstyle='-|>',
                                            mutation_scale=7, color=GREY, lw=.8))
    save(c, 'Figure6')


if __name__ == '__main__':
    QA.clear()
    for fn in (figure2, figure3, figure4, figure5, figure6):
        fn()
    (ROOT / 'NATURE_V2_RENDER_QA.json').write_text(json.dumps(QA, indent=2) + '\n')
    for q in QA:
        print(q['figure'], 'overlaps:', q['text_overlaps'], 'outside:', q['out_of_bounds_text'])
