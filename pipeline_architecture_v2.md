# MAS Pipeline: Detailed Technical Specification

**Version**: 2.0 (Optimized with Hybrid Search & Cross-Encoder)
**Date**: 2025-12-30
**System**: Chemical Database Formation Agent
**User**: `chen`

---

## 1. System Overview

This system is a **Multi-Agent System (MAS)** designed to autonomously extract verified chemical knowledge from scientific literature. It transitions from a vague user request to a structured, evidence-backed dataset (`end_to_end_summary.json`).

### High-Level Architecture
```mermaid
graph TD
    User[User Input] --> Refinement[Refinement Agent]
    Refinement -->|Refined Definition| Discovery[Upper-Stream Agent]
    
    subgraph "Phase 1: Discovery (Searching & NER)"
        Discovery -->|Query| HybridSearch[Hybrid Search Tool]
        HybridSearch -->|Parallel| Online[PubMed/EuropePMC API]
        HybridSearch -->|Parallel| Offline[LanceDB (1.1TB)]
        Online --> Rerank[Cross-Encoder Reranker]
        Offline --> Rerank
        Rerank -->|Top 500 Papers| NER[Chemical NER (HunFlair2)]
        NER -->|JSON| Clustering[Clustering Node]
    end
    
    Clustering -->|Top Chemicals| QueryGen[Query Generation Node]
    QueryGen -->|Questions| Swarm[Downstream Agent Swarm]
    
    subgraph "Phase 2: Verification (The Swarm)"
        Swarm -->|Wait| LitAgent[Literature Agent]
        LitAgent -->|Search & Read| Evidence[Evidence Extraction]
        Evidence --> Critique[Critique Agent]
        Critique -->|Loop| LitAgent
        Critique -->|Approved| Verdict[Final Verdict]
    end
    
    Verdict --> Aggregation[End-to-End Summary]
```

---

## 2. Phase 1: Initialization & Refinement
**Objective**: Convert natural language intent into a strict scientific definition.

### 2.1. Refinement Node
*   **Source**: `notebooks/e2e_agent.py` (`refinement_node`)
*   **Input**: User Query (e.g., "Find DBPs").
*   **Logic**:
    *   Uses `refinement_agent` (LLM) to identify ambiguity.
    *   Drafts a `refined_definition`.
    *   **Interactive Mode**: Prompts user for approval via `human_feedback_node`.
    *   **Batch Mode**: Auto-approves meaningful definitions.
*   **Output State**: `state['refined_definition']` string.

---

## 3. Phase 2: Upper-Stream Discovery
**Objective**: Recall high-relevance papers and identifying chemical entities.

### 3.1. Hybrid Search Tool (`FullTextJournalSearchTool`)
*   **Source**: `code/searching_tool.py`
*   **Strategy**: Parallel retrieval from Online APIs and Offline Vector DB.

#### A. Online Search
*   **Sources**: PubMed, EuropePMC, ArXiv, Unpaywall.
*   **Execution**: `ThreadPoolExecutor` (fan-out query to all sources).
*   **Optimizations**:
    *   Rate limiting handling (exponential backoff).
    *   Lazy loading of PDFs (only fetches full text if metadata matches).

#### B. Offline Index (LanceDB)
*   **Path**: `/data/chen/GNPS_SIM/pmc_lancedb_index`
*   **Size**: 1.1 TB, ~266 Million Vectors.
*   **Model**: `sentence-transformers/all-MiniLM-L6-v2` (384-d vectors).
*   **Tool**: `code/offline_paper_tool.py` / `_search_offline_db` in `searching_tool.py`.
*   **Logic**:
    1.  **Vector Search**: Finds semantically similar papers (`tbl.search(query)`).
    2.  **Deduplication**: Checks if `doc_id` or Title exists in Online set.
    3.  **Priority**: Offline hits are kept over Online hits (faster access).

#### C. Smart Reranking (Cross-Encoder)
*   **Logic**: The "recall" phase returns ~1000 noisy candidates. Reranking filters them.
*   **Model**: `cross-encoder/ms-marco-MiniLM-L-6-v2`.
*   **Process**:
    1.  Pairs `(Query, Paper_Title + Paper_Abstract)` are formed.
    2.  Model predicts a `_relevance_score` (logit).
    3.  List is sorted by `Score (Desc)` -> `Date (Desc)`.
