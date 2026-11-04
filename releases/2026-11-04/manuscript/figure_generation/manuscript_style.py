"""Story-aligned visual production from frozen manuscript data; no inference calls."""
import argparse
import hashlib
import json
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans', 'Liberation Sans']
plt.rcParams['svg.fonttype'] = 'none'
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm, to_rgb
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

import nature_figures as g
import nature_figures_v2 as previous

ROOT, DATA, STORY = g.ROOT, g.DATA, g.STORY
TOPICS, NAMES = g.TOPICS, g.NAMES
TOPIC = ['#719FB9', '#CB977D', '#78A79C', '#B8A267', '#AE91B1']
ZERO, FROZEN, ADAPT, FULL = '#BDC4CA', '#C9B49A', '#9BBFBA', '#578D9D'
ROSE, INK, GREY, GRID = '#B97876', '#263640', '#59666E', '#E5EAEC'
STAGES = ['Zero-shot', 'Frozen retrieval', 'Adaptive search', 'Full']
PALETTE = [ZERO, FROZEN, ADAPT, FULL]
VALUES = {}


def tint(color, strength=.15):
    return tuple(1-strength*(1-v) for v in to_rgb(color))


def style():
    plt.rcParams.update({'font.size': 7, 'axes.labelsize': 7, 'xtick.labelsize': 6.7,
        'ytick.labelsize': 7, 'axes.linewidth': .5, 'axes.labelcolor': INK,
        'axes.edgecolor': GREY, 'xtick.color': GREY, 'ytick.color': INK,
        'text.color': INK, 'pdf.fonttype': 42, 'axes.labelpad': 3,
        'legend.frameon': False, 'legend.fontsize': 7, 'savefig.facecolor': 'white'})


class Canvas(g.Canvas):
    def panel(self, x, y, letter, title):
        self.text(x, y, letter, fontsize=9, fontweight='bold', color=INK)
        self.text(x+5, y, title, fontsize=8, fontweight='bold', color=INK)


def rows(ax, xmax=100, labels=NAMES, ticks=(0, 50, 100), xlabel=None):
    ax.set(xlim=(0, xmax), ylim=(len(labels)-.4, -.6), yticks=range(len(labels)),
           xticks=ticks, xlabel=xlabel)
    ax.set_yticklabels(labels)
    ax.spines['left'].set_visible(False)
    ax.tick_params(axis='y', length=0, pad=3)
    ax.tick_params(axis='x', length=2)
    ax.grid(axis='x', color=GRID, lw=.5)
    ax.set_axisbelow(True)
    return ax


def value(ax, x, y, text, **kw):
    return ax.text(x, y, text, transform=ax.get_yaxis_transform(), va='center',
                   ha=kw.pop('ha', 'left'), fontsize=kw.pop('fontsize', 7),
                   color=kw.pop('color', INK), clip_on=False, **kw)


def horizontal_legend(canvas, y, labels, colors, markers):
    handles = [Line2D([], [], ls='', marker=m, markersize=4.5,
                     markerfacecolor='white' if m in ('s', 'D') else col,
                     markeredgecolor=col, label=label)
               for label, col, m in zip(labels, colors, markers)]
    canvas.fig.legend(handles=handles, loc='center',
                      bbox_to_anchor=(.53, 1-y/canvas.h), ncol=len(labels),
                      handletextpad=.45, columnspacing=2.2)


