"""Promote frozen SI results into story-led main figures; no new inference calls."""
import csv
import hashlib
import json
import re
import shutil
from pathlib import Path

import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

import generate as g

WORK = g.ROOT.parent
ARCHIVE = WORK.parent / 'editorial_archive/pre_story_panels_20261026'
g.OUT = WORK / 'figures/workshop_style'
SOURCE = g.DATA / 'story_panels'
SOURCE.mkdir(exist_ok=True)
TOPIC_COLORS = ['#719CAA', '#D4A58C', '#89ADA3', '#C3B176', '#B09EBC']


def export(name, fields, rows):
    with (SOURCE / name).open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(fields)
        writer.writerows(rows)


def extract():
    """Read numeric table entries from the frozen, pre-edit manuscript sources."""
    si = (ARCHIVE / 'DB_Curator_SI.tex').read_text()
    main = (ARCHIVE / 'DB_Curator_main.tex').read_text()
    model_block = si.split('Supplementary Table 6.')[1].split('Supplementary Table 7.')[0]
    model = []
    for line in model_block.splitlines():
        cells = line.strip().rstrip('\\').split('&')
        if len(cells) == 7 and cells[1].strip() == '100':
            model.append([cells[0].strip()] + [int(x.strip()) for x in cells[1:]])
    assert len(model) == 5
    assert np.array([r[2:] for r in model]).sum(axis=0).tolist() == [419, 411, 395, 65, 40]
    export('model_support.csv', ['topic','n','claude','gpt','both','neither','differ'], model)

    reason_block = si.split('Supplementary Table 7.')[1].split('Supplementary Note 11.')[0]
    reasons = []
    for line in reason_block.splitlines():
        cells = line.strip().rstrip('\\').split('&')
        if len(cells) == 4 and cells[1].strip().isdigit() and not cells[0].startswith('Non-support'):
            reasons.append([cells[0].strip()] + [int(x.strip()) for x in cells[1:]])
    assert sum(r[3] for r in reasons) == 170
    export('non_support_reasons.csv', ['reason','claude','gpt','total'], reasons)

    expert = []
    block = si.split('Supplementary Table 4.')[1].split('Supplementary Table 5.')[0]
    for line in block.splitlines():
        cells = line.strip().rstrip('\\').split('&')
        if len(cells) == 6 and cells[1].strip().replace(',', '').isdigit():
            expert.append([cells[0].strip()] + [int(x.strip().replace(',', '')) for x in cells[1:]])
    # Use the later reviewer adjudication for construction and zero-shot only.
    review = WORK / 'source_data/human_comment_recheck/color_review_summary_20261029.json'
    if review.exists():
        latest = json.loads(review.read_text())['cohorts']
        keys = {'DB-Curator construction': 'construction_250_labeled_version',
                'Zero-shot construction': 'zero_shot_250'}
        for row in expert:
            if row[0] in keys:
                r = latest[keys[row[0]]]
                row[3], row[4], row[5] = r['agreement'] - row[2], r['agreement'], r['n'] - r['agreement']
    benchmark_review = WORK / 'source_data/human_comment_recheck/benchmark_review_summary_20261030.json'
    if benchmark_review.exists():
        r = json.loads(benchmark_review.read_text())
        for row in expert:
            if row[0] == 'Benchmark verification':
                row[1:] = [r['n'], r['blank_agreement'], r['approved_comments'],
                           r['agreement'], r['not_counted_as_agreement']]
    export('expert_review.csv', ['cohort','n','blank','comment_agreement','agreement','other_comments'], expert)

    repeats = []
    block = main.split('Topic & Zero-shot & Static RAG')[1].split('\\bottomrule')[0]
    for line in block.splitlines():
        means = re.findall(r'\$(\d+(?:\.\d+)?)\\pm(\d+(?:\.\d+)?)\$', line)
        if len(means) == 4:
            lo, hi, agreement = re.search(r'& (\d+)--(\d+)\\% & (\d+)\\%', line).groups()
            repeats.append([line.split('&')[0].strip()] + [float(v[0]) for v in means] + [int(lo),int(hi),int(agreement)])
    assert len(repeats) == 5
    export('repeats.csv', ['topic','zero','static','adaptive','full','min','max','agreement'], repeats)

    swap = []
    block = main.split('Topic & Critique model &')[1].split('\\bottomrule')[0]
    for line in block.splitlines():
        means = re.findall(r'\$(\d+(?:\.\d+)?)\\pm(\d+(?:\.\d+)?)\$', line)
        if len(means) == 2:
            delta = float(re.search(r'\$\+(\d+\.\d+)\$', line).group(1))
            cells = line.split('&')
            swap.append([cells[0].strip(), cells[1].strip(), float(means[0][0]), float(means[1][0]), delta])
    assert len(swap) == 10
    export('model_swap.csv', ['topic','critic','adaptive','full','change_pp'], swap)

    costs = []
    block = si.split('Supplementary Table 9.')[1].split('\\bottomrule')[0]
    for line in block.splitlines():
        cells = line.strip().rstrip('\\').split('&')
        if len(cells) == 6 and '/' in cells[1]:
            costs.append([x.strip().replace(',', '') for x in cells])
    assert len(costs) == 4
    export('costs.csv', ['condition','confirmed','token_n','mean_tokens','time_n','mean_seconds'], costs)
    manifest = {
        'source_files': {str(p.relative_to(WORK.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in [ARCHIVE/'DB_Curator_main.tex', ARCHIVE/'DB_Curator_SI.tex'] +
                         ([review] if review.exists() else []) +
                         ([benchmark_review] if benchmark_review.exists() else [])},
        'exported_tables': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.glob('*.csv')},
        'new_model_calls': 0,
    }
    (SOURCE/'MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return model, reasons, expert, repeats, swap, costs


def panel(f, col, row, labels, xmax, ticks, xlabel, letter, title):
    return g.axes(f, [.155 + col*.51, .724-row*.305, .295, .204],
                  labels, xmax, ticks, xlabel, letter, title)


def legend(ax, handles, ncol=2):
    ax.legend(handles=handles, loc='upper center', bbox_to_anchor=(.5, -.20),
              ncol=ncol, frameon=False, fontsize=6.9, handlelength=1.2,
              columnspacing=1.1, handletextpad=.4, borderaxespad=0)


def figure3(model, reasons, expert):
    f = g.figure(199)
    rows = {r['topic']: r for r in g.read('benchmark_final.csv')}
    a=panel(f,0,0,g.NAMES,80,[0,25,50,75],'Final Confirmed (%)','a','Benchmark decisions')
    b=panel(f,1,0,g.NAMES,123,[0,50,100],'Located citations (%)','b','Citation provenance')
    for i,t in enumerate(g.TOPICS):
        r=rows[t]; y=4-i
        for ax, num, den, mark in [(a,int(r['final_confirmed']),int(r['candidates']),'bar'),
                                   (b,int(r['verified_citations']),int(r['citation_instances']),'dot')]:
            v=100*num/den
            if mark=='bar': ax.barh(y,v,.46,color=g.BLUE)
            else:
                ax.hlines(y,0,v,color=g.PALE,lw=2)
                ax.plot(v,y,'o',color=g.BLUE,ms=4.8)
            g.label(ax,v+2,y+.13,f'{v:.1f}%',size=7,weight='bold')
            g.label(ax,v+2,y-.22,f'{num}/{den}',size=6.5,color=g.SLATE)
    c=panel(f,0,1,['Construction','Benchmark','Zero-shot'],105,[0,50,100],
            'Expert agreement (%)','c','Expert review')
    for y,r in zip([2,1,0], [expert[0], expert[2], expert[1]]):
        v=100*r[4]/r[1]
        c.barh(y,v,.45,color=g.BLUE if y else g.PALE)
        g.label(c,4,y,f'{r[4]:,}/{r[1]:,}  ({v:.1f}%)',size=7,color=g.INK)
    d=panel(f,1,1,g.NAMES,111,[0,50,100],'Supported packets (%)','d','Model evidence assessment')
    for y,r in zip(range(4,-1,-1),model):
        cv,gv=r[2:4]
        d.plot([cv,gv],[y,y],color=g.RULE,lw=1.6)
        d.plot(cv,y,'o',color=g.BLUE,ms=4.6)
        d.plot(gv,y,'s',mfc='white',mec=g.ROSE,ms=4.5)
        g.label(d,cv,y+.27,str(cv),size=7,ha='center',color='#42788A')
        g.label(d,gv,y-.27,str(gv),size=7,ha='center',color='#985D59')
    legend(d,[Line2D([],[],marker='o',ls='',color=g.BLUE,label='Claude'),
              Line2D([],[],marker='s',ls='',mfc='white',color=g.ROSE,label='GPT')])
    e=panel(f,0,2,g.NAMES,100,[0,50,100],'Packets per topic','e','Joint model assessment')
    for y,r in zip(range(4,-1,-1),model):
        left=0
        for v,col in zip([r[4],r[6],r[5]],[g.BLUE,'#DFCBA5',g.PALE]):
            e.barh(y,v,.5,left=left,color=col,edgecolor='white',linewidth=.6)
            if v>=8: g.label(e,left+v/2,y,str(v),size=7,ha='center')
            left+=v
        assert left==100
    legend(e,[Patch(color=g.BLUE,label='Both'),Patch(color='#DFCBA5',label='One'),Patch(color=g.PALE,label='Neither')],3)
    labels=['Direct evidence','Exact identity','Reaction role','Rubric meaning','Biological origin']
    z=panel(f,1,2,labels,125,[0,50,100],'Non-support judgments','f','Why support was withheld')
    for y,r in zip(range(4,-1,-1),reasons):
        z.barh(y,r[3],.45,color=g.ROSE)
        g.label(z,r[3]+2,y,str(r[3]),size=7)
    g.save(f,3)


def figure4(repeats, swap, costs):
    f=g.figure(199)
    a=panel(f,0,0,['Zero-shot','Frozen retrieval','Adaptive search','Full'],60,[0,25,50],
            'Confirmed-label yield (%)','a','Stages of evidence acquisition')
    counts=[317,475,645,671]
    aggregate = [r for r in g.read('repeated_contrasts.csv') if r['topic']=='all']
    assert sorted({int(r[k]) for r in aggregate for k in ['a_confirmed','b_confirmed']}) == counts
    for y,n,col in zip(range(3,-1,-1),counts,[g.SLATE,'#A4BDCA','#CDB78F',g.BLUE]):
        v=100*n/1500
        a.barh(y,v,.48,color=col)
        g.label(a,v+1,y,f'{v:.1f}% ({n})',size=7)
    b=panel(f,1,0,g.NAMES,36,[0,10,20,30],'Change (percentage points)','b','Where yield increases')
    contrasts={r['topic']:r for r in g.read('repeated_contrasts.csv') if r['contrast']=='Full-Dynamic'}
    static={r['topic']:r for r in g.read('repeated_contrasts.csv') if r['contrast']=='Full-Static'}
    for y,t in zip(range(4,-1,-1),g.TOPICS):
        full_gain=float(contrasts[t]['difference_pp'])
        adaptive_gain=float(static[t]['difference_pp'])-full_gain
        for yy,v,col in [(y+.15,adaptive_gain,'#CDB78F'),(y-.15,full_gain,g.BLUE)]:
            b.barh(yy,v,.23,color=col)
            g.label(b,v+.6,yy,f'+{v:.1f}',size=6.9)
    legend(b,[Patch(color='#CDB78F',label='Adaptive'),Patch(color=g.BLUE,label='Critique stage')])
    c=panel(f,0,1,g.NAMES,100,[0,25,50,75,100],'Full-system Confirmed (%)','c','Consistency across repeats')
    for y,r,col in zip(range(4,-1,-1),repeats,TOPIC_COLORS):
        c.hlines(y,r[5],r[6],color=col,lw=3)
        c.plot(r[4],y,'o',color=col,ms=5,mec='white',mew=.5)
        g.label(c,100,y,f'{r[7]}%',ha='right',size=7.5)
    c.text(1,1.015,'Same label',transform=c.transAxes,ha='right',fontsize=7)
    d=panel(f,1,1,g.NAMES,9,[0,3,6,9],'Adaptive-to-full change (pp)','d','Two Critique configurations')
    for i in range(5):
        y=4-i
        for j,col in [(0,g.BLUE),(1,g.ROSE)]:
            r=swap[2*i+j]; yy=y+.15 if j==0 else y-.15
            d.barh(yy,r[4],.23,color=col)
            g.label(d,r[4]+.15,yy,f'+{r[4]:.1f}',size=6.9)
    legend(d,[Patch(color=g.BLUE,label='GPT Critique'),Patch(color=g.ROSE,label='Gemini Critique')])
    e=panel(f,0,2,['Zero-shot','Frozen retrieval','Full'],6,[3,4,5],'Mean tokens per candidate','e','Token investment')
    # Log-axis positions prevent the smallest nonzero means disappearing.
    e.set(xlim=(2.3,6),xticks=[3,4,5],xticklabels=['1,000','10,000','100,000'])
    for y,r,col in zip([2,1,0],[costs[0],costs[1],costs[3]],[g.SLATE,'#A4BDCA',g.BLUE]):
        v=int(r[3]); x=np.log10(v)
        e.hlines(y,2.3,x,color=g.PALE,lw=2)
        e.plot(x,y,'o',color=col,ms=5)
        g.label(e,x+.08,y+.21,f'{v:,}',size=7)
    z=panel(f,1,2,['Frozen retrieval','Full'],350,[0,100,200,300],'Mean time per candidate (s)','f','Time to a decision')
    for y,r,col in zip([1,0],[costs[1],costs[3]],['#A4BDCA',g.BLUE]):
        v=float(r[5]); z.barh(y,v,.4,color=col)
        g.label(z,v+5,y,f'{v:.1f}',size=7.5)
    g.save(f,4)


if __name__=='__main__':
    model,reasons,expert,repeats,swap,costs=extract()
    figure3(model,reasons,expert)
    figure4(repeats,swap,costs)
    for ext in ['pdf', 'svg', 'png', 'tiff']:
        shutil.copyfile(ARCHIVE/'workshop_style'/f'Figure4.{ext}', g.OUT/f'Figure5.{ext}')
    (g.ROOT/'STORY_RENDER_QA.json').write_text(json.dumps(g.QA,indent=2)+'\n')
