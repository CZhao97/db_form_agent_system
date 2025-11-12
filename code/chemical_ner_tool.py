from __future__ import annotations
from typing import List, Dict, Optional, Any, Tuple, Type
import time
import torch
import json
import requests
from pathlib import Path
from contextvars import ContextVar

# ---------------- third-party libs ----------------
import flair
from flair.data import Sentence
from flair.nn import Classifier
from flair.models import EntityMentionLinker
# Removed: from flair.splitter import SegtokSentenceSplitter (too slow!)

# NEW: PubChemPy for synonyms
import pubchempy as pcp

# --- Pydantic and LangChain Imports ---
from pydantic import BaseModel, Field
from langchain.tools import BaseTool
from langchain_core.runnables import RunnableConfig

# --- Context variable for session directory ---
_session_dir_var: ContextVar[Optional[str]] = ContextVar("chemical_ner_session_dir", default=None)

# ---------------- E-UTILS ----------------
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

def _get(url: str, params: Dict, tries: int = 3, backoff: float = 0.7) -> requests.Response:
    """Simple retrying GET with exponential backoff."""
    for i in range(tries):
        r = requests.get(url, params=params, timeout=30)
        if r.ok:
            return r
        if i < tries - 1:
            time.sleep(backoff * (2 ** i))
    r.raise_for_status()
    return r  # pragma: no cover

def mesh_descriptor_to_cids(
    mesh_did: str,
    api_key: Optional[str] = None,
    email: Optional[str] = None,
    tool: str = "mesh2cid_example"
) -> List[int]:
    """
    Convert a MeSH Descriptor ID (e.g., 'D000082') to PubChem CIDs via:
      1) ESearch MeSH -> numeric UID
      2) ELink MeSH (UID) -> PubChem Compound (pccompound)
    Returns a sorted, de-duplicated list of CIDs (ints). May be empty if no link.
    """

    # 1) MeSH Dxxxxxx -> numeric MeSH UID
    esearch_params = {
        "db": "mesh",
        "retmode": "json",
        "term": f"{mesh_did}[MeSH Unique ID]",
        "tool": tool
    }
    if api_key: esearch_params["api_key"] = api_key
    if email:   esearch_params["email"] = email

    r = _get(f"{EUTILS_BASE}/esearch.fcgi", esearch_params)
    data = r.json()
    idlist = data.get("esearchresult", {}).get("idlist", [])
    if not idlist:
        return []

    mesh_uid = idlist[0]  # use the first/only UID

    # 2) Link that MeSH UID to PubChem Compound (pccompound) -> CIDs
    elink_params = {
        "dbfrom": "mesh",
        "db": "pccompound",
        "retmode": "json",
        "id": mesh_uid,
        "tool": tool
    }
    if api_key: elink_params["api_key"] = api_key
    if email:   elink_params["email"] = email

    r2 = _get(f"{EUTILS_BASE}/elink.fcgi", elink_params)
    d2 = r2.json()

    cids = []
    for ls in d2.get("linksets", []):
        for ldb in (ls.get("linksetdbs") or []):
            cids.extend(ldb.get("links", []) or [])

    # de-duplicate + sort as ints
    try:
        cids_int = sorted({int(x) for x in cids})
    except Exception:
        cids_int = sorted({int(str(x)) for x in cids if str(x).isdigit()})

    return cids_int

# NEW: helper to fetch synonyms for one CID via PubChemPy
def _cid_to_synonyms(cid: int) -> List[str]:
    try:
        cmpd = pcp.Compound.from_cid(int(cid))
        syns = cmpd.synonyms or []
        # Light cleanup & dedup
        seen = set()
        out = []
        for s in syns:
            ss = s.strip()
            if ss and ss.lower() not in seen:
                seen.add(ss.lower())
                out.append(ss)
        return out
    except Exception:
        return []

# NEW: collapse synonyms across multiple CIDs
def cids_to_synonyms(cids: List[int], max_per_cid: Optional[int] = None) -> List[str]:
    all_syns = []
    for cid in cids:
        syns = _cid_to_synonyms(cid)
        if max_per_cid is not None and max_per_cid > 0:
            syns = syns[:max_per_cid]
        all_syns.extend(syns)
        # Be polite; PubChemPy hits PUG REST under the hood
        time.sleep(0.2)
    # global dedup (case-insensitive), keep first seen casing
    seen = {}
    for s in all_syns:
        k = s.lower()
        if k not in seen:
            seen[k] = s
    return list(seen.values())

