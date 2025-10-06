#!/usr/bin/env python3
"""
Simple test runner for FullTextJournalSearchTool.
Creates a run under searching_results/ and prints saved file paths and bioRxiv-specific fields.
"""
import sys
import json
import pathlib

sys.path.append('code')
from searching_agent import FullTextJournalSearchTool


def main():
    tool = FullTextJournalSearchTool()
    print('Running focused test (script)')
    res = tool._run(query='machine learning', max_results=2)
    print('Saved files count:', len(res))
    latest = list(pathlib.Path('searching_results').glob('run_*'))
    latest = sorted([d for d in latest if d.is_dir()])[-1]
    print('Latest run:', latest)
    for pfile in res:
        print('\nFILE:', pfile)
        try:
            with open(pfile, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except Exception as e:
            print(' Failed to read', pfile, e)
            continue
        print(' source:', data.get('source'))
        print(' title:', (data.get('title') or '')[:120])
        if data.get('source','').lower() == 'biorxiv':
            print('  pdf_url:', data.get('pdf_url'))
            print('  pdf_path:', data.get('pdf_path'))
            print('  download_failed:', data.get('download_failed'))
            print('  download_attempts:', data.get('download_attempts'))
            print('  html_path:', data.get('html_path'))
            print('  has_fulltext:', data.get('has_fulltext'))
            print('  sections len:', len(data.get('sections', [])))
            if data.get('html_path'):
                print('  html exists:', pathlib.Path(data.get('html_path')).exists())


if __name__ == '__main__':
    main()