def figure2():
    data = {r['topic']: {k:int(v) for k,v in r.items() if k!='topic'}
            for r in g.read(DATA/'construction_final.csv')}
    processed = sum(r['processed_candidates'] for r in data.values())
    retained = sum(r['final_confirmed'] for r in data.values())
    c = Canvas(135)
    for x,y,l,title in [(2,6,'a',f'From {processed:,} records to {retained:,} rows'),
                        (96,6,'b','Retention of known compounds'),
                        (2,73,'c','Benchmark overlap'),
                        (96,73,'d','Citation provenance')]:
        c.panel(x,y,l,title)
    a = rows(c.ax(25,17,42,41), 750, ticks=(0,250,500,750), xlabel='Candidate records')
    c.text(71,13,'Processed / retained', fontsize=6.4, ha='center', color=GREY)
    for i,t in enumerate(TOPICS):
        r=data[t]
        a.barh(i,r['processed_candidates'],.50,color=tint(TOPIC[i],.24),lw=0)
        a.barh(i,r['final_confirmed'],.22,color=TOPIC[i],lw=0)
        value(a,1.08,i,f"{r['processed_candidates']} / {r['final_confirmed']}",fontsize=6.8)
    b = rows(c.ax(104,17,46,41),labels=['']*5,xlabel='Retained known identities (%)')
    c.text(155,13,'Retained / seen',fontsize=6.4,color=GREY)
    for i,t in enumerate(TOPICS):
        r=data[t]; n,d=r['released_benchmark_linked'],r['processed_benchmark_linked']; v=100*n/d
        b.barh(i,100,.5,color=tint(TOPIC[i],.09),lw=0)
        b.barh(i,v,.5,color=tint(TOPIC[i],.60),lw=0)
        b.plot(v,i,'o',color=TOPIC[i],ms=4)
        b.text(4,i,f'{v:.1f}%',va='center',fontsize=7,fontweight='bold')
        value(b,1.09,i,f'{n}/{d}',fontsize=6.8)
    cc = rows(c.ax(25,84,42,36),xlabel='Benchmark-matched rows (%)')
    c.text(72,80,'DB / zero-shot',ha='center',fontsize=6.4,color=GREY)
    for i,t in enumerate(TOPICS):
        r=data[t]; db=r['released_benchmark_linked']; z=r['zero_shot_benchmark_linked']
        cc.plot([db/2,z/2],[i,i],color=tint(TOPIC[i],.65),lw=1.3)
        cc.plot(z/2,i-.08,'s',mfc='white',mec=GREY,ms=4,mew=.8)
        cc.plot(db/2,i+.08,'o',color=TOPIC[i],ms=4.4,mec='white',mew=.4)
        value(cc,1.08,i,f'{db} / {z}',fontsize=6.8)
    d = c.ax(101,87,71,26)
    d.set(xlim=(0,100),ylim=(-.55,1.55),xticks=[0,50,100],yticks=[],
          xlabel='Source-located paper citations (%)')
    for s in ('left','right','top'): d.spines[s].set_visible(False)
    d.grid(axis='x',color=GRID,lw=.5);d.set_axisbelow(True)
    totals = {k:sum(r[k] for r in data.values()) for k in next(iter(data.values()))}
    for y,label,n,den,col in [(1,'DB-Curator retained rows',totals['verified_citations'],totals['citation_instances'],FULL),
                             (0,'Zero-shot proposals',totals['zero_shot_verified'],totals['zero_shot_citations'],ZERO)]:
        d.barh(y,100,.24,color=tint(col,.15),lw=0)
        d.barh(y,100*n/den,.24,color=col,lw=0)
        d.text(0,y+.30,label,fontsize=7,va='bottom')
        d.text(100,y+.30,f'{n:,}/{den:,}',ha='right',va='bottom',fontsize=7,fontweight='bold')
        if n==0: d.plot(0,y,'s',ms=4,mfc='white',mec=GREY,clip_on=False)
    horizontal_legend(c,132,['DB-Curator','Zero-shot'],[FULL,GREY],['o','s'])
    VALUES['Figure2']=data
    g.save(c,'Figure2')