# ---------------- Caching & types ----------------
_MODELS: Dict[Tuple[str, str, int, int, bool], Dict[str, Any]] = {}

EntityValue = Dict[str, Any]  # e.g., {"synonyms": [...], "mentions": ["Aspirin", ...]}
MergedResultDict = Dict[Optional[str], EntityValue]

# ---------------- Device helpers ----------------
def _device_for(idx: int) -> torch.device:
    if torch.cuda.is_available() and torch.cuda.device_count() > idx:
        return torch.device(f"cuda:{idx}")
    return torch.device("cpu")

# ---------------- Chunking helpers (NEW, high impact) ----------------
# Use simple regex-based splitting instead of slow SegtokSentenceSplitter
import re
_SENTENCE_PATTERN = re.compile(r'[.!?]+[\s]+|[\n]{2,}')

def _split_into_sentences(text: str) -> List[str]:
    """Fast sentence splitting using regex instead of slow Segtok."""
    if not text.strip():
        return []
    # Split on sentence boundaries
    sentences = _SENTENCE_PATTERN.split(text)
    # Filter empty and clean
    return [s.strip() for s in sentences if s.strip()]

def _pack_sentences(sentences: List[str], max_chars: int = 2500) -> List[str]:
    """
    Greedy packer: groups sentences so each chunk <= max_chars.
    Increased from 1200 to 2500 to reduce number of chunks (fewer Sentence objects).
    Using chars is a good proxy for tokens; keeps chunks ~500–800 tokens.
    """
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for s in sentences:
        sl = len(s)
        if sl > max_chars:
            # very long single sentence → flush current and add alone (truncate slightly)
            if cur:
                chunks.append(" ".join(cur))
                cur, cur_len = [], 0
            chunks.append(s[:max_chars])
            continue
        if cur_len + (1 if cur else 0) + sl <= max_chars:
            cur.append(s)
            cur_len += (1 if cur_len > 0 else 0) + sl
        else:
            chunks.append(" ".join(cur))
            cur, cur_len = [s], sl
    if cur:
        chunks.append(" ".join(cur))
    return chunks

# ---------------- Model loading (tuned) ----------------
def _load_and_prepare_models(
    ner_model_name: str = "hunflair2",
    linker_model_name: str = "chemical-linker",
    ner_gpu: int = 0,
    linker_gpu: int = 1,
    use_fp16: bool = True,     # default to True (safe with autocast)
    warmup: bool = True,
    warmup_text: str = "Test chemical aspirin."
):
    """
    Load models once, set global device, enable TF32, and (optionally) warm up.
    Returns tuple (ner, linker, ner_device, linker_device).
    """
    key = (ner_model_name, linker_model_name, ner_gpu, linker_gpu, use_fp16)
    if key in _MODELS:
        m = _MODELS[key]
        return m["ner"], m["linker"], m["ner_device"], m["linker_device"]

    ner_device = _device_for(ner_gpu)
    linker_device = _device_for(linker_gpu)

    # Global device for Flair internals
    flair.device = ner_device

    # Speedups
    try:
        torch.set_grad_enabled(False)
    except Exception:
        pass
    if ner_device.type == "cuda" or linker_device.type == "cuda":
        try:
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            torch.backends.cudnn.benchmark = True
        except Exception:
            pass

    ner = Classifier.load(ner_model_name)
    linker = EntityMentionLinker.load(linker_model_name)

    ner.to(ner_device)
    linker.to(linker_device)

    ner.eval()
    linker.eval()

    if warmup:
        try:
            s = Sentence(warmup_text)
            if ner_device.type == "cuda":
                with torch.inference_mode(), torch.cuda.amp.autocast(enabled=use_fp16):
                    ner.predict([s], mini_batch_size=1)
                    linker.predict([s], batch_size=1)
            else:
                with torch.inference_mode():
                    ner.predict([s], mini_batch_size=1)
                    linker.predict([s], batch_size=1)
        except Exception:
            pass

    _MODELS[key] = {
        "ner": ner,
        "linker": linker,
        "ner_device": ner_device,
        "linker_device": linker_device,
    }

    # Debug print
    try:
        nd = next(ner.parameters()).device if any(True for _ in ner.parameters()) else None
    except Exception:
        nd = None
    try:
        ld = next(linker.parameters()).device if any(True for _ in linker.parameters()) else None
    except Exception:
        ld = None
    print(f"[model] ner -> {ner_device} (params on {nd}), linker -> {linker_device} (params on {ld})")

    return ner, linker, ner_device, linker_device

