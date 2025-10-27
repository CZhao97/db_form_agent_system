# Project Pipeline Overview

This document explains the end-to-end workflow for `db_form_agent_system`, covering how literature is retrieved, enriched, indexed, and queried, as well as how compound data lookup slots into the overall agent experience. Use this as the authoritative reference when running the system locally or embedding the tools inside an orchestrator.

---

## 1. High-Level Architecture

```
┌──────────────────────┐      ┌──────────────────────┐      ┌──────────────────────┐
│  Search orchestration│  ➜   │  Storage (JSON + CSV)│  ➜   │  Vector index (FAISS) │
└─────────▲────────────┘      └─────────▲────────────┘      └─────────▲────────────┘
          │                               │                               │
          │                               │                               │
          │        ┌──────────────────────┴──────────────┐                 │
          │        │   Retrieval-augmented agent (LLM)   │◄───────────────┘
          │        └─────────────────────────────────────┘
          │
          │        ┌─────────────────────────────────────┐
          └────────┤ Compound lookup + SMILES analytics  │
                   └─────────────────────────────────────┘
```

* `FullTextJournalSearchTool` (aka the "search tool") performs multi-source literature retrieval and persists the results under timestamped run directories.
* `FullTextIndexTool` and `FullTextQueryTool` convert the stored full texts into a FAISS vector index and expose semantic retrieval for downstream agents.
* `CompoundDatabaseTool` provides PubChem- and RDKit-backed compound enrichment that complements the literature workflow.

---

## 2. Search and Ingestion Workflow

### 2.1 Entry Points

* **Agent / Tool**: `FullTextJournalSearchTool` in `code/searching_tool.py`
* **Headless script**: `scripts/run_searching_test.py`
* **Notebook experiments**: `notebooks/hmdb_test_agent.ipynb`

### 2.2 Data Sources

| Source  | Enabled by default | Notes |
|---------|--------------------|-------|
| PubMed + PMC | ✅ | Primary source. Retrieves metadata, abstract, and attempts to pull structured JATS full text when available. |
| arXiv | ⚠️ currently disabled via `include_preprints=False` | PDF fallback for preprints. |
| Crossref, bioRxiv | ❌ commented out in current codebase | Can be re-enabled by restoring helper methods in `searching_tool.py`.

### 2.3 Execution Flow

1. **Normalize queries** – `_run()` accepts a single string, a `||`-delimited list, or a JSON array of query strings.
2. **Session directory** – results are written to `searching_results/run_<UTC timestamp>/`. You can override the base directory with the `results_base_dir` constructor argument or the `SEARCH_RESULTS_DIR` environment variable.
3. **Source-specific retrieval** – the tool executes the selected search providers and assembles a combined result set.
4. **Deduplication** – merges records by DOI, PMID, arXiv ID, or fuzzy title similarity (`title_close`).
5. **Full-text acquisition**:
   * PubMed entries attempt PMC JATS extraction first.
   * If full text remains unavailable, any available `pdf_url` is downloaded to `assets/` and parsed via `pdfplumber`/`pdfminer` and `PyMuPDF` (if installed) to capture text, tables, and figures.
   * Extracted text is cleaned to remove boilerplate and references.
6. **Persistence** – each retained paper is saved as `<doi|pmid|title>.json` with a standardized schema containing metadata, cleaned full text, and asset paths. An `index.csv`/`index.ndjson` pair summarises the run.

### 2.4 Run Directory Layout

```
searching_results/
└── run_YYYYmmdd_HHMMSS/
    ├── index.csv              # Tabular summary of all saved papers
    ├── index.ndjson           # Line-delimited JSON for programmatic ingestion
    ├── <paper>.json           # Full payload per paper (metadata + full_text + asset refs)
    └── assets/
        ├── <paper>.pdf       # Downloaded PDFs
        └── <paper>_pX_imgY.* # Extracted figures when PyMuPDF is available
```

Each JSON file contains the keys documented in the tool docstring (source, title, authors, pubdate, doi, url, ids, abstract, full_text, tables, figures, pdf_path, html_path, has_fulltext).

### 2.5 Operational Tips

* **Environment variables**
  * `ENTREZ_EMAIL` – override the default Entrez email identity when talking to NCBI.
  * `SEARCH_SESSION_DIR` – force the tool to reuse an existing run folder (useful within a single agent conversation).
  * `SEARCH_RESULTS_DIR` – change the base directory for new runs.
* **Network resilience** – the tool uses retry-enabled HTTP sessions and exponential backoff for Entrez calls.
* **Error handling** – failures from individual providers or download steps are logged but do not abort the overall run; unsuccessful PDFs are still retained with diagnostic flags.

---

## 3. Vector Indexing Pipeline