def figure3():
    bench={r['topic']:r for r in g.read(DATA/'benchmark_final.csv')}
    experts={r['cohort']:r for r in g.read(STORY/'expert_review.csv')}
    review=json.loads((ROOT.parent/'source_data/human_comment_recheck/color_review_summary_20261029.json').read_text())['cohorts']
    c=Canvas(132)
    c.panel(2,6,'a','Benchmark decisions')
    c.panel(96,6,'b','Expert agreement')
    c.panel(2,73,'c','Construction review by topic')
    a=rows(c.ax(25,17,42,41),60,ticks=(0,20,40,60),xlabel='Final Confirmed (%)')
    c.text(71,13,'Confirmed / input',fontsize=6.4,ha='center',color=GREY)
    for i,t in enumerate(TOPICS):
        r=bench[t];n,d=int(r['final_confirmed']),int(r['candidates']);v=100*n/d
        a.barh(i,v,.43,color=tint(TOPIC[i],.7),lw=0)
        a.plot(v,i,'o',color=TOPIC[i],ms=4)
        a.text(2,i,f'{v:.1f}%',va='center',fontsize=6.7)
        value(a,1.08,i,f'{n}/{d}',fontsize=6.8)
    b=c.ax(101,18,71,38)
    b.set(xlim=(0,100),ylim=(-.55,2.75),xticks=[0,50,100],yticks=[],xlabel='Agreement (%)')
    b.spines['left'].set_visible(False);b.grid(axis='x',color=GRID,lw=.5);b.set_axisbelow(True)
    for i,(key,label,col) in enumerate([
            ('DB-Curator construction','DB-Curator construction',FULL),
            ('Benchmark verification','Benchmark decisions',ADAPT),
            ('Zero-shot construction','Zero-shot construction',ZERO)]):
        y=2-i;r=experts[key];n,d=int(r['agreement']),int(r['n']);v=100*n/d
        b.barh(y,100,.27,color=tint(col,.15),lw=0)
        b.barh(y,v,.27,color=col,lw=0)
        b.text(0,y+.26,label,fontsize=6.7,va='bottom')
        b.text(100,y+.26,f'{v:.1f}%  ({n:,}/{d:,})',ha='right',va='bottom',fontsize=6.4)
    cc=rows(c.ax(25,84,109,33),102,ticks=(85,90,95,100),xlabel='Reviewer agreement (%)')
    cc.set_xlim(85,102)
    c.text(143,80,'DB-Curator / zero-shot',fontsize=6.5,color=GREY)
    for i,t in enumerate(TOPICS):
        rc=review['construction_250_labeled_version']['topics'][t]
        rz=review['zero_shot_250']['topics'][t]
        cv,zv=100*rc['agreement']/rc['n'],100*rz['agreement']/rz['n']
        cc.plot([cv,zv],[i,i],color=tint(TOPIC[i],.7),lw=1.4)
        cc.plot(zv,i-.08,'s',mfc='white',mec=GREY,ms=4.4)
        cc.plot(cv,i+.08,'o',color=TOPIC[i],ms=4.8,mec='white',mew=.4)
        value(cc,1.07,i,f"{rc['agreement']}/50   /   {rz['agreement']}/50")
    horizontal_legend(c,129,['DB-Curator','Zero-shot'],[FULL,GREY],['o','s'])
    VALUES['Figure3']={'benchmark':bench,'expert':experts,'topic_review':review}
    g.save(c,'Figure3')