# ---------------- Core batch (rewritten) ----------------
def extract_chemicals_with_nen_batch(
    texts: List[str],
    ner_gpu: int = 0,
    linker_gpu: int = 1,
    ner_model_name: str = "hunflair2",
    linker_model_name: str = "chemical-linker",
    use_fp16: bool = True,
    verbose: bool = False,
    ner_mini_batch_size: int = 16,       # Reduced to prevent hanging
    linker_mini_batch_size: int = 32,    # Reduced to prevent hanging
    max_chunk_chars: int = 3000,         # Larger chunks = fewer total chunks
) -> List[MergedResultDict]:
    """
    Batch processing version of chemical extraction + NEN with:
      - sentence splitting + greedy chunking
      - larger mini-batches
      - mixed precision on GPU
      - lower Python/object overhead
    Returns per-document dicts keyed by KB id (e.g., "MESH:...").
    """
    if not isinstance(texts, list):
        raise TypeError("texts must be a list of strings")
    if not texts:
        return []

    ner, linker, ner_device, linker_device = _load_and_prepare_models(
        ner_model_name=ner_model_name,
        linker_model_name=linker_model_name,
        ner_gpu=ner_gpu,
        linker_gpu=linker_gpu,
        use_fp16=use_fp16,
        warmup=True,
    )

    # ---- build chunks and provenance map ----
    print(f"[NER] Preparing {len(texts)} documents for processing...")
    t_prep_start = time.time()
    
    all_chunks: List[Sentence] = []
    doc_index: List[int] = []

    for i, text in enumerate(texts):
        if not isinstance(text, str) or not text.strip():
            continue
        sents = _split_into_sentences(text)
        chunks = _pack_sentences(sents, max_chars=max_chunk_chars)
        for ch in chunks:
            all_chunks.append(Sentence(ch))
            doc_index.append(i)
        
        # Progress indicator every 50 docs
        if (i + 1) % 50 == 0 or (i + 1) == len(texts):
            print(f"[NER]   Processed {i+1}/{len(texts)} docs, {len(all_chunks)} chunks created")

    if not all_chunks:
        return [{} for _ in texts]
    
    t_prep = time.time() - t_prep_start
    print(f"[NER] Preparation complete: {len(all_chunks)} chunks in {t_prep:.2f}s")

    # ---- predict NER + linker in bigger batches with autocast ----
    t0 = time.time()
    print(f"[NER] Running NER model on {len(all_chunks)} chunks (batch_size={ner_mini_batch_size})...")
    
    if ner_device.type == "cuda":
        with torch.inference_mode(), torch.cuda.amp.autocast(enabled=use_fp16):
            ner.predict(all_chunks, mini_batch_size=ner_mini_batch_size, verbose=True)
    else:
        with torch.inference_mode():
            ner.predict(all_chunks, mini_batch_size=ner_mini_batch_size, verbose=True)
    t1 = time.time()
    print(f"[NER] NER complete in {t1-t0:.2f}s")

    print(f"[NER] Running Entity Linker on {len(all_chunks)} chunks (batch_size={linker_mini_batch_size})...")
    if linker_device.type == "cuda":
        with torch.inference_mode(), torch.cuda.amp.autocast(enabled=use_fp16):
            linker.predict(all_chunks, batch_size=linker_mini_batch_size)
    else:
        with torch.inference_mode():
            linker.predict(all_chunks, batch_size=linker_mini_batch_size)
    t2 = time.time()
    print(f"[NER] Entity Linking complete in {t2-t1:.2f}s")

    if verbose:
        total_chunks = len(all_chunks)
        avg_ner = (t1 - t0) / max(1, total_chunks)
        avg_linker = (t2 - t1) / max(1, total_chunks)
        print(
            f"[timing-batch] chunks={total_chunks}, "
            f"ner={t1-t0:.3f}s ({avg_ner*1000:.1f} ms/chunk), "
            f"linker={t2-t1:.3f}s ({avg_linker*1000:.1f} ms/chunk), total={t2-t0:.3f}s"
        )

    # ---- aggregate results back per document ----
    per_doc: List[MergedResultDict] = [dict() for _ in texts]

    for chunk, doc_i in zip(all_chunks, doc_index):
        out_dict = per_doc[doc_i]

        for span in chunk.get_spans("ner"):
            if (span.tag or "").lower() != "chemical":
                continue

            kb_id: Optional[str] = None
            link_labels = span.get_labels("link")
            if link_labels:
                top = max(link_labels, key=lambda l: l.score)
                kb_id = top.value  # e.g., "MESH:D000082"

            mention_text: str = span.text
            if kb_id not in out_dict:
                out_dict[kb_id] = {"synonyms": [], "mentions": []}
            out_dict[kb_id]["mentions"].append(mention_text)

    return per_doc