*   **Global Cap**: `GLOBAL_MAX_CAP = 500`. The list is truncated *after* reranking to ensure only the best 500 are processed.

### 3.2. Chemical NER Tool (`ChemicalNerTool`)
*   **Source**: `code/chemical_ner_tool.py`
*   **Model**: `hunflair2` (State-of-the-Art Biomedical NER).
*   **Hardware**: Runs on local GPU (CUDA).
*   **Batching**:
    *   Processes papers in batches (e.g., 320 at a time).
    *   Uses `lancedb` to check if NER results are already cached (skipping GPU inference).
*   **Linking**: Maps text mentions to **MeSH UIDs** where possible.
*   **Output**: A list of JSONs, each containing:
    *   `unique_mentions`: List of chemical names found.
    *   `full_text`: The text processed.

---

## 4. Phase 3: Middle Layer (Query Generation)
**Objective**: Aggregating raw names into testable hypotheses.

### 4.1. Clustering & Sampling
*   **Source**: `notebooks/e2e_agent.py`
*   **Logic**:
    *   Raw list of chemical names from all 500 papers is flattened.
    *   Names are clustered (string similarity) to merge synonyms (e.g., "TCM" == "Chloroform").
    *   **Sampling**: The top N (default 30-100) most frequent chemicals are selected.

### 4.2. Query Generation Node
*   **Prompt**: `prompts/query_generator_agent.md`
*   **Action**: For each chemical, the LLM generates a **Verification Question**.
*   **Format**: *"Is [Chemical] a confirmed [Topic] according to [Definition]?"*
*   **Output**: `generated_queries.json`.

---

## 5. Phase 4: Downstream Verification (The "Swarm")
**Objective**: Validating each hypothesis with rigorous evidence.

*   **Execution**: `LangGraph` subgraph runs in parallel batches.

### 5.1. Literature Agent (`literature_agent.md`)
*   **Role**: The "Researcher".
*   **Tools**:
    *   `CompoundDatabaseTool`: Resolves chemical names/IDs.
    *   `OfflinePaperSearchTool`: Checks local DB first.
    *   `FullTextJournalSearchTool`: Checks online if local fails.
*   **Logic (Hybrid Query Expansion)**:
    1.  **Resolve**: Calls `CompoundDatabaseTool` for formal synonyms (CAS, IUPAC).
    2.  **Brainstorm**: Uses LLM knowledge for abbreviations/slang (e.g., "TBBQ").
    3.  **Search**: Executes hybrid search (Offline semantic + Online boolean) using the combined synonym set.
    4.  **Extract**: Reads full-text and extracts quotes.

### 5.2. Critique Agent (`critique_agent.md`)
*   **Role**: The "Reviewer".
*   **Logic**:
    1.  Reviews the `LiteratureAgent`'s findings.
    2.  Checks against the strict `refined_definition`.
    3.  **Reject**: If evidence is weak or circumstantial ("It might be...").
    4.  **Approve**: If evidence is explicit ("We observed formation of...").
*   **Loop**: If rejected, the Literature Agent searches again (up to `max_iterations`).

---

## 6. Phase 5: Output Aggregation
**Objective**: Finalizing the knowledge base.

*   **File**: `end_to_end_summary.json`
*   **Location**: `searching_results/e2e_run_YYYYMMDD_HHMMSS/`
*   **Content**:
    *   Map of `Chemical Name` -> `Result Object`.
    *   Includes `verdict` (Confirmed/Rejected/Uncertain), `confidence` (0.0-1.0), and `evidence` (list of DOIs/Claims).

## 7. Configuration & Optimization Notes

### Key Parameters (in `e2e_agent.py` & `searching_tool.py`)
*   `GLOBAL_MAX_CAP`: **500** (Max papers to NER).
*   `ner_batch_size`: **320** (for high-end GPU).
*   `offline_index_path`: `/data/chen/GNPS_SIM/pmc_lancedb_index` (1.1TB DB).
*   `llm_model`: `gpt-4o` (or similar high-reasoning model).

### Critical Optimizations
1.  **Offline First**: Saves network time and API quotas.
2.  **Cross-Encoder**: Ensures 500 *relevant* papers beat 500 *random* papers.
3.  **Caching**: NER results are cached in LanceDB; subsequent runs on the same paper are near-instant.
4.  **Batch Execution**: Supports `nohup` via auto-approval protocols in `human_feedback_node`.