def figure4():
    rep=g.read(STORY/'repeats.csv');swap=g.read(STORY/'model_swap.csv')
    paired=g.read(DATA/'repeated_contrasts.csv')
    costs={r['condition']:r for r in g.read(STORY/'costs.csv')}
    counts=[int(costs[key]['confirmed'].split('/')[0]) for key in
            ('Zero-shot','Static RAG','Adaptive search','Full DB-Curator')]
    assert counts==[317,475,645,671]
    c=Canvas(169)
    for x,y,l,title in [(2,6,'a','Confirmation across stages'),(96,6,'b','Stage gains by topic'),
                        (2,65,'c','Repeat consistency'),(96,65,'d','Critique configurations'),
                        (2,127,'e','Yield and computation')]: c.panel(x,y,l,title)
    a=rows(c.ax(27,16,42,36),50,labels=['Zero-shot','Frozen retrieval','Adaptive search','Full'],
           ticks=(0,25,50),xlabel='Confirmed (%)')
    c.text(72,12,'Count / 1,500',fontsize=6.4,color=GREY)
    for i,(n,col) in enumerate(zip(counts,PALETTE)):
        a.barh(i,n/15,.46,color=col,lw=0)
        a.text(1.5,i,f'{n/15:.1f}%',va='center',fontsize=7)
        value(a,1.08,i,str(n),fontweight='bold')
    hm=c.ax(116,17,55,35)
    mat=[]
    for t in TOPICS:
        d={r['contrast']:float(r['difference_pp']) for r in paired if r['topic']==t}
        mat.append([d['Static-Zero'],d['Full-Static']-d['Full-Dynamic'],d['Full-Dynamic']])
    mat=np.asarray(mat)
    cm=LinearSegmentedColormap.from_list('soft_delta',[ROSE,'#FAFAF9',FULL])
    hm.imshow(mat,cmap=cm,norm=TwoSlopeNorm(0,-15,45),aspect='auto')
    hm.set(xticks=range(3),yticks=range(5));hm.set_yticklabels(NAMES)
    hm.set_xticklabels(['Zero →\nfrozen','Frozen →\nadaptive','Adaptive →\nfull'],fontsize=6.4)
    hm.xaxis.tick_top();hm.tick_params(length=0,pad=3)
    for s in hm.spines.values():s.set_visible(False)
    for i in range(5):
        for j in range(3):
            hm.text(j,i,f'{mat[i,j]:+.1f}',ha='center',va='center',fontsize=7.2,
                    color='white' if mat[i,j]>33 else INK)
        hm.axhline(i+.5,color='white',lw=1.3)
    for j in range(2):hm.axvline(j+.5,color='white',lw=1.3)
    c.text(143,57,'Change in percentage points',fontsize=6.5,ha='center',color=GREY)
    cc=rows(c.ax(25,77,42,35),80,ticks=(0,40,80),xlabel='Full Confirmed (%)')
    c.text(73,73,'Same label',fontsize=6.4,color=GREY)
    for i,r in enumerate(rep):
        lo,hi,m=int(r['min']),int(r['max']),float(r['full'])
        cc.plot([lo,hi],[i,i],color=tint(TOPIC[i],.65),lw=4,solid_capstyle='round')
        cc.plot(m,i,'o',color=TOPIC[i],mec='white',mew=.6,ms=4.8)
        value(cc,1.14,i,f"{r['agreement']}%",fontweight='bold')
    d=rows(c.ax(116,77,55,35),9,labels=NAMES,ticks=(0,3,6,9),xlabel='Adaptive to Full (pp)')
    for i in range(5):
        a0,b0=float(swap[2*i]['change_pp']),float(swap[2*i+1]['change_pp'])
        d.plot([a0,b0],[i,i],color=tint(TOPIC[i],.65),lw=1.3)
        d.plot(a0,i+.08,'o',color=TOPIC[i],ms=4.4)
        d.plot(b0,i-.08,'s',mfc='white',mec=TOPIC[i],ms=4.4)
    d.legend(handles=[Line2D([],[],marker='o',ls='',color=GREY,label='GPT-5-mini'),
                      Line2D([],[],marker='s',ls='',mfc='white',color=GREY,label='Gemini 2.5 Flash')],
             loc='lower center',bbox_to_anchor=(.43,1.03),ncol=2,fontsize=6.3,
             handletextpad=.25,columnspacing=.7)
    e=c.ax(18,136,92,24)
    e.set_xscale('log');e.set(xlim=(200,700000),ylim=(0,60),xticks=[1e3,1e4,1e5],
                            yticks=[0,20,40,60],xlabel='Mean tokens per candidate',ylabel='Confirmed (%)')
    e.minorticks_off();e.grid(axis='y',color=GRID,lw=.5);e.set_axisbelow(True)
    points=[]
    for key,i in [('Zero-shot',0),('Static RAG',1),('Full DB-Curator',3)]:
        r=costs[key];x=int(r['mean_tokens']);y=counts[i]/15
        e.scatter(x,y,s=30,color=PALETTE[i],edgecolor=INK,lw=.4,zorder=3)
        e.annotate(['Zero-shot','Frozen',None,'Full'][i],(x,y),xytext=(0,7),
                   textcoords='offset points',ha='center',fontsize=6.7)
        points.append([x,y])
    e.plot(*zip(*points),color=GRID,lw=.8,zorder=1)
    tab=c.ax(121,134,55,27);tab.axis('off');tab.set(xlim=(0,55),ylim=(0,27))
    tab.text(0,25,'Setting',fontsize=6.5,color=GREY)
    tab.text(34,25,'Tokens',fontsize=6.5,color=GREY,ha='right')
    tab.text(54,25,'Time (s)',fontsize=6.5,color=GREY,ha='right')
    for y,key,label in [(17,'Zero-shot','Zero-shot'),(10,'Static RAG','Frozen'),(3,'Full DB-Curator','Full')]:
        r=costs[key];sec=r['mean_seconds']
        tab.text(0,y,label,fontsize=6.7)
        tab.text(34,y,f"{int(r['mean_tokens']):,}",ha='right',fontsize=6.7)
        tab.text(54,y,'n/a' if sec=='--' else f'{float(sec):.1f}',ha='right',fontsize=6.7)
    VALUES['Figure4']={'counts':counts,'topic_differences':mat.tolist(),'repeats':rep,'model_swap':swap,'costs':costs}
    g.save(c,'Figure4')