### 3.1 Index Construction (`FullTextIndexTool`)

1. **Inputs** – path to a `run_*` directory (or any file inside it), plus chunking parameters.
2. **Document building** – loads each JSON paper, slices `full_text` into overlapping fragments (paragraph-aware by default), and attaches metadata (title, source, doi, etc.).
3. **Embeddings** – uses `all-MiniLM-L6-v2` via `SentenceTransformerEmbeddings`, avoiding remote API calls.
4. **Vector store** – creates an in-memory FAISS index; optionally persists to `<run_dir>/faiss_index/`.
5. **Return payload** – JSON summary including document count, persistence status, and paths.

### 3.2 Querying (`FullTextQueryTool`)

1. **Index loading** – reuses the in-process `_VECTOR_REGISTRY` cache or loads the persisted FAISS files.
2. **Similarity search** – `similarity_search_with_score` (k configurable, default 20) returns top snippets with associated metadata.
3. **Tool output** – JSON containing the ranked hits, ready for grounding citations in an LLM response.

### 3.3 Typical Usage Pattern

```python
from fulltext_vector_tools import FullTextIndexTool, FullTextQueryTool

run_dir = "searching_results/run_20251009_000906"
# prefer passing the project-wide results base so tools can resolve run dirs reliably
base = "/home/chen/GNPS_SIM/agent/db_form_agent_system/searching_results"
index_tool = FullTextIndexTool(results_base_dir=base)
print(index_tool._run(run_path=run_dir))

query_tool = FullTextQueryTool(results_base_dir=base)
print(query_tool._run(run_path=run_dir, query="oxidized phospholipid biomarkers", k=5))
```

---

## 4. Compound Data Workflow (`CompoundDatabaseTool`)

1. **Inputs** – compound name, mass, formula, or SMILES.
2. **PubChem integration** – searches by name, mass, or formula and collates top matches (when `pubchempy` is installed).
3. **SMILES analytics** – supplements search results using RDKit when available, generating formulas and exact masses even without PubChem.
4. **Output schema** – JSON structure with `primary` result, `candidates`, `synonyms`, and `smiles_analysis` blocks.
5. **Error handling** – wrapped by `safe_tool_wrapper` to guarantee string outputs and user-friendly error messages.

### Example quick run

```bash
python scripts/run_compound_test.py
```

The script demonstrates name, SMILES, and mass searches and prints the raw JSON responses.

---

## 5. Agent & Prompt Layer

* Prompt templates in `prompts/` (`critique_agent.md`, `literature_agent.md`) describe higher-level agent roles that orchestrate the tools.
* Notebook prototypes under `notebooks/` show how to combine tool outputs with LLM calls for interactive exploration (e.g., `hmdb_test_agent.ipynb`).
* When embedding inside an agent framework, the usual pattern is:
  1. Run `fulltext_journal_search` to create a run directory.
  2. Build an index with `fulltext_index` for that run.
  3. Use `fulltext_query` to gather supporting evidence during the conversation.
  4. Call `compound_database` when chemical context is required.

---

## 6. Operational Checklist

| Step | Command / Action | Output |
|------|------------------|--------|
| 1. Validate compound tool | `python scripts/run_compound_test.py` | JSON payloads per lookup |
| 2. Create literature run | `python scripts/run_searching_test.py` | New `searching_results/run_*` folder |
| 3. Build vector index | Use `FullTextIndexTool` (Python or agent call) | `faiss_index/` persisted assets |
| 4. Query index | `FullTextQueryTool` | Ranked snippets with metadata |

*Keep the virtual environment activated (`.venv/`) and ensure dependencies (e.g., `Biopython`, `pdfplumber`, `PyMuPDF`, `langchain`) are installed.*

---

## 7. Troubleshooting

* **No papers saved** – confirm that the search term actually returns PMC full text. Only entries with `has_fulltext=True` are persisted.
* **FAISS index missing** – run `FullTextIndexTool` with `persist=True` before calling `FullTextQueryTool` or ensure the in-memory cache has been populated this session.
* **PubChem errors** – install `pubchempy` (`pip install pubchempy`) and ensure network access.
* **RDKit unavailable** – the tool still runs but omits SMILES analysis; install `rdkit-pypi` for full functionality.
* **Entrez rate limits** – set `ENTREZ_EMAIL` and introduce pauses between bulk runs to comply with NCBI usage policies.

---

## 8. Next Steps

* Re-enable Crossref / bioRxiv modules for broader coverage once API keys and rate limits are addressed.
* Automate pipeline execution via a higher-level orchestrator or scheduled job to refresh the knowledge base.
* Add regression tests for the vector indexing workflow to validate embeddings and persistence behaviour.
