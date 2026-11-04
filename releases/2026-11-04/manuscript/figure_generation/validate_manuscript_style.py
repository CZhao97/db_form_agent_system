"""Offline checks for the style-only manuscript revision."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

import fitz


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def table(path):
    with path.open(encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--revision',type=Path,required=True)
    args=p.parse_args()
    root=Path(__file__).resolve().parent
    work=root.parent
    rendered=args.revision/'rendered'
    before=args.revision/'before'
    qa=read(rendered/'STYLE_QA.json')
    values=read(rendered/'PLOTTED_VALUES.json')
    assert sha(root/'manuscript_style.py')==qa['script_sha256']
    for rel,digest in qa['input_hashes'].items():
        assert sha(work/rel)==digest,rel
        frozen=before/rel
        if frozen.exists():assert sha(frozen)==digest,rel
    for q in qa['figures']:
        assert not q['text_overlaps'] and not q['out_of_bounds_text'],q['figure']
        for ext in ['pdf','svg','png','tiff']:
            name=q['figure']+'.'+ext
            assert sha(rendered/name)==qa['outputs'][name]
            assert sha(work/'figures/nature'/name)==qa['outputs'][name]
        svg=(rendered/(q['figure']+'.svg')).read_text()
        assert '<text ' in svg,'SVG text not editable'
        with fitz.open(rendered/(q['figure']+'.pdf')) as pdf:
            assert len(pdf)==1
            assert abs(pdf[0].rect.width*25.4/72-180)<.01
            assert pdf[0].get_text().strip()
    for row in table(root/'source_data/construction_final.csv'):
        actual=values['Figure2'][row['topic']]
        assert actual=={k:int(v) for k,v in row.items() if k!='topic'}
    assert sum(v['final_confirmed'] for v in values['Figure2'].values())==1000
    assert sum(v['citation_instances'] for v in values['Figure2'].values())==7689
    for row in table(root/'source_data/benchmark_final.csv'):
        assert values['Figure3']['benchmark'][row['topic']]==row
    assert values['Figure4']['counts']==[317,475,645,671]
    for row,shown in zip(table(root/'source_data/criterion_indicators.csv'),values['Figure5']):
        assert row['topic']==shown['topic'] and row['criterion']==shown['criterion']
        assert abs(100*float(row['pass_rate_confirmed'])-shown['confirmed_indicator'])<1e-9
        assert abs(100*float(row['pass_rate_other'])-shown['other_indicator'])<1e-9
    source={r['candidate']:r for r in read(work/'source_data/final_confirmed_evidence_inspection/all_11_inspections.json')}
    for shown in values['Figure6']:
        src=source[shown['candidate']]
        assert src['canonical_final_label']==shown['final_label']
        assert src['canonical_accepted']==shown['accepted']
        assert src['critique_label']==shown['critique_label']
        for n,stage in [(0,'initial_report'),(1,'response')]:
            anchors=[a for ins in src['inspections'] for a in ins['source_anchors']
                     if a['stage']==stage and a['supplied_identifier']==shown[f'identifier{n}']]
            assert anchors
            fragments=[x.strip() for x in shown[f'quote{n}'].split('\u2026') if x.strip()]
            assert any(all(s in a['quote'] for s in fragments) for a in anchors)
    caption=re.compile(r'\\textbf\{Figure [1-6] .*?(?=\n\n)',re.S)
    old=(before/'DB_Curator_main.tex').read_text()
    new=(work/'DB_Curator_main.tex').read_text()
    assert caption.sub('',old)==caption.sub('',new),'Non-caption manuscript text changed'
    assert sha(before/'DB_Curator_SI.tex')==sha(work/'DB_Curator_SI.tex')
    output={'status':'pass','source_data_unchanged':True,'caption_only_prose_edits':True,
            'new_model_calls':0,'plots':qa['figures'],'documents':{}}
    for stem in ['DB_Curator_main','DB_Curator_SI']:
        log=(work/(stem+'.log')).read_text()
        assert not re.search(r'Overfull|Undefined control sequence|Missing character|^!|undefined references',log,re.M)
        doc=fitz.open(work/(stem+'.pdf'))
        output['documents'][stem]={'pages':len(doc),'pdf_sha256':sha(work/(stem+'.pdf')),
                                  'tex_sha256':sha(work/(stem+'.tex'))}
        if stem=='DB_Curator_main':
            old_doc=fitz.open(before/(stem+'.pdf'))
            select=lambda d:next(p for p in d if 'Figure 1 |' in p.get_text())
            assert select(doc).get_pixmap().samples==select(old_doc).get_pixmap().samples,'Figure 1 changed'
            output['figure1_page_unchanged']=True
        for i,page in enumerate(doc):
            if any('Figure '+str(n)+' |' in page.get_text() for n in range(2,7)):
                page.get_pixmap(matrix=fitz.Matrix(1.25,1.25)).save(args.revision/f'{stem}_p{i+1}.png')
    (args.revision/'VALIDATION.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output,indent=2))


if __name__=='__main__':main()