def figure5():
    data=g.read(DATA/'criterion_indicators.csv')
    names=[['Direct treatment attribution','Disinfectant–precursor reaction','Disinfection or oxidation','Specific chemical'],
           ['Blood / systemic circulation','Human blood specimen','Endogenous / exogenous allowed','Literature or dataset support'],
           ['Drug modality*','Formulation exclusion','Pharmacological effect','Specific drug entity'],
           ['Host / microbiota allowed','Human production','Human biochemical function','Small molecule'],
           ['Analytical evidence','Unambiguous structure','Non-secondary exclusion','Specific chemical']]
    full=['Disinfection by-products','Blood exposome','Drugs','Endogenous metabolites','Microbial natural products']
    c=Canvas(162)
    ax=c.ax(73,10,72,137)
    ax.set(xlim=(-2,102),ylim=(27.9,-.6),xticks=[0,25,50,75,100],yticks=[],
           xlabel='Criterion indicator (%)')
    ax.spines['left'].set_visible(False);ax.grid(axis='x',color=GRID,lw=.5);ax.set_axisbelow(True)
    value(ax,1.15,-.85,'Difference',fontsize=6.4,color=GREY)
    vals=[]
    for j,t in enumerate(TOPICS):
        subset=[r for r in data if r['topic']==t];assert len(subset)==4
        h=j*5.6
        ax.text(-99,h,chr(97+j),va='center',fontsize=9,fontweight='bold',clip_on=False)
        ax.text(-91,h,full[j],va='center',fontsize=7.4,fontweight='bold',color=INK,clip_on=False)
        nco,notr=int(float(subset[0]['rows_confirmed'])),int(float(subset[0]['rows_other']))
        value(ax,1.15,h,f'{nco}/{notr}',fontsize=6.3,color=GREY)
        for k,(r,name) in enumerate(zip(subset,names[j])):
            y=h+k+1.1;co,ot=100*float(r['pass_rate_confirmed']),100*float(r['pass_rate_other']);dv=co-ot
            ax.text(-9,y,name,ha='right',va='center',fontsize=6.7,clip_on=False)
            ax.text(-5,y,r['gate_type'],ha='center',va='center',fontsize=6.3,color=INK,
                    bbox={'boxstyle':'round,pad=.20','fc':tint(TOPIC[j],.2),'ec':'none'},clip_on=False)
            ax.plot([ot,co],[y,y],color='#B7C8C9',lw=1.2)
            ax.plot(ot,y,'D',mfc='white',mec=ROSE,ms=4,mew=.9)
            ax.plot(co,y,'o',color=FULL,ms=4.4,mec='white',mew=.4)
            value(ax,1.15,y,f'{dv:+.1f} pp',fontsize=6.7)
            vals.append({'topic':t,'criterion':r['criterion'],'role':r['gate_type'],
                         'confirmed_indicator':co,'other_indicator':ot,'difference_pp':dv})
        ax.plot([-100,143],[h+4.75,h+4.75],color=tint(TOPIC[j],.35),lw=.5,clip_on=False)
    horizontal_legend(c,159,['Confirmed','Other outcomes'],[FULL,ROSE],['o','D'])
    VALUES['Figure5']=vals
    g.save(c,'Figure5')


