"""Offline checks for the published Researcher prediction endpoint."""
import csv
import json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'source_data/researcher_endpoint_20261102'
FIG=ROOT/'figure_generation/source_data'


def read(p):
    with p.open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))


def main():
    bench=read(ROOT/'source_data/benchmark_consolidated_20261104/benchmark_all1887.csv')
    assert len(bench)==len({r['case_id'] for r in bench})==1887
    assert sum(r['researcher_label']=='Confirmed' for r in bench)==975
    assert sum(r['current_label']=='Confirmed' for r in bench)==669
    by_id={r['case_id']:r for r in bench}
    for r in read(FIG/'benchmark_operational_current.csv'):
        assert r['final_label']==by_id[r['case_id']]['researcher_label']
        assert r['saved_system_label']==by_id[r['case_id']]['current_label']
    for r in read(FIG/'benchmark_labels.csv'):
        assert json.loads(r['final_label_counts'])==Counter(x['researcher_label'] for x in bench if x['topic']==r['topic'])
    criteria=read(FIG/'criterion_count_rows.csv')
    assert len(criteria)==1887
    for r in criteria:assert r['scientific_label']==by_id[r['row_index']]['researcher_label']
    primary=read(SRC/'repeated_full_all1500.csv')
    alternate=read(SRC/'model_swap_gemini_all1500.csv')
    assert len(primary)==len(alternate)==1500
    assert sum(r['researcher_label']=='Confirmed' for r in primary)==673
    assert sum(r['researcher_label']=='Confirmed' for r in alternate)==647
    for r in read(FIG/'story_panels/model_swap.csv'):
        if r['critic']=='Gemini 2.5 Flash':
            names={'DBP':'dbp','Blood exposome':'blood_exposome','Drug':'drug_compounds',
                   'Endogenous metabolite':'human_endogenous_metabolites','Microbial natural product':'microbial_natural_products'}
            n=sum(x['researcher_label']=='Confirmed' for x in alternate if x['topic']==names[r['topic']])
            assert abs(float(r['full'])-n/3)<1e-9
    construction=read(SRC/'construction_all2122.csv')
    assert sum(r['retained']=='True' for r in construction)==1000
    assert sum(r['researcher_label']=='Confirmed' for r in construction)==1284
    assert sum(r['retained']=='True' and r['researcher_label']=='Confirmed' for r in construction)==999
    feedback=read(SRC/'feedback_all300.csv')
    assert [sum(r['researcher_label']=='Confirmed' for r in feedback if r['arm']==a) for a in 'ABC']==[58,48,51]
    positive=[r for r in bench if r['researcher_label']=='Confirmed']
    assert sum(int(r['paper_citations']) for r in positive)==4169
    assert sum(int(r['verified_citations']) for r in positive)==3964
    print('PASS: endpoint labels, release separation, plot grouping, model swap and citation counts.')


if __name__=='__main__':main()
