"""Compact manuscript figures drawn from frozen evaluation records."""
from pathlib import Path
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
import csv
import json
import hashlib
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.text import Text

plt.rcParams.update({
    'font.family': 'sans-serif', 'font.sans-serif': ['Liberation Sans', 'DejaVu Sans'],
    'font.size': 7.2, 'axes.titlesize': 8.2, 'axes.labelsize': 7.2,
    'xtick.labelsize': 6.7, 'ytick.labelsize': 7.2,
    'axes.linewidth': .5, 'axes.spines.top': False, 'axes.spines.right': False,
    'axes.edgecolor': '#9AA8B0', 'text.color': '#293B44',
    'axes.labelcolor': '#293B44', 'xtick.color': '#65757F', 'ytick.color': '#293B44',
    'svg.fonttype': 'none', 'pdf.fonttype': 42, 'savefig.facecolor': 'white',
})
ROOT = Path(__file__).resolve().parent
DATA = ROOT/'source_data'
OUT = ROOT/'figures'
OUT.mkdir(exist_ok=True)
BLUE = '#6497A8'
PALE = '#DAE7EB'
SLATE = '#7D8F9C'
MUTED_TEXT = '#5E737F'
ROSE = '#C68E89'
AMBER = '#BD945C'
INK = '#293B44'
RULE = '#DFE7EA'
TOPICS = ['dbp', 'blood_exposome', 'drug_compounds', 'human_endogenous_metabolites', 'microbial_natural_products']
NAMES = ['DBPs', 'Blood', 'Drugs', 'Endogenous', 'Microbial NP']
QA = []


def read(name):
    with (DATA/name).open(encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def figure(height):
    return plt.figure(figsize=(183/25.4, height/25.4), facecolor='white')


def axes(fig, pos, labels, xmax, ticks, xlabel, letter, title):
    ax = fig.add_axes(pos)
    ax.set(xlim=(0, xmax), ylim=(-.65, len(labels)-.35),
           yticks=np.arange(len(labels))[::-1], yticklabels=labels,
           xticks=ticks, xlabel=xlabel)
    ax.tick_params(axis='y', length=0, pad=5)
    ax.tick_params(axis='x', width=.5, length=2.5, pad=3)
    ax.spines['left'].set_visible(False)
    ax.set_title(title, loc='left', pad=11, fontweight='bold')
    ax.text(-.115, 1.085, letter, transform=ax.transAxes, fontsize=9, fontweight='bold')
    return ax


def label(ax, x, y, s, color=INK, size=6.5, **kwargs):
    return ax.text(x, y, s, color=MUTED_TEXT if color==SLATE else color, fontsize=size, va='center', clip_on=False, **kwargs)


def shared_methods(fig):
    handles = [Line2D([], [], marker='o', linestyle='', color=BLUE, markersize=4.5, label='DB-Curator'),
               Line2D([], [], marker='s', linestyle='', color=SLATE, markerfacecolor='white', markersize=4.5, label='Zero-shot')]
    fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(.55,.015), ncol=2,
               frameon=False, fontsize=7, handletextpad=.5, columnspacing=2.2)


def save(fig, n):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    texts = [t for t in fig.findobj(Text) if t.get_visible() and t.get_text()]
    outside = []
    overlaps = []
    boxes = []
    for t in texts:
        b = t.get_window_extent(renderer)
        if b.x0 < -.5 or b.y0 < -.5 or b.x1 > fig.bbox.width+.5 or b.y1 > fig.bbox.height+.5:
            outside.append(t.get_text())
        boxes.append(b)
    for i, b in enumerate(boxes):
        for j in range(i+1,len(boxes)):
            q = boxes[j]
            if min(b.x1,q.x1)-max(b.x0,q.x0)>1 and min(b.y1,q.y1)-max(b.y0,q.y0)>1:
                overlaps.append([texts[i].get_text(),texts[j].get_text()])
    for ext in ['pdf','svg','png','tiff']:
        kwargs = {'dpi':600 if ext=='tiff' else 300}
        if ext=='tiff': kwargs['pil_kwargs'] = {'compression':'tiff_lzw'}
        fig.savefig(OUT/f'Figure{n}.{ext}', **kwargs)
    QA.append({'figure':n,'size_mm':[round(v*25.4,1) for v in fig.get_size_inches()],
               'out_of_bounds_text':outside,'text_overlaps':overlaps,
               'visible_words':sum(len(t.get_text().split()) for t in texts)})
    plt.close(fig)


