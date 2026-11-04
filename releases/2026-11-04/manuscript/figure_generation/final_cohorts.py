"""Plot final fixed-cohort decisions alongside separately frozen repeated experiments."""
import hashlib
import json
import numpy as np
import generate as g


def figure2():
    rows = {r['topic']: r for r in g.read('construction_final.csv')}
    f = g.figure(132)
    a = g.axes(f, [.115,.585,.345,.325], g.NAMES, 810, [0,200,400,600], 'Candidates', 'a', 'Evaluated and released')
    b = g.axes(f, [.625,.585,.345,.325], g.NAMES, 119, [0,50,100], 'Encountered benchmark links retained (%)', 'b', 'Known-compound retention')
    c = g.axes(f, [.115,.145,.345,.325], g.NAMES, 118, [0,50,100], 'Benchmark-linked rows (%)', 'c', 'Benchmark linkage')
    d = g.axes(f, [.625,.145,.345,.325], g.NAMES, 119, [0,50,100], 'Located citation instances (%)', 'd', 'Citation provenance')
    for i, topic in enumerate(g.TOPICS):
        r = {k: int(v) for k,v in rows[topic].items() if k != 'topic'}
        y = 4-i
        n, ret = r['processed_candidates'], r['final_confirmed']
        a.barh(y+.14, n, .22, color=g.PALE)
        a.barh(y-.14, ret, .22, color=g.BLUE)
        g.label(a,n+10,y+.14,str(n))
        g.label(a,ret+10,y-.14,f'{ret}  ·  {n/ret:.2f}×',color='#42788A')
        num, den = r['released_benchmark_linked'], r['processed_benchmark_linked']
        val = 100*num/den
        b.hlines(y,0,val,color=g.PALE,lw=2.1)
        b.plot(val,y,'o',color=g.BLUE,ms=4.7,mec='white',mew=.5)
        g.label(b,val+2,y+.14,f'{val:.1f}%',color='#42788A',size=7.1,weight='bold')
        g.label(b,val+2,y-.20,f'{num}/{den}',color=g.SLATE,size=6.2)
        zs = r['zero_shot_benchmark_linked']
        cv, zv = 100*num/ret, 100*zs/200
        c.plot([zv,cv],[y-.045,y+.045],color=g.RULE,lw=1.2)
        c.plot(cv,y+.045,'o',color=g.BLUE,ms=4.6,mec='white',mew=.4)
        c.plot(zv,y-.045,'s',mfc='white',mec=g.SLATE,ms=4.3,mew=.8)
        g.label(c,cv,y+.26,f'{num}/{ret}',color='#42788A',ha='center')
        g.label(c,zv,y-.26,f'{zs}/200',color=g.SLATE,ha='center')
        yes, total = r['verified_citations'], r['citation_instances']
        v = 100*yes/total
        d.hlines(y,0,v,color=g.RULE,lw=1.6)
        d.plot(v,y,'o',color=g.BLUE,ms=4.7,mec='white',mew=.5)
        d.plot(0,y,'s',mfc='white',mec=g.SLATE,ms=4.3,mew=.8,clip_on=False)
        g.label(d,v+2,y+.13,f'{v:.1f}%',color='#42788A',size=7.1,weight='bold')
        g.label(d,v+2,y-.21,f'{yes}/{total}',color=g.SLATE,size=6.1)
        g.label(d,1,y-.26,f"0/{r['zero_shot_citations']}",color=g.SLATE,size=6.2)
    g.shared_methods(f)
    g.save(f,2)


def figure3():
    rows = {r['topic']: r for r in g.read('benchmark_final.csv')}
    rep = {r['contrast']: r for r in g.read('repeated_contrasts.csv') if r['topic']=='all'}
    f = g.figure(132)
    a = g.axes(f,[.115,.585,.345,.325],g.NAMES,80,[0,25,50,75],'Final Confirmed (%)','a','Benchmark decisions')
    b = g.axes(f,[.625,.585,.345,.325],g.NAMES,122,[0,50,100],'Located citation instances (%)','b','Citation provenance')
    for i,t in enumerate(g.TOPICS):
        r=rows[t]; y=4-i
        n, yes = int(r['candidates']), int(r['final_confirmed'])
        v = 100*yes/n
        a.barh(y,v,.44,color=g.BLUE)
        g.label(a,v+2,y+.13,f'{v:.1f}%',color='#42788A',weight='bold',size=7.1)
        g.label(a,v+2,y-.20,f'{yes}/{n}',color=g.SLATE,size=6.3)
        n, yes = int(r['citation_instances']), int(r['verified_citations'])
        v=100*yes/n
        b.hlines(y,0,v,color=g.PALE,lw=2)
        b.plot(v,y,'o',color=g.BLUE,ms=4.8,mec='white',mew=.5)
        g.label(b,v+2,y+.13,f'{v:.1f}%',color='#42788A',weight='bold',size=7.1)
        g.label(b,v+2,y-.20,f'{yes}/{n}',color=g.SLATE,size=6.3)
    c=g.axes(f,[.115,.145,.345,.325],['Zero-shot','Frozen retrieval','Adaptive search','Full'],60,[0,25,50],'Recorded Confirmed-label yield (%)','c','Repeated workflow ablation')
    counts=[317,475,645,671]
    assert sorted({int(r[k]) for r in rep.values() for k in ['a_confirmed','b_confirmed']}) == counts
    for y,n,col in zip([3,2,1,0],counts,[g.SLATE,'#A4BDCA','#CDB78F',g.BLUE]):
        v=100*n/1500
        c.barh(y,v,.48,color=col)
        g.label(c,v+1,y,f'{v:.1f}%  ({n})',size=6.5)
    d=g.axes(f,[.625,.145,.345,.325],['Full − adaptive','Full − frozen','Frozen − zero-shot'],20,[0,10,20],'Difference (percentage points)','d','Incremental recorded yield')
    d.axvline(0,color=g.RULE,lw=.7)
    for y,r in zip([2,1,0],rep.values()):
        v,lo,hi=[float(r[k]) for k in ['difference_pp','ci95_low_pp','ci95_high_pp']]
        d.errorbar(v,y,xerr=[[v-lo],[hi-v]],fmt='o',color=g.BLUE,ms=4.8,lw=1,capsize=2,capthick=.7)
        g.label(d,v,y+.29,f'+{v:.2f}',color='#42788A',size=7,ha='center')
    g.save(f,3)


if __name__ == '__main__':
    manifest=json.loads((g.DATA/'SOURCE_MANIFEST.json').read_text())
    for name in ('construction_final.csv','benchmark_final.csv','repeated_contrasts.csv'):
        assert hashlib.sha256((g.DATA/name).read_bytes()).hexdigest() == manifest[name]['sha256']
    figure2()
    figure3()
    (g.ROOT/'FINAL_RENDER_QA.json').write_text(json.dumps(g.QA,indent=2)+'\n')