def merge_batch_results(batch_results: List[MergedResultDict]) -> MergedResultDict:
    """
    Merges a list of result dictionaries into a single dictionary.
    """
    final_merged_dict: MergedResultDict = {}
    for result_dict in batch_results:
        for kb_id, value_dict in result_dict.items():
            if kb_id not in final_merged_dict:
                final_merged_dict[kb_id] = {"synonyms": [], "mentions": []}
            final_merged_dict[kb_id]["mentions"].extend(value_dict["mentions"])
    return final_merged_dict

# -------------------- LANGCHAIN TOOL --------------------
class ChemicalNerInput(BaseModel):
    """Input schema for the Chemical NER Tool."""
    texts: List[str] = Field(..., description="A list of text strings OR JSON file paths OR a single folder path containing JSON files.")
    get_synonyms: bool = Field(False, description="If true, resolve MeSH→CID and fetch PubChem synonyms.")
    load_from_json: bool = Field(False, description="If true, treat 'texts' as file paths to JSON files and extract 'full_text' field from each.")
    load_from_folder: bool = Field(False, description="If true, treat 'texts[0]' as a folder path and load all JSON files from that directory.")

class ChemicalNerTool(BaseTool):
    """
    Tool to extract chemical entities, link them to MESH, and (optionally) fetch PubChem synonyms.
    Saves results to a local JSON file and returns the file path.
    Supports loading text directly from JSON files or scanning entire folders to reduce token costs.
    """
    name: str = "chemical_ner"
    description: str = (
        "Extracts chemical entities (NER), links them to MESH IDs, and optionally converts MeSH to PubChem "
        "to fetch synonyms via PubChemPy. Saves results to a JSON file in the session directory and returns the file path. "
        "Can load text from JSON files (set load_from_json=true) or from a folder (set load_from_folder=true) to reduce token costs."
    )
    args_schema: Type[BaseModel] = ChemicalNerInput

    # You can pass runtime parameters like email upon initialization
    ncbi_email: str = "laozc@student.ubc.ca"  # Default email
    ncbi_tool: str = "flair_nen_to_synonyms_agent_tool"

    @classmethod
    def set_session_dir(cls, session_dir: str) -> None:
        """Set the session directory for saving NER results."""
        _session_dir_var.set(session_dir)

    @classmethod
    def get_session_dir(cls) -> Optional[str]:
        """Get the current session directory."""
        return _session_dir_var.get()

    def __init__(self, ncbi_email: str = "laozc@student.ubc.ca", **data):
        super().__init__(**data)
        self.ncbi_email = ncbi_email
        self.ncbi_tool = "flair_nen_to_synonyms_agent_tool"

    def _load_texts_from_json_files(self, file_paths: List[str]) -> List[str]:
        """
        Load text content from JSON files.
        """
        texts = []
        for file_path in file_paths:
            try:
                path = Path(file_path)
                if not path.exists():
                    print(f"[{self.name}] Warning: File not found: {file_path}")
                    continue

                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Try to extract text in order of preference
                text = None
                if isinstance(data, dict):
                    text = data.get('full_text') or data.get('abstract') or data.get('title', '')

                if text and isinstance(text, str) and text.strip():
                    # Truncate very long texts to avoid memory issues (keep first 10000 chars)
                    texts.append(text.strip()[:10000])
                else:
                    print(f"[{self.name}] Warning: No valid text found in {file_path}")

            except Exception as e:
                print(f"[{self.name}] Error loading {file_path}: {e}")

        return texts

    def _load_texts_from_folder(self, folder_path: str) -> List[str]:
        """
        Load text content from all JSON files in a folder.
        """
        try:
            # Convert to absolute path to handle both relative and absolute paths
            folder = Path(folder_path).resolve()
            if not folder.exists():
                print(f"[{self.name}] Error: Folder not found: {folder_path} (resolved to: {folder})")
                return []

            if not folder.is_dir():
                print(f"[{self.name}] Error: Path is not a directory: {folder_path}")
                return []

            # Find all JSON files in the folder (non-recursive)
            json_files = sorted(folder.glob("*.json"))

            if not json_files:
                print(f"[{self.name}] Warning: No JSON files found in {folder_path}")
                return []

            print(f"[{self.name}] Found {len(json_files)} JSON files in {folder_path}")

            # Use existing method to load texts from the file list
            file_paths = [str(f) for f in json_files]
            return self._load_texts_from_json_files(file_paths)

        except Exception as e:
            print(f"[{self.name}] Error loading folder {folder_path}: {e}")
            return []

    def _run(
        self,
        texts: List[str],
        get_synonyms: bool = False,
        load_from_json: bool = False,
        load_from_folder: bool = False,
        config: Optional[RunnableConfig] = None,
        **kwargs
    ) -> str:
        """The core logic of the tool."""

        session_dir: Optional[str] = None

        try:
            # Priority: load_from_folder > load_from_json > direct text
            if load_from_folder:
                if not texts or len(texts) == 0:
                    return json.dumps({
                        "error": True,
                        "message": "load_from_folder=true but no folder path provided in texts[0]"
                    })
                folder_path = Path(texts[0]).resolve()
                session_dir = str(folder_path)
                print(f"[{self.name}] Loading all JSON files from folder: {folder_path}")
                input_texts = self._load_texts_from_folder(str(folder_path))
                print(f"[{self.name}] Loaded {len(input_texts)} text documents from folder")
            elif load_from_json:
                resolved_files = [Path(p).resolve() for p in texts]
                if resolved_files:
                    session_dir = str(resolved_files[0].parent)
                print(f"[{self.name}] Loading texts from {len(texts)} JSON files...")
                input_texts = self._load_texts_from_json_files([str(p) for p in resolved_files])
                print(f"[{self.name}] Loaded {len(input_texts)} text documents")
            else:
                input_texts = texts

            if not session_dir:
                session_dir = self.get_session_dir()

            if not input_texts:
                return json.dumps({
                    "error": True,
                    "message": "No valid texts found to process"
                })

            # Step 1: Run batch NER and Linking (now chunked & optimized)
            # Process in smaller document batches to prevent hanging
            doc_batch_size = 25  # Process 25 docs at a time (reduced from 50 if still hanging)
            print(f"[{self.name}] Processing {len(input_texts)} documents with chemical NER...")
            print(f"[{self.name}] Using document batches of {doc_batch_size} to prevent memory issues")
            t_start = time.time()
            
            results_per_doc = []
            for batch_idx in range(0, len(input_texts), doc_batch_size):
                batch_end = min(batch_idx + doc_batch_size, len(input_texts))
                batch_texts = input_texts[batch_idx:batch_end]
                
                print(f"[{self.name}] Processing document batch {batch_idx//doc_batch_size + 1}/{(len(input_texts)-1)//doc_batch_size + 1} (docs {batch_idx+1}-{batch_end})")
                
                batch_results = extract_chemicals_with_nen_batch(
                    batch_texts,
                    ner_gpu=0,
                    linker_gpu=1,
                    use_fp16=True,
                    verbose=True,  # Enable verbose timing
                    ner_mini_batch_size=8,     # Further reduced to 8 (from 16)
                    linker_mini_batch_size=16,  # Further reduced to 16 (from 32)
                    max_chunk_chars=3000        # Bigger chunks = fewer Sentence objects
                )
                results_per_doc.extend(batch_results)
                
                # Clear GPU cache between batches
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            
            t_ner = time.time() - t_start
            print(f"[{self.name}] NER+Linking completed in {t_ner:.2f}s ({t_ner/len(input_texts):.2f}s per doc)")

            # Step 2: Merge all mentions from all texts
            final_merged_data = merge_batch_results(results_per_doc)

            # Step 3: Populate synonyms (if requested)
            mesh_to_syns_cache: Dict[str, List[str]] = {}

            if get_synonyms:
                mesh_ids_to_fetch = [
                    kb_id for kb_id in final_merged_data.keys()
                    if kb_id and isinstance(kb_id, str) and kb_id.startswith("MESH:")
                ]
                total_mesh = len(mesh_ids_to_fetch)
                print(f"[{self.name}] Fetching synonyms for {total_mesh} unique MeSH IDs...")
                
                for idx, kb_id in enumerate(mesh_ids_to_fetch, 1):
                    mesh_did = kb_id[5:]  # strip "MESH:"
                    if not mesh_did:
                        continue

                    if mesh_did not in mesh_to_syns_cache:
                        print(f"[{self.name}] [{idx}/{total_mesh}] MeSH→CID→Synonyms: {mesh_did}")
                        try:
                            # 1) MeSH→CIDs (can be multiple)
                            cids = mesh_descriptor_to_cids(
                                mesh_did=mesh_did,
                                email=self.ncbi_email,
                                tool=self.ncbi_tool
                            )
                            # 2) CIDs→Synonyms (union; dedup later)
                            syns = cids_to_synonyms(cids, max_per_cid=None)
                            mesh_to_syns_cache[mesh_did] = syns
                            print(f"[{self.name}]   -> Found {len(cids)} CIDs, {len(syns)} synonyms")
                            time.sleep(0.34)  # Rate limit between chemicals
                        except Exception as e:
                            print(f"[{self.name}] Error fetching synonyms for {mesh_did}: {e}")
                            mesh_to_syns_cache[mesh_did] = []

                    final_merged_data[kb_id]["synonyms"] = mesh_to_syns_cache[mesh_did]

            # Step 4: Reformat to the desired simple output
            total_mention_count = 0
            reformatted_merged_data: Dict[Optional[str], Dict[str, Any]] = {}

            for kb_id, value_dict in final_merged_data.items():
                mention_text_list = value_dict.get("mentions", [])
                total_mention_count += len(mention_text_list)

                # Case-insensitive dedup of mentions, preserve first casing
                seen_lower = set()
                unique_mentions = []
                for tx in mention_text_list:
                    lx = tx.lower()
                    if lx not in seen_lower:
                        seen_lower.add(lx)
                        unique_mentions.append(tx)
                unique_mentions.sort()

                reformatted_merged_data[kb_id] = {
                    "synonyms": value_dict.get("synonyms", []) if get_synonyms else [],
                    "mentions": [{"text": unique_mentions}]
                }

            # Save to file in session directory (derived from inputs when possible)
            def _count_mentions(data: Dict[Optional[str], Dict[str, Any]]) -> int:
                total = 0
                for entry in data.values():
                    for group in entry.get("mentions", []) or []:
                        total += len(group.get("text", []) or [])
                return total

            merged_output = reformatted_merged_data

            if session_dir:
                session_path = Path(session_dir)
                session_path.mkdir(parents=True, exist_ok=True)

                ner_dir = session_path / "ner_results"
                ner_dir.mkdir(parents=True, exist_ok=True)

                output_path = ner_dir / "chemical_ner_results.json"

                if output_path.exists():
                    print(f"[{self.name}] Merging with existing results in {output_path}")
                    try:
                        with open(output_path, "r", encoding="utf-8") as f:
                            existing_data = json.load(f)

                        existing_merged = existing_data.get("merged", {})
                        for kb_id, value_dict in reformatted_merged_data.items():
                            if kb_id in existing_merged:
                                existing_mentions_flat = [
                                    mention
                                    for bucket in existing_merged[kb_id].get("mentions", []) or []
                                    for mention in bucket.get("text", []) or []
                                ]
                                new_mentions_flat = [
                                    mention
                                    for bucket in value_dict.get("mentions", []) or []
                                    for mention in bucket.get("text", []) or []
                                ]
                                combined_mentions = sorted({*existing_mentions_flat, *new_mentions_flat})
                                existing_merged[kb_id]["mentions"] = [{"text": combined_mentions}]

                                existing_syns = existing_merged[kb_id].get("synonyms", []) or []
                                new_syns = value_dict.get("synonyms", []) or []
                                combined_syns = sorted({*existing_syns, *new_syns})
                                existing_merged[kb_id]["synonyms"] = list(combined_syns)
                            else:
                                existing_merged[kb_id] = value_dict

                        merged_output = existing_merged
                    except Exception as e:
                        print(f"[{self.name}] Warning: Could not merge with existing file. Overwriting. Error: {e}")
                        merged_output = reformatted_merged_data

                mention_count = _count_mentions(merged_output)

                final_output_dict = {
                    "error": False,
                    "results_file": str(output_path),
                    "mention_count": mention_count,
                }

                
                save_output_dict = {
                    "error": False,
                    "results_file": str(output_path),
                    "mention_count": mention_count,
                    "merged_output": merged_output
                }

                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(save_output_dict, f, indent=2, ensure_ascii=False)

                return json.dumps(final_output_dict, indent=2)
            else:
                mention_count = _count_mentions(merged_output)
                return json.dumps({
                    "error": False,
                    "results_file": None,
                    "mention_count": mention_count,
                }, indent=2)

        except Exception as e:
            # Return a JSON error message if the whole process fails
            return json.dumps({"error": True, "message": str(e)})

# -------------------- END OF TOOL DEFINITION --------------------