def case_specs():
    cases={r['candidate']:r for r in json.loads(previous.CASES.read_text())}
    def anchors(name,stage):
        return [a for ins in cases[name]['inspections'] for a in ins['source_anchors'] if a['stage']==stage]
    hb=next(k for k in cases if 'Hydroxybenzene' in k)
    iso='Isoterrelumamide A';pc=next(k for k in cases if k.startswith('PC('))
    entries=[
        (hb,'4-Hydroxyphthalic acid','Disinfection by-products','Organic precursor',
         ['nine nonhalogenated aromatic compounds were identified as new intermediate DBPs in chlorination, including','4-hydroxyphthalic acid'],
         ['demonstrating that they somewhat acted as intermediates between NOM and halogenated aromatic DBPs.'],
         'Chlorination formation is shown. Find the link to an organic precursor.',
         'Same source: precursor link made explicit',FULL),
        (iso,iso,'Microbial natural products','Secondary-metabolite status',
         ['isoterrelumamide A (2)','The structures of the new compounds were established by 1D and 2D NMR spectroscopic analysis as well as by HRESIMS.'],
         ['Isoterrelumamide A (67)','the secondary metabolites detected are not always the same'],
         'Fungal isolation and structure are shown. Find secondary-metabolite evidence.',
         'Added source: classification made explicit',FULL),
        (pc,'PC(20:2(11Z,14Z)/20:1(11Z))','Endogenous metabolites','Exact molecular species',
         ['Eighteen metabolites associated with GPL metabolism were identified','PC (20:3(8Z,11Z,14Z)/20:1(11Z))'],
         ['The Kennedy pathway represents the primary route for phosphatidylcholine (PC) biosynthesis'],
         'Target: PC(20:2/20:1). Cited: PC(20:3/20:1). Find the exact lipid species.',
         'Class-level synthesis: target still unresolved',ROSE)]
    spec=[]
    for key,title,domain,criterion,p0,p1,request,outcome,color in entries:
        assert cases[key]['canonical_final_label']=='Confirmed' and cases[key]['canonical_accepted']
        a0=anchors(key,'initial_report')[0];a1=anchors(key,'response')[1]
        assert a0['location_status']==a1['location_status']=='exact'
        spec.append(dict(candidate=key,title=title,domain=domain,criterion=criterion,
            quote0=previous.excerpt(a0['quote'],*p0),quote1=previous.excerpt(a1['quote'],*p1),
            identifier0=a0['supplied_identifier'],identifier1=a1['supplied_identifier'],
            request=request,outcome=outcome,color=color,initial_label='Confirmed',
            critique_label=cases[key]['critique_label'],final_label='Confirmed',accepted=True))
    return spec


