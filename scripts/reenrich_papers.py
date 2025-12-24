#!/usr/bin/env python3
import sys, json, logging
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent / 'code'))
from searching_tool import FullTextJournalSearchTool

logging.basicConfig(level=logging.INFO, format='%(levelname)-8s | %(message)s')
log = logging.getLogger(__name__)

session_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
paper_files = [f for f in session_dir.glob("*.json") if f.stem not in ['index', 'agent_summary', 'end_to_end_summary', 'batch_summary']]

papers_to_enrich = []
for pf in paper_files:
    with open(pf) as f:
        p = json.load(f)
    if not p.get('has_fulltext', False):
        papers_to_enrich.append((pf, p))

log.info(f"Found {len(papers_to_enrich)} papers without full text out of {len(paper_files)} total")

tool = FullTextJournalSearchTool(results_base_dir=str(session_dir.parent))
tool._current_run_assets_dir = session_dir

enriched = 0
for pf, p in papers_to_enrich:
    title = p.get('title', '')[:50]
    log.info(f"Processing: {title}...")
    enriched_p = tool._phase1_enrich_one(p)
    if enriched_p.get('has_fulltext'):
        log.info(f"  ✅ SUCCESS: {len(enriched_p.get('full_text', ''))} chars")
        with open(pf, 'w') as f:
            json.dump(enriched_p, f, indent=2)
        enriched += 1
    else:
        log.info(f"  ❌ FAILED")

log.info(f"\nRe-enriched {enriched}/{len(papers_to_enrich)} papers")
