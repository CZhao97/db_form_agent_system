#!/usr/bin/env python3
import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent.parent
CODE_DIR = BASE_DIR / 'code'
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from searching_tool import FullTextJournalSearchTool
from offline_retrieval_config import default_offline_search_kwargs


def load_queries(args: argparse.Namespace) -> List[str]:
    queries: List[str] = []
    if args.query:
        queries.extend([q.strip() for q in args.query if q.strip()])
    if args.queries_file:
        with open(args.queries_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    queries.append(line)
    deduped: List[str] = []
    seen = set()
    for q in queries:
        key = q.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(q)
    if not deduped:
        raise SystemExit('No queries provided. Use --query or --queries-file.')
    return deduped


def make_tool(enable_vector: bool) -> FullTextJournalSearchTool:
    kwargs = default_offline_search_kwargs()
    kwargs['enable_offline_vector_search'] = enable_vector
    return FullTextJournalSearchTool(
        include_online_search=False,
        include_pubmed=False,
        include_preprints=False,
        include_s2=False,
        include_arxiv=False,
        include_medrxiv=False,
        include_chemrxiv=False,
        include_eupmc=False,
        include_offline_search=True,
        **kwargs,
    )


def summarize_hits(hits: List[Dict[str, Any]], top_k: int) -> Dict[str, Any]:
    top = []
    for rank, hit in enumerate(hits[:top_k], start=1):
        top.append({
            'rank': rank,
            'doc_id': hit.get('offline_doc_id') or '',
            'title': hit.get('title') or '',
            'sources': hit.get('_rrf_sources') or [],
            'pmcid': ((hit.get('ids') or {}).get('pmcid') or ''),
        })
    return {
        'count': len(hits),
        'top_hits': top,
        'titles': [item['title'] for item in top],
        'doc_ids': [item['doc_id'] for item in top],
    }


def compare_query(query: str, lexical_tool: FullTextJournalSearchTool, hybrid_tool: FullTextJournalSearchTool, k: int, top_k: int) -> Dict[str, Any]:
    lexical_hits = lexical_tool._search_offline_doc_db(query, k)
    hybrid_hits = hybrid_tool._search_offline_doc_db(query, k)

    lexical_summary = summarize_hits(lexical_hits, top_k)
    hybrid_summary = summarize_hits(hybrid_hits, top_k)

    lexical_docs = set(lexical_summary['doc_ids'])
    hybrid_docs = set(hybrid_summary['doc_ids'])
    only_hybrid = [d for d in hybrid_summary['doc_ids'] if d and d not in lexical_docs]
    only_lexical = [d for d in lexical_summary['doc_ids'] if d and d not in hybrid_docs]

    return {
        'query': query,
        'lexical': lexical_summary,
        'hybrid': hybrid_summary,
        'overlap_topk': len(lexical_docs & hybrid_docs),
        'hybrid_gain_topk': len(only_hybrid),
        'lexical_only_topk': len(only_lexical),
        'hybrid_only_doc_ids': only_hybrid,
        'lexical_only_doc_ids': only_lexical,
    }


def write_csv(rows: List[Dict[str, Any]], output_csv: Path) -> None:
    fieldnames = [
        'query',
        'lexical_count',
        'hybrid_count',
        'overlap_topk',
        'hybrid_gain_topk',
        'lexical_only_topk',
        'lexical_top1',
        'hybrid_top1',
    ]
    with output_csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                'query': row['query'],
                'lexical_count': row['lexical']['count'],
                'hybrid_count': row['hybrid']['count'],
                'overlap_topk': row['overlap_topk'],
                'hybrid_gain_topk': row['hybrid_gain_topk'],
                'lexical_only_topk': row['lexical_only_topk'],
                'lexical_top1': row['lexical']['titles'][0] if row['lexical']['titles'] else '',
                'hybrid_top1': row['hybrid']['titles'][0] if row['hybrid']['titles'] else '',
            })


def main() -> None:
    ap = argparse.ArgumentParser(description='Compare offline lexical-only vs lexical+vector retrieval.')
    ap.add_argument('--query', action='append', help='Query to compare. Repeatable.')
    ap.add_argument('--queries-file', help='Text file with one query per line.')
    ap.add_argument('--k', type=int, default=10, help='Top-k documents to retrieve per mode.')
    ap.add_argument('--top-k-summary', type=int, default=5, help='Top-k hits to include in the detailed summary.')
    ap.add_argument('--output-json', default='offline_retrieval_mode_comparison.json', help='Detailed JSON output path.')
    ap.add_argument('--output-csv', default='offline_retrieval_mode_comparison.csv', help='Compact CSV output path.')
    args = ap.parse_args()

    queries = load_queries(args)
    lexical_tool = make_tool(enable_vector=False)
    hybrid_tool = make_tool(enable_vector=True)

    rows = []
    for idx, query in enumerate(queries, start=1):
        print(f'[{idx}/{len(queries)}] Comparing: {query}')
        rows.append(compare_query(query, lexical_tool, hybrid_tool, args.k, args.top_k_summary))

    output_json = Path(args.output_json)
    output_csv = Path(args.output_csv)
    output_json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
    write_csv(rows, output_csv)

    print(f'Wrote JSON: {output_json}')
    print(f'Wrote CSV:  {output_csv}')


if __name__ == '__main__':
    main()
