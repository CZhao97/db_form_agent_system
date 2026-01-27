#!/usr/bin/env python3
"""
Quick test to demonstrate the offline search issue with phrase queries.
"""
import sys
sys.path.insert(0, 'code')
from searching_tool import FullTextJournalSearchTool

# Initialize offline-only tool
tool = FullTextJournalSearchTool(
    include_offline_search=True,
    include_pubmed=False,
    include_eupmc=False,
    include_s2=False,
    include_arxiv=False,
    include_medrxiv=False,
    offline_index_path='/data/chen/GNPS_SIM/pmc_lancedb_index'
)

print("="*70)
print("OFFLINE SEARCH TEST: 4-Bromophenol")
print("="*70)

# Test 1: Phrase query (quoted) - FAILS due to index limitation
print("\n1. PHRASE QUERY (with quotes):")
print("   Query: '\"4-Bromophenol\" AND \"disinfection\"'")
result1 = tool._run('"4-Bromophenol" AND "disinfection"', max_results=10)
print(f"   {result1}")

# Test 2: Simple query (no quotes) - SHOULD WORK
print("\n2. SIMPLE QUERY (no quotes):")
print("   Query: '4-Bromophenol disinfection'")
result2 = tool._run('4-Bromophenol disinfection', max_results=10)
print(f"   {result2}")

# Test 3: Single term - SHOULD WORK
print("\n3. SINGLE TERM:")
print("   Query: '4-Bromophenol'")
result3 = tool._run('4-Bromophenol', max_results=10)
print(f"   {result3}")

print("\n" + "="*70)
print("SUMMARY:")
print("- Phrase queries (quoted terms) fail due to FTS index missing 'position' data")
print("- Simple queries (no quotes) work correctly")
print("- Solution: Use unquoted queries OR rebuild FTS index with position=True")
print("="*70)