def figure2():
    rows = {r['topic']:r for r in read('construction.csv')}
    cit = {r['topic']:r for r in read('construction_citations.csv')}
    assert sum(int(r['processed_to_200']) for r in rows.values()) == 1743
    assert sum(int(r['confirmed_benchmark_overlap']) for r in rows.values()) == 673
    f = figure(132)
    a = axes(f,[.115,.585,.345,.325],NAMES,810,[0,200,400,600],'Candidates','a','Construction effort')
    b = axes(f,[.625,.585,.345,.325],NAMES,119,[0,50,100],'Processed-pool benchmark recall (%)','b','Benchmark recovery')
    c = axes(f,[.115,.145,.345,.325],NAMES,118,[0,50,100],'Benchmark overlap (%)','c','Benchmark overlap')
    d = axes(f,[.625,.145,.345,.325],NAMES,119,[0,50,100],'Source-locatable citations (%)','d','Citation provenance')
    for i, topic in enumerate(TOPICS):
        y = 4-i
        r = rows[topic]
        n,ret = int(r['processed_to_200']),int(r['selected_confirmed'])
        a.barh(y+.14,n,.22,color=PALE,edgecolor='none')
        a.barh(y-.14,ret,.22,color=BLUE,edgecolor='none')
        effort=(Decimal(n)/Decimal(ret)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        label(a,n+10,y+.14,str(n))
        label(a,ret+10,y-.14,f'{ret}  ·  {effort}×',color='#42788A')
        num,den=int(r['confirmed_benchmark_overlap']),int(r['processed_benchmark_overlap'])
        val=100*num/den
        b.hlines(y,0,val,color=PALE,lw=2.1)
        b.plot(val,y,'o',color=BLUE,ms=4.7,mec='white',mew=.5)
        label(b,val+2,y+.14,f'{val:.1f}%',color='#42788A',size=7.1,weight='bold')
        label(b,val+2,y-.20,f'{num}/{den}',color=SLATE,size=6.2)
        zs=int(r['zero_shot_benchmark_overlap'])
        cv,zv=100*num/200,100*zs/200
        c.plot([zv,cv],[y-.045,y+.045],color=RULE,lw=1.2,zorder=1)
        c.plot(cv,y+.045,'o',color=BLUE,ms=4.6,mec='white',mew=.4)
        c.plot(zv,y-.045,'s',mfc='white',mec=SLATE,ms=4.3,mew=.8)
        label(c,cv,y+.26,f'{num}/200',color='#42788A',size=6.4,ha='center')
        label(c,zv,y-.26,f'{zs}/200',color=SLATE,size=6.4,ha='center')
        q=cit[topic]
        yes,all_=int(q['dbcurator_source_locatable']),int(q['dbcurator_citations'])
        zero,total=int(q['zero_shot_source_locatable']),int(q['zero_shot_citations'])
        v,z=100*yes/all_,100*zero/total
        d.hlines(y,z,v,color=RULE,lw=1.6)
        d.plot(v,y,'o',color=BLUE,ms=4.7,mec='white',mew=.5)
        d.plot(z,y,'s',mfc='white',mec=SLATE,ms=4.3,mew=.8,clip_on=False)
        label(d,v+2,y+.13,f'{v:.1f}%',color='#42788A',size=7.1,weight='bold')
        label(d,v+2,y-.21,f'{yes}/{all_}',color=SLATE,size=6.1)
        label(d,1,y-.26,f'{zero}/{total}',color=SLATE,size=6.2)
    shared_methods(f)
    save(f,2)


def figure3():
    bench=read('benchmark_paired.csv')
    total=next(r for r in bench if r['topic']=='all')
    by={r['topic']:r for r in bench}
    rep={r['contrast']:r for r in read('repeated_contrasts.csv') if r['topic']=='all'}
    assert int(total['n'])==1887 and int(total['full'])==1015 and int(total['zero'])==375
    f=figure(132)
    a=axes(f,[.115,.585,.345,.325],NAMES,118,[0,50,100],'Confirmed-label yield (%)','a','Benchmark label yield')
    b=axes(f,[.625,.585,.345,.325],['Overall']+NAMES,85,[0,40,80],'Difference (percentage points)','b','Paired yield difference')
    for i,t in enumerate(TOPICS):
        r=by[t];y=4-i;n=int(r['n']);full=int(r['full']);zero=int(r['zero'])
        fv,zv=100*full/n,100*zero/n
        a.plot([zv,fv],[y-.04,y+.04],color=RULE,lw=1.2)
        a.plot(fv,y+.04,'o',color=BLUE,ms=4.8,mec='white',mew=.5)
        a.plot(zv,y-.04,'s',mfc='white',mec=SLATE,ms=4.3,mew=.8)
        label(a,fv,y+.26,f'{full}/{n}',color='#42788A',ha='center')
        label(a,zv,y-.26,f'{zero}/{n}',color=SLATE,ha='center')
    for i,r in enumerate([total]+[by[t] for t in TOPICS]):
        y=5-i;v,lo,hi=[float(r[k]) for k in ['difference_pp','ci_low_pp','ci_high_pp']]
        b.errorbar(v,y,xerr=[[v-lo],[hi-v]],fmt='o',color=BLUE,ms=4.6,lw=1,capsize=2,capthick=.7)
        label(b,hi+2,y,f'+{v:.1f}',color='#42788A',size=6.8)
    c=axes(f,[.115,.145,.345,.325],['Zero-shot','Frozen retrieval','Adaptive search','Full'],60,[0,25,50],'Confirmed-label yield (%)','c','Workflow ablation')
    counts=[317,475,645,671]
    assert sorted({int(r[k]) for r in rep.values() for k in ['a_confirmed','b_confirmed']})==counts
    for y,n,col in zip([3,2,1,0],counts,[SLATE,'#A4BDCA','#CDB78F',BLUE]):
        v=100*n/1500;c.barh(y,v,.48,color=col,edgecolor='none')
        label(c,v+1,y,f'{v:.1f}%  ({n})',size=6.5)
    labels=['Full − adaptive','Full − frozen','Frozen − zero-shot']
    rows=list(rep.values())
    assert [int(r['a_confirmed'])-int(r['b_confirmed']) for r in rows]==[26,196,158]
    d=axes(f,[.625,.145,.345,.325],labels,20,[0,10,20],'Difference (percentage points)','d','Incremental yield')
    d.axvline(0,color=RULE,lw=.7)
    for y,r in zip([2,1,0],rows):
        v,lo,hi=[float(r[k]) for k in ['difference_pp','ci95_low_pp','ci95_high_pp']]
        d.errorbar(v,y,xerr=[[v-lo],[hi-v]],fmt='o',color=BLUE,ms=4.8,lw=1,capsize=2,capthick=.7)
        label(d,v,y+.29,f'+{v:.2f}',color='#42788A',size=7,ha='center')
    shared_methods(f)
    save(f,3)


def figure4():
    data=read('criterion_indicators.csv')
    f=figure(174)
    short=[
        ['Direct treatment attribution','Disinfectant–precursor reaction','Disinfection or oxidation','Specific chemical'],
        ['Blood / systemic circulation','Human blood specimen','Endogenous / exogenous allowed','Literature or dataset support'],
        ['Drug modality*','Formulation exclusion','Pharmacological effect','Specific drug entity'],
        ['Host / microbiota allowed','Human production','Human biochemical function','Small molecule'],
        ['Analytical evidence','Unambiguous structure','Non-secondary exclusion','Specific chemical'],
    ]
    for j,t in enumerate(TOPICS):
        rows=[r for r in data if r['topic']==t]
        bottom=.815-j*.168
        ax=f.add_axes([.35,bottom,.59,.11])
        ax.set(xlim=(-3,124),ylim=(-.5,3.5),yticks=[3,2,1,0],
               yticklabels=[f"{lab}  [{r['gate_type']}]" for lab,r in zip(short[j],rows)],xticks=[0,50,100])
        ax.tick_params(axis='y',length=0,pad=6,labelsize=7.1)
        ax.spines['left'].set_visible(False)
        ax.spines['bottom'].set_visible(j==4)
        ax.tick_params(axis='x',bottom=j==4,labelbottom=j==4,length=2.5,width=.5)
        for v in [0,50,100]:ax.axvline(v,color=RULE,lw=.6,zorder=0)
        f.text(.035,bottom+.135,chr(97+j),fontsize=9,fontweight='bold')
        f.text(.067,bottom+.135,NAMES[j],fontsize=8.3,fontweight='bold')
        for i,r in enumerate(rows):
            y=3-i;co=float(r['pass_rate_confirmed'])*100;ot=float(r['pass_rate_other'])*100
            ax.plot([ot,co],[y-.05,y+.05],color='#CFDCE1',lw=1.15)
            ax.plot(co,y+.05,'o',color=BLUE,ms=4.6,mec='white',mew=.4)
            ax.plot(ot,y-.05,'D',mfc='white',mec=ROSE,ms=4,mew=.9)
            label(ax,119,y,f'{co-ot:+.1f}',size=7,ha='right')
        if j==4:ax.set_xlabel('Recorded criterion indicator (%)',labelpad=6)
    f.text(.904,.973,'Δ (pp)',fontsize=7,ha='right',color=SLATE)
    handles=[Line2D([],[],marker='o',ls='',color=BLUE,label='Confirmed',ms=4.5),
             Line2D([],[],marker='D',ls='',color=ROSE,mfc='white',label='Other outcomes',ms=4)]
    f.legend(handles=handles,loc='lower center',bbox_to_anchor=(.55,.025),ncol=2,frameon=False,fontsize=7)
    save(f,4)


def figure5():
    records=read('transitions.csv');counts=Counter((r['observable_category'],r['direction']) for r in records)
    assert len(records)==44 and len({r['candidate_id'] for r in records})==42
    case=next(r for r in records if r['transition_id']=='4_dbp_47')
    states=[r for r in read('criterion_changes.csv') if r['transition_id']=='4_dbp_47']
    assert case['pre_label']=='Suspected' and case['post_label']=='Confirmed'
    assert [r['pre_status'] for r in states]==['solved']*4+['unsolved']
    assert [r['post_status'] for r in states]==['solved']*5
    f=figure(124)
    a=axes(f,[.235,.605,.235,.29],['New citation','Existing source','Unchanged','Incomplete'],35,[0,15,30],'Label transitions','a','Evidence changes')
    # Position this panel title above the full label-and-data region.
    a.set_title('',loc='left')
    for tx in a.texts:
        if tx.get_text()=='a':tx.set_visible(False)
    f.text(.035,.945,'a',fontsize=9,weight='bold');f.text(.065,.945,'Evidence changes',fontsize=8.3,weight='bold')
    keys=['new_cited_source_in_saved_report','existing_sources_passages_or_assessments_changed','label_change_without_new_source_or_assessment_change','unknown_incomplete_pre_payload']
    for y,k in zip([3,2,1,0],keys):
        up,down=counts[k,'up'],counts[k,'down']
        a.barh(y,up,.48,color=BLUE);a.barh(y,down,.48,left=up,color=ROSE)
        label(a,up+down+1,y,str(up+down),size=7)
        for left,n in [(0,up),(up,down)]:
            if n>=4:label(a,left+n/2,y,str(n),size=6.6,color=INK,ha='center')
    a.legend(handles=[Line2D([],[],color=BLUE,lw=5,label='To Confirmed'),Line2D([],[],color=ROSE,lw=5,label='From Confirmed')],
             loc='upper center',bbox_to_anchor=(.25,-.25),ncol=2,frameon=False,fontsize=6.6,handlelength=1.1,columnspacing=1.3)
    g=f.add_axes([0,0,1,1],frameon=False);g.set(xlim=(0,1),ylim=(0,1));g.axis('off')
    def txt(x,y,s,size=7.2,color=INK,ha='left',weight='normal'):
        g.text(x,y,s,fontsize=size,color=MUTED_TEXT if color==SLATE else color,ha=ha,va='center',weight=weight)
    def box(x,y,w,h,s,color='#F0F5F6',ink=INK):
        g.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0,rounding_size=.009',fc=color,ec='none'))
        txt(x+w/2,y+h/2,s,7.2,ink,'center')
    def arrow(x1,x2,y):
        g.add_patch(FancyArrowPatch((x1,y),(x2,y),arrowstyle='-|>',mutation_scale=8,color=SLATE,lw=.8))
    txt(.55,.945,'b',9,weight='bold');txt(.58,.945,'2-Chloro-2-iodoacetonitrile',8.2,weight='bold')
    txt(.845,.874,'Suspected',7,AMBER,'center');txt(.948,.874,'Confirmed',7,BLUE,'center')
    terms=['Specific compound','Water treatment','Precursor reaction','Water matrix','Direct formation attribution']
    for i,(term,row) in enumerate(zip(terms,states)):
        y=.818-i*.051
        if i==4:
            g.add_patch(FancyBboxPatch((.55,y-.023),.427,.046,boxstyle='round,pad=0,rounding_size=.005',fc='#FAF4EA',ec='none'))
        txt(.56,y,term,7.05,AMBER if i==4 else INK)
        for x,status in [(.845,row['pre_status']),(.948,row['post_status'])]:
            g.plot(x,y,'o',ms=4.7,mfc=BLUE if status=='solved' else 'white',mec=BLUE if status=='solved' else AMBER,mew=.9)
        if i==4:arrow(.867,.925,y)
    g.plot(.67,.54,'o',ms=4.6,color=BLUE);txt(.685,.54,'Resolved',6.8)
    g.plot(.83,.54,'o',ms=4.6,mfc='white',mec=AMBER);txt(.845,.54,'Unresolved',6.8)
    g.plot([.035,.977],[.45,.45],color=RULE,lw=.65)
    txt(.035,.403,'c',9,weight='bold');txt(.065,.403,'Cinatrin A',8.3,weight='bold')
    txt(.1325,.354,'Raw baseline',6.9,SLATE,'center');txt(.3675,.354,'Saved baseline',6.9,SLATE,'center')
    box(.035,.224,.195,.092,'Confirmed','#EDF4F3',BLUE)
    box(.27,.224,.195,.092,'Insufficient\nevidence','#FAF4EA',AMBER)
    arrow(.233,.267,.27);txt(.25,.18,'JSON parsing error',7,SLATE,'center')
    txt(.55,.403,'d',9,weight='bold');txt(.58,.403,'Chloroacetaldehyde',8.3,weight='bold')
    for x,s in [(.55,'Identity\nlookup'),(.705,'Paper\nclaims'),(.86,'Critique\napproval')]:box(x,.224,.12,.092,s)
    arrow(.675,.70,.27);arrow(.83,.855,.27)
    txt(.765,.18,'No observed paper retrieval',7.3,'#A36D68','center')
    save(f,5)


if __name__=='__main__':
    manifest=json.loads((DATA/'SOURCE_MANIFEST.json').read_text())
    for name,record in manifest.items():
        assert hashlib.sha256((DATA/name).read_bytes()).hexdigest()==record['sha256'],name
    for fn in [figure2,figure3,figure4,figure5]: fn()
    (ROOT/'RENDER_QA.json').write_text(json.dumps(QA,indent=2)+'\n')
    print(json.dumps(QA,indent=2))
