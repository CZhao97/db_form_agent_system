# Quality Analysis: Unquoted Query Performance

## Test Results for 4-Bromophenol DBP Evaluation

### Papers Retrieved: 680 total

#### Quality Breakdown
| Category | Count | Percentage |
|---|---|---|
| **Specific to 4-Bromophenol** | 4 | 0.6% |
| **General DBP/Brominated** | 173 | 25.4% |
| **Off-topic** | 503 | **74.0%** |

### Sample 4-Bromophenol Specific Papers Found
1. Ion-exchange-resin-catalyzed adamantylation of phenol derivatives
2. Derivatization-free method for compound-specific isotope analysis
3. Oxidation of 4-bromophenol by recombinant fused protein
4. Near-UV photolysis of substituted phenols (4-fluoro-, 4-chloro-, 4-bromo-)

### Assessment

**Precision: LOW (0.6% exact match, 26% related)**
- Unquoted queries create high recall but very low precision
- FTS without position data treats words independently
- Many papers match "disinfection" OR "byproduct" but not together

**Issues Identified:**
1. Too many off-topic ozonation studies
2. General brominated compound papers (not specific to 4-BP)
3. Unrelated chemistry papers with incidental keyword matches

### Recommendations

#### Option 1: Rebuild FTS Index (Best Quality)
**Pros:** Enables phrase queries, much better precision
**Cons:** Time-intensive (~hours for 266M rows)
**Impact:** Could reduce off-topic from 74% → 20-30%

#### Option 2: Improve Query Strategy
**Pros:** Quick to implement
**Cons:** Limited improvement without phrase search
**Suggestions:**
- Add compound identifiers (CAS: 106-41-2)
- Use negative filters
- Strengthen reranking

#### Option 3: Accept Current Quality
**Pros:** Works now
**Cons:** Wastes tokens, agent processing time
**Mitigation:** Rely on Cross-Encoder reranking + agent filtering

### Conclusion
Current approach retrieves papers successfully but with **74% noise**.
For production, **rebuilding FTS index with position=True** is strongly recommended.