def figure6():
    spec=case_specs();c=Canvas(146)
    for x,label in [(4,'Initial report: Confirmed'),(69,'Critique request'),(117,'Revised evidence')]:
        c.text(x,5,label,fontsize=7.4,fontweight='bold')
    for i,r in enumerate(spec):
        y=11+i*44
        c.panel(2,y,chr(97+i),r['title'])
        c.text(178,y,r['domain'],ha='right',fontsize=6.5,color=GREY)
        c.text(7,y+5,'Criterion: '+r['criterion'],fontsize=6.7,color=r['color'])
        review_label = 'IDE' if r['critique_label']=='Insufficient Direct Evidence' else r['critique_label']
        c.text(69,y+5,'Review: '+review_label,fontsize=6.5,color='#917745')
        c.text(178,y+5,'Final label: Confirmed',fontsize=6.5,ha='right',color=GREY)
        ax=c.ax(2,y+8,176,32);ax.set(xlim=(0,176),ylim=(0,32));ax.axis('off')
        for x,w,body,ident,col in [(0,60,r['quote0'],r['identifier0'],FULL),
                                 (65,43,r['request'],None,'#B89C65'),
                                 (113,63,r['quote1'],r['identifier1'],r['color'])]:
            ax.add_patch(FancyBboxPatch((x,0),w,32,boxstyle='round,pad=0,rounding_size=1.2',
                                        fc=tint(col,.09),ec=tint(col,.27),lw=.5))
            ax.add_patch(Rectangle((x,0),.7,32,fc=col,ec='none'))
            text='“'+body+'”' if ident else body
            ax.text(x+2.5,29.5,textwrap.fill(text,width=50 if w>50 else 33),va='top',
                    fontsize=6.7,linespacing=1.35,style='italic' if ident else 'normal')
            if ident:
                prefix='doi: ' if ident.startswith('10.') else 'PMID: '
                ax.text(x+2.5,9 if x>100 else 3,prefix+ident,fontsize=5.8,color=GREY)
            if x>100:
                ax.text(x+2.5,3,r['outcome'],fontsize=6.2,color=col,fontweight='bold')
        for x0,x1 in [(60.8,64.2),(108.8,112.2)]:
            ax.add_patch(FancyArrowPatch((x0,16),(x1,16),arrowstyle='-|>',mutation_scale=6,color=GREY,lw=.7))
    VALUES['Figure6']=spec
    g.save(c,'Figure6')


def accumulation():
    data=g.read(DATA/'construction_accumulation.csv')
    c=Canvas(105);ax=c.ax(18,7,155,77)
    for t,name,col in zip(TOPICS,NAMES,TOPIC):
        rs=[r for r in data if r['topic']==t]
        x=[0]+[int(r['processed_records']) for r in rs]
        y=[0]+[int(r['retained_rows']) for r in rs]
        assert y[-1]==200 and all(a<=b for a,b in zip(y,y[1:]))
        ax.step(x,y,where='post',lw=1.4,color=col,label=name)
        ax.plot(x[-1],200,'o',ms=4,color=col)
    ax.set(xlim=(0,730),ylim=(0,215),xticks=range(0,701,100),yticks=[0,50,100,150,200],
           xlabel='Processed candidate records',ylabel='Final retained entries')
    ax.grid(axis='y',color=GRID,lw=.5);ax.set_axisbelow(True)
    ax.axhline(200,color=GREY,lw=.6,ls='--')
    c.fig.legend(*ax.get_legend_handles_labels(),loc='lower center',bbox_to_anchor=(.53,.01),
                 ncol=5,fontsize=7,handlelength=1.8,columnspacing=1.3)
    VALUES['SupplementaryFigure2']=data
    g.save(c,'SupplementaryFigure2')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT.parent/'figures/nature')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    paths=[DATA/p for p in ['construction_final.csv','benchmark_final.csv',
                           'criterion_indicators.csv','repeated_contrasts.csv','construction_accumulation.csv']]
    paths += list(STORY.glob('*.csv'))+[previous.CASES,ROOT.parent/'source_data/human_comment_recheck/color_review_summary_20261029.json']
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    before={str(p.relative_to(ROOT.parent)):sha(p) for p in paths}
    style();g.OUT=args.output;g.QA.clear()
    for fn in [figure2,figure3,figure4,figure5,figure6,accumulation]:fn()
    assert before=={str(p.relative_to(ROOT.parent)):sha(p) for p in paths},'Source data changed'
    (args.output/'PLOTTED_VALUES.json').write_text(json.dumps(VALUES,indent=2)+'\n')
    manifest={'input_hashes':before,'script_sha256':sha(Path(__file__)),
              'figures':g.QA,'figure1_unchanged':True,'new_model_calls':0,
              'outputs':{p.name:sha(p) for p in args.output.iterdir() if p.suffix in ['.pdf','.svg','.png','.tiff']}}
    (args.output/'STYLE_QA.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for q in g.QA:print(q)


if __name__=='__main__':main()
