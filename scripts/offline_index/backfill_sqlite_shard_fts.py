#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import time

import apsw


def main() -> None:
    ap = argparse.ArgumentParser(description='Backfill SQLite FTS for shard databases from documents table.')
    ap.add_argument('--db-path', required=True)
    ap.add_argument('--replace', action='store_true')
    ap.add_argument('--optimize', action='store_true')
    args = ap.parse_args()

    db_path = pathlib.Path(args.db_path)
    conn = apsw.Connection(str(db_path))
    cur = conn.cursor()

    start = time.time()
    docs = next(cur.execute('select count(*) from documents'))[0]
    try:
        fts_before = next(cur.execute('select count(*) from documents_fts'))[0]
    except Exception:
        fts_before = -1

    print(f'db={db_path}')
    print(f'documents={docs}')
    print(f'fts_before={fts_before}')

    cur.execute('PRAGMA journal_mode=WAL')
    cur.execute('PRAGMA synchronous=NORMAL')
    cur.execute('PRAGMA temp_store=MEMORY')
    cur.execute('PRAGMA cache_size=-200000')

    if args.replace:
        cur.execute('DELETE FROM documents_fts')

    if args.replace or fts_before != docs:
        cur.execute(
            """
            INSERT INTO documents_fts(doc_id, title, abstract, identifiers)
            SELECT doc_id,
                   coalesce(title, ''),
                   coalesce(abstract, ''),
                   trim(
                       coalesce(doi, '') || ' ' ||
                       coalesce(pmid, '') || ' ' ||
                       coalesce(pmcid, '') || ' ' ||
                       coalesce(doc_id, '')
                   )
            FROM documents
            """
        )

    if args.optimize:
        cur.execute("INSERT INTO documents_fts(documents_fts) VALUES('optimize')")

    fts_after = next(cur.execute('select count(*) from documents_fts'))[0]
    elapsed = time.time() - start
    print(f'fts_after={fts_after}')
    print(f'elapsed_s={elapsed:.2f}')


if __name__ == '__main__':
    main()
