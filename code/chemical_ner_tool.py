from __future__ import annotations
from typing import List, Dict, Optional, Any, Tuple, Type
import time
import torch
import json
import requests
from pathlib import Path
from contextvars import ContextVar
import os
import bisect
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ---------------- third-party libs ----------------
import flair
from flair.data import Sentence
from flair.nn import Classifier
from flair.models import EntityMentionLinker
# Removed: from flair.splitter import SegtokSentenceSplitter (too slow!)

# NEW: PubChemPy for synonyms
import pubchempy as pcp

# Optimization for Ampere+ GPUs
try:
    torch.set_float32_matmul_precision('high')
except Exception:
    pass

# --- Pydantic and LangChain Imports ---
from pydantic import BaseModel, Field
from langchain.tools import BaseTool
from langchain_core.runnables import RunnableConfig

# --- LanceDB Integration ---
try:
    import lancedb
    # Try to import the model definition from the build script
    # We assume build_offline_db.py is in the same directory
    import sys
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.append(current_dir)
    from build_offline_db import PaperChunk, TABLE_NAME, text_splitter
except ImportError:
    lancedb = None
    PaperChunk = None
    TABLE_NAME = "papers_index"
    text_splitter = None

# Fallback for text_splitter if import failed
if text_splitter is None:
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )
    except ImportError:
        pass # Will handle later if needed

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
# NEW: Simple in-memory cache for Entity Linking to skip neural network for common terms
_LINKER_CACHE: Dict[str, str] = {
    "oxygen": "MESH:D010100",
    "water": "MESH:D014867",
    "glucose": "MESH:D005947",
    "hydrogen": "MESH:D006859",
    "nitrogen": "MESH:D009584",
    "carbon dioxide": "MESH:D002245",
    "calcium": "MESH:D002118",
    "sodium": "MESH:D012964",
    "potassium": "MESH:D011188",
    "magnesium": "MESH:D008274",
    "iron": "MESH:D007501",
    "copper": "MESH:D003300",
    "zinc": "MESH:D015032",
    "ethanol": "MESH:D000431",
    "methanol": "MESH:D000432",
    "atp": "MESH:D000255",
    "adp": "MESH:D000244",
    "dna": "MESH:D004247",
    "rna": "MESH:D012313",
    "protein": "MESH:D011506",
    "amino acid": "MESH:D000596",
    "fatty acid": "MESH:D005227",
    "cholesterol": "MESH:D002784",
    "insulin": "MESH:D007328",
    "albumin": "MESH:D000418",
    "hemoglobin": "MESH:D006454",
    "glutamate": "MESH:D018698",
    "gaba": "MESH:D005680",
    "dopamine": "MESH:D004298",
    "serotonin": "MESH:D012701",
    "acetylcholine": "MESH:D000109",
    "epinephrine": "MESH:D004837",
    "norepinephrine": "MESH:D009638",
    "cortisol": "MESH:D006854",
    "testosterone": "MESH:D013739",
    "estrogen": "MESH:D004967",
    "progesterone": "MESH:D011374",
    "aspirin": "MESH:D001241",
    "ibuprofen": "MESH:D007052",
    "acetaminophen": "MESH:D000082",
    "caffeine": "MESH:D002110",
    "nicotine": "MESH:D009538",
    "alcohol": "MESH:D000431",
    "sugar": "MESH:D002241",
    "salt": "MESH:D012965",
    "acid": "MESH:D000138",
    "base": "MESH:D000138", # Generic mapping
    "buffer": "MESH:D002021",
    "solution": "MESH:D012996",
    "medium": "MESH:D003470",
    "serum": "MESH:D012709",
    "plasma": "MESH:D010949",
    "urine": "MESH:D014556",
    "blood": "MESH:D001769",
    "tissue": "MESH:D014024",
    "cell": "MESH:D002477",
}

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

def _pack_sentences_with_offsets(sentences: List[str], max_chars: int = 1500) -> List[Tuple[str, List[Tuple[int, int]]]]:
    """
    Packer that returns chunks of sentences, each respecting max_chars limit.
    """
    if not sentences:
        return []

    chunks = []
    current_sents = []
    current_len = 0
    
    for s in sentences:
        slen = len(s)
        # If adding this sentence exceeds max_chars, and we have something in buffer, flush buffer
        if current_len + slen + 1 > max_chars:
            if current_sents:
                chunk_text = " ".join(current_sents)
                offsets = []
                pos = 0
                for cs in current_sents:
                    offsets.append((pos, pos + len(cs)))
                    pos += len(cs) + 1
                chunks.append((chunk_text, offsets))
                
                current_sents = []
                current_len = 0
            
            # If the sentence itself is longer than max_chars, split it hard
            if slen > max_chars:
                for i in range(0, slen, max_chars):
                    sub_s = s[i:i+max_chars]
                    chunks.append((sub_s, [(0, len(sub_s))]))
                continue
        
        current_sents.append(s)
        current_len += slen + 1
        
    # Flush remaining
    if current_sents:
        chunk_text = " ".join(current_sents)
        offsets = []
        pos = 0
        for cs in current_sents:
            offsets.append((pos, pos + len(cs)))
            pos += len(cs) + 1
        chunks.append((chunk_text, offsets))
        
    return chunks

def _pack_sentences(sentences: List[str]) -> List[str]:
    """
    Legacy wrapper for _pack_sentences_with_offsets.
    """
    packed = _pack_sentences_with_offsets(sentences)
    return [p[0] for p in packed]

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
    
    if linker_model_name:
        linker = EntityMentionLinker.load(linker_model_name)
        linker.to(linker_device)
    else:
        linker = None

    ner.to(ner_device)
    
    # OPTIMIZATION: PyTorch 2.0 Compile
    # We use 'reduce-overhead' mode if available, or default.
    # We catch errors to fallback to eager mode.
    if False and hasattr(torch, "compile"):
        print(f"[model] Attempting to compile models with torch.compile on {ner_device}...")
        try:
            # Compile the underlying transformer embeddings
            def compile_transformer(model):
                if hasattr(model, "embeddings"):
                    from flair.embeddings import TransformerWordEmbeddings, TransformerDocumentEmbeddings
                    
                    # Handle StackedEmbeddings
                    embeddings = model.embeddings
                    if hasattr(embeddings, "embeddings"):
                        embed_list = embeddings.embeddings
                    else:
                        embed_list = [embeddings]
                        
                    for emb in embed_list:
                        if isinstance(emb, (TransformerWordEmbeddings, TransformerDocumentEmbeddings)):
                            if hasattr(emb, "model"):
                                print(f"[model] Compiling Transformer embedding in {type(model).__name__}")
                                # mode="reduce-overhead" is good for small batches, "max-autotune" for speed but slow compile
                                # default is a good balance.
                                emb.model = torch.compile(emb.model)

            compile_transformer(ner)
            
            # Linker usually has a transformer in 'model' or 'word_embeddings'
            if linker and hasattr(linker, "model"):
                 print(f"[model] Compiling Linker underlying model")
                 linker.model = torch.compile(linker.model)
            
        except Exception as e:
            print(f"[model] Compilation warning: {e}")

    ner.eval()
    if linker:
        linker.eval()

    if warmup:
        try:
            s = Sentence(warmup_text)
            if ner_device.type == "cuda":
                with torch.inference_mode(), torch.amp.autocast('cuda', enabled=use_fp16):
                    ner.predict([s], mini_batch_size=1)
                    if linker:
                        linker.predict([s], batch_size=1)
            else:
                with torch.inference_mode():
                    ner.predict([s], mini_batch_size=1)
                    if linker:
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
        ld = next(linker.parameters()).device if linker and any(True for _ in linker.parameters()) else None
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
    max_chunk_chars: int = 500,          # Reduced to 500 to prevent OOM/Crash
    disable_linking: bool = False        # NEW: Option to skip linking for speed
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

    # Filter texts to focus on Results/Discussion if present
    processed_texts = [_filter_relevant_sections(t) for t in texts]

    # Only load linker if we are going to use it
    actual_linker_name = None if disable_linking else linker_model_name
    
    ner, linker, ner_device, linker_device = _load_and_prepare_models(
        ner_model_name=ner_model_name,
        linker_model_name=actual_linker_name,
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
    chunk_offsets: List[List[Tuple[int, int]]] = []

    for i, text in enumerate(processed_texts):
        if not isinstance(text, str) or not text.strip():
            continue
        sents = _split_into_sentences(text)
        # Use max_chars to keep chunks small for faster Transformer inference
        packed = _pack_sentences_with_offsets(sents, max_chars=max_chunk_chars)
        for ch_text, offsets in packed:
            all_chunks.append(Sentence(ch_text))
            doc_index.append(i)
            chunk_offsets.append(offsets)
        
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

    # OPTIMIZATION: Sort chunks by length to minimize padding overhead during inference.
    # Since Sentence objects are modified in-place, we can create a sorted list, predict on it,
    # and the original 'all_chunks' list will reflect the changes.
    sorted_chunks = sorted(all_chunks, key=lambda s: len(s.to_plain_string()), reverse=True)
    
    try:
        if ner_device.type == "cuda":
            with torch.inference_mode(), torch.amp.autocast('cuda',enabled=use_fp16):
                ner.predict(sorted_chunks, mini_batch_size=ner_mini_batch_size, verbose=verbose)
        else:
            with torch.inference_mode():
                ner.predict(sorted_chunks, mini_batch_size=ner_mini_batch_size, verbose=verbose)
        t1 = time.time()
        print(f"[NER] NER complete in {t1-t0:.2f}s")

        # --- OPTIMIZATION: Only run linker on chunks that have entities ---
        # chunks_with_entities = [c for c in all_chunks if len(c.get_spans("ner")) > 0]
        
        # NEW: Apply Cache First
        chunks_to_link = []
        cached_count = 0
        
        # DEBUG: Check if we have any spans at all
        total_spans_found = 0
        
        for chunk in all_chunks:
            spans = chunk.get_spans("ner")
            if not spans:
                continue
                
            total_spans_found += len(spans)
            
            # Check if we can skip linking for this chunk
            # We can skip if ALL Chemical entities are in the cache.
            # If even one is missing, we must run the linker on the whole chunk
            # (because the linker expects the full context and might overwrite labels).
            
            needs_linking = False
            chemical_spans = []
            
            for span in spans:
                # Safer tag access
                tag_value = span.get_label("ner").value
                
                # Filter for Chemical entities only
                if tag_value != "Chemical":
                    continue
                
                chemical_spans.append(span)
                
                # Check if already linked
                if span.get_labels("link"):
                    continue
                    
                text_lower = span.text.lower()
                if text_lower not in _LINKER_CACHE:
                    needs_linking = True
            
            if needs_linking:
                chunks_to_link.append(chunk)
            elif chemical_spans:
                # All chemical spans are in cache (and there is at least one)
                # Apply cached labels now
                for span in chemical_spans:
                    text_lower = span.text.lower()
                    if text_lower in _LINKER_CACHE:
                        span.add_label("link", _LINKER_CACHE[text_lower], score=1.0)
                        cached_count += 1
        # If no chemical spans, we don't need to do anything (linker wouldn't do anything either)

        print(f"[NER] DEBUG: Total NER spans found: {total_spans_found}")
        print(f"[NER] {len(chunks_to_link)}/{len(all_chunks)} chunks need linking ({cached_count} entities resolved from cache in skipped chunks).")
        sys.stdout.flush()

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"ERROR in NER/Linking: {e}")
        sys.stdout.flush()
        raise e

    if chunks_to_link and linker:
        # Sort linker chunks as well
        sorted_linker_chunks = sorted(chunks_to_link, key=lambda s: len(s.to_plain_string()), reverse=True)
        
        # DEBUG: Check max length
        if sorted_linker_chunks:
            max_len = len(sorted_linker_chunks[0].to_plain_string())
            print(f"[NER] Max chunk length to link: {max_len} chars")
        
        # Force GC and clear cache
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        print(f"[NER] Preparing to link {len(chunks_to_link)} chunks...")
        sys.stdout.flush()

        # OPTIMIZATION: Explode chunks into single-entity sentences.
        # This avoids the quadratic complexity of the linker when many entities are in one sentence.
        # We lose context, but for Chemicals it is usually acceptable and provides 40x speedup.
        single_entity_sentences = []
        span_mapping = [] # (single_entity_sentence, original_span)
        
        for chunk in chunks_to_link:
            for span in chunk.get_spans("ner"):
                if span.get_label("ner").value != "Chemical":
                    continue
                
                # Check cache again
                text_lower = span.text.lower()
                if text_lower in _LINKER_CACHE:
                    span.add_label("link", _LINKER_CACHE[text_lower], score=1.0)
                    cached_count += 1
                    continue
                
                # Create a new sentence for this entity
                s_clone = Sentence(span.text)
                # Add NER label to the whole sentence
                span_clone = s_clone[0:len(s_clone)]
                span_clone.add_label("ner", "Chemical")
                
                single_entity_sentences.append(s_clone)
                span_mapping.append((s_clone, span))
        
        if single_entity_sentences:
            print(f"[NER] Exploded chunks into {len(single_entity_sentences)} single-entity sentences for linking.")
            sys.stdout.flush()
            
            # Run in batches
            # Use a larger batch size for these small sentences
            link_batch_size = 256 
            
            # Manual outer loop to prevent hanging on huge lists and show progress
            total_sentences = len(single_entity_sentences)
            outer_batch_size = 5000 # Process 5000 entities at a time
            
            for i in range(0, total_sentences, outer_batch_size):
                batch_slice = single_entity_sentences[i : i + outer_batch_size]
                print(f"[NER] Linking batch slice {i}-{min(i+outer_batch_size, total_sentences)}/{total_sentences}...")
                sys.stdout.flush()
                
                try:
                    if linker_device.type == "cuda":
                        with torch.inference_mode(), torch.amp.autocast('cuda', enabled=use_fp16):
                            linker.predict(batch_slice, batch_size=link_batch_size)
                    else:
                        with torch.inference_mode():
                            linker.predict(batch_slice, batch_size=link_batch_size)
                except Exception as e:
                    print(f"[NER] Error linking slice {i}: {e}")
                    sys.stdout.flush()
            
            # Map back results
            for s_clone, original_span in span_mapping:
                span_clone = s_clone[0:len(s_clone)]
                link_labels = span_clone.get_labels("link")
                if link_labels:
                    # Take the top one
                    top = max(link_labels, key=lambda l: l.score)
                    original_span.add_label("link", top.value, score=top.score)

        # Update Cache with new results
        new_cached = 0
        for chunk in chunks_to_link:
            for span in chunk.get_spans("ner"):
                if span.get_label("ner").value != "Chemical":
                    continue
                    
                link_labels = span.get_labels("link")
                if link_labels:
                    top = max(link_labels, key=lambda l: l.score)
                    kb_id = top.value
                    text_lower = span.text.lower()
                    if text_lower not in _LINKER_CACHE:
                        _LINKER_CACHE[text_lower] = kb_id
                        new_cached += 1
        if new_cached > 0:
            print(f"[NER] Added {new_cached} new terms to linker cache (total size: {len(_LINKER_CACHE)})")

    elif not linker:
        print("[NER] Linker disabled. Skipping linking.")
    else:
        print("[NER] No entities found or all resolved by cache. Skipping linker.")

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

    for chunk, doc_i, offsets in zip(all_chunks, doc_index, chunk_offsets):
        out_dict = per_doc[doc_i]
        chunk_plain = chunk.to_plain_string()
        
        # Precompute start positions for bisect
        chunk_starts = [o[0] for o in offsets]
        chunk_ends = [o[1] for o in offsets]

        for span in chunk.get_spans("ner"):
            if (span.tag or "").lower() != "chemical":
                continue

            mention_text: str = span.text
            
            kb_id: Optional[str] = None
            link_labels = span.get_labels("link")
            if link_labels:
                top = max(link_labels, key=lambda l: l.score)
                kb_id = top.value  # e.g., "MESH:D000082"
            
            # Fallback if no linker or no link found: use normalized text
            if not kb_id:
                kb_id = f"TEXT:{mention_text.upper()}"
            
            # Optimized Context Lookup using bisect
            start = span.start_position
            end = span.end_position
            
            # Find the first sentence that starts before or at the mention start
            idx_start = bisect.bisect_right(chunk_starts, start) - 1
            
            context_sentence = mention_text # Default
            
            if idx_start >= 0:
                # Check if the mention is fully contained in this sentence
                s_start = chunk_starts[idx_start]
                s_end = chunk_ends[idx_start]
                
                if end <= s_end:
                    # Perfect match
                    context_sentence = chunk_plain[s_start:s_end]
                else:
                    # Spans multiple sentences. Find the last sentence overlapping the mention.
                    idx_last = bisect.bisect_left(chunk_starts, end) - 1
                    
                    # Clamp idx_last
                    if idx_last < idx_start: 
                        idx_last = idx_start
                    if idx_last >= len(chunk_starts):
                        idx_last = len(chunk_starts) - 1
                        
                    # Combine from start of first to end of last
                    c_start = chunk_starts[idx_start]
                    c_end = chunk_ends[idx_last]
                    context_sentence = chunk_plain[c_start:c_end]
            
            # Format: "Mention (Context: Sentence)"
            combined_text = f"{mention_text} (Context: {context_sentence})"

            if kb_id not in out_dict:
                out_dict[kb_id] = {"synonyms": [], "mentions": []}
            
            # Avoid duplicates (case-insensitive check on the full string)
            is_dup = False
            combined_lower = combined_text.lower()
            for existing in out_dict[kb_id]["mentions"]:
                if existing.lower() == combined_lower:
                    is_dup = True
                    break
            
            if not is_dup:
                out_dict[kb_id]["mentions"].append(combined_text)

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
    offline_index_path: Optional[str] = Field("/home/chen/GNPS_SIM/agent/db_form_agent_system/pmc_lancedb_index", description="Path to the offline LanceDB index. If provided, new results will be added to the DB.")

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

    def _load_texts_from_json_files(self, file_paths: List[str]) -> List[Dict[str, str]]:
        """
        Load text content from JSON files.
        Returns list of dicts: {"file": filename, "text": content}
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
                    # No truncation as requested. The chunking logic handles large texts.
                    texts.append({
                        "file": str(path), 
                        "text": text.strip(),
                        "raw_data": data  # Store raw data for offline DB update
                    })
                else:
                    print(f"[{self.name}] Warning: No valid text found in {file_path}")

            except Exception as e:
                print(f"[{self.name}] Error loading {file_path}: {e}")

        return texts

    def _load_texts_from_folder(self, folder_path: str) -> List[Dict[str, str]]:
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
            # Exclude .ner_cache.json files
            json_files = sorted([f for f in folder.glob("*.json") if not f.name.endswith(".ner_cache.json")])

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
        texts: List[Any], # Can be List[str] or List[Dict] depending on input
        get_synonyms: bool = False,
        load_from_json: bool = False,
        load_from_folder: bool = False,
        config: Optional[RunnableConfig] = None,
        offline_index_path: Optional[str] = "/home/chen/GNPS_SIM/agent/db_form_agent_system/pmc_lancedb_index",
        **kwargs
    ) -> str:
        """The core logic of the tool."""

        session_dir: Optional[str] = None
        input_data: List[Dict[str, str]] = [] # List of {"file": ..., "text": ...}

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
                input_data = self._load_texts_from_folder(str(folder_path))
                print(f"[{self.name}] Loaded {len(input_data)} text documents from folder")
            elif load_from_json:
                resolved_files = [Path(p).resolve() for p in texts]
                if resolved_files:
                    session_dir = str(resolved_files[0].parent)
                print(f"[{self.name}] Loading texts from {len(texts)} JSON files...")
                input_data = self._load_texts_from_json_files([str(p) for p in resolved_files])
                print(f"[{self.name}] Loaded {len(input_data)} text documents")
            else:
                # Direct text input
                if texts and isinstance(texts[0], dict) and "file" in texts[0] and "text" in texts[0]:
                    # Already in the correct format: [{"file": "...", "text": "..."}]
                    input_data = texts
                else:
                    # List of strings -> assign dummy filenames
                    input_data = [{"file": f"text_{i}.txt", "text": t} for i, t in enumerate(texts)]

            if not session_dir:
                session_dir = self.get_session_dir()

            if not input_data:
                return json.dumps({
                    "error": True,
                    "message": "No valid texts found to process"
                })

            # Check for cached NER results to skip processing
            final_results_map = {} # index -> entities
            docs_to_process = [] # list of (index, text)
            
            print(f"[{self.name}] Checking for cached NER results...")
            
            for idx, item in enumerate(input_data):
                file_path = item.get("file")
                text = item.get("text", "")
                
                found_cache = False
                if file_path and file_path.endswith(".json"):
                    # Check for sidecar file: [filename].ner_cache.json
                    cache_path = Path(file_path).with_suffix(".ner_cache.json")
                    if cache_path.exists():
                        try:
                            with open(cache_path, "r", encoding="utf-8") as f:
                                cached_entities = json.load(f)
                            # Validate it looks like a dict (MergedResultDict)
                            if isinstance(cached_entities, dict):
                                final_results_map[idx] = cached_entities
                                found_cache = True
                        except Exception as e:
                            print(f"[{self.name}] Error reading cache {cache_path}: {e}")
                
                if not found_cache:
                    docs_to_process.append((idx, text))
            
            print(f"[{self.name}] Found {len(final_results_map)} cached documents. {len(docs_to_process)} documents need NER.")

            # Extract just the texts for processing
            input_texts_to_process = [d[1] for d in docs_to_process]
            
            results_from_model = []
            
            if input_texts_to_process:
                # Step 1: Run batch NER and Linking (now chunked & optimized)
                # Process in smaller document batches to prevent hanging
                doc_batch_size = 25  # Process 25 docs at a time (reduced from 50 if still hanging)
                print(f"[{self.name}] Processing {len(input_texts_to_process)} documents with chemical NER...")
                print(f"[{self.name}] Using document batches of {doc_batch_size} to prevent memory issues")
                t_start = time.time()
                
                for batch_idx in range(0, len(input_texts_to_process), doc_batch_size):
                    batch_end = min(batch_idx + doc_batch_size, len(input_texts_to_process))
                    batch_texts = input_texts_to_process[batch_idx:batch_end]
                    
                    print(f"[{self.name}] Processing document batch {batch_idx//doc_batch_size + 1}/{(len(input_texts_to_process)-1)//doc_batch_size + 1} (docs {batch_idx+1}-{batch_end})")
                    
                    batch_results = extract_chemicals_with_nen_batch(
                        batch_texts,
                        ner_gpu=0,
                        linker_gpu=1,
                        use_fp16=True,
                        verbose=True,  # Enable verbose timing
                        ner_mini_batch_size=32,     # Increased for speed
                        linker_mini_batch_size=64,  # Increased for speed
                    )
                    results_from_model.extend(batch_results)
                    
                    # Clear GPU cache between batches
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                
                t_ner = time.time() - t_start
                print(f"[{self.name}] NER+Linking completed in {t_ner:.2f}s ({t_ner/len(input_texts_to_process):.2f}s per doc)")
            
            # Merge model results back into final map
            for i, (original_idx, _) in enumerate(docs_to_process):
                final_results_map[original_idx] = results_from_model[i]
            
            # Reconstruct results_per_doc in original order
            results_per_doc = [final_results_map[i] for i in range(len(input_data))]

            # Step 1.5: Construct per-file results list (User Request)
            per_file_results = []
            for i, res in enumerate(results_per_doc):
                per_file_results.append({
                    "file": input_data[i]["file"],
                    "entities": res
                })

            # Step 2: Merge all mentions from all texts
            # final_merged_data = merge_batch_results(results_per_doc)
            # User requested NO merging between files for now.
            final_merged_data = {}

            # Step 3: Populate synonyms (if requested)
            mesh_to_syns_cache: Dict[str, List[str]] = {}

            if get_synonyms:
                # Note: If final_merged_data is empty (no global merge), this won't fetch synonyms.
                # If synonyms are needed per-file, we would need to iterate per_file_results.
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
            
            # If global merge is disabled, count mentions from per_file_results for reporting
            if total_mention_count == 0 and per_file_results:
                for entry in per_file_results:
                    for kb_id, val in entry["entities"].items():
                        total_mention_count += len(val.get("mentions", []))

            # --- Step 5: Update Offline DB (if requested) ---
            # offline_index_path is passed as argument
            
            if offline_index_path and lancedb and PaperChunk and text_splitter:
                db_path = offline_index_path
                print(f"[{self.name}] Updating offline DB at {db_path} with {len(docs_to_process)} new documents...")
                try:
                    db = lancedb.connect(db_path)
                    if TABLE_NAME in db.table_names():
                        tbl = db.open_table(TABLE_NAME)
                        
                        new_chunks = []
                        for idx, text in docs_to_process:
                            # Get metadata from raw_data
                            raw = input_data[idx].get("raw_data", {})
                            # If raw_data is missing (e.g. direct text input), try to infer or use defaults
                            
                            # Extract metadata
                            title = raw.get("title", "Unknown Title")
                            year = raw.get("year", "Unknown Year")
                            source = raw.get("source", "Unknown Source")
                            
                            # Use filename as doc_id if no explicit id
                            fpath = input_data[idx].get("file", "")
                            doc_id = Path(fpath).name if fpath else f"doc_{time.time()}_{idx}"
                            
                            # Get NER results
                            ner_res = final_results_map.get(idx, {})
                            ner_json = json.dumps(ner_res)
                            
                            # Chunking
                            chunks = text_splitter.split_text(text)
                            for i, chunk_text in enumerate(chunks):
                                contextualized_text = f"Title: {title}. {chunk_text}"
                                new_chunks.append({
                                    "text": contextualized_text,
                                    "doc_id": doc_id,
                                    "title": title,
                                    "year": str(year),
                                    "source": source,
                                    "chunk_id": i,
                                    "ner_results": ner_json
                                })
                        
                        if new_chunks:
                            print(f"[{self.name}] Adding {len(new_chunks)} chunks to offline DB...")
                            tbl.add(new_chunks)
                            print(f"[{self.name}] Offline DB update complete.")
                        else:
                            print(f"[{self.name}] No new chunks to add.")
                    else:
                        print(f"[{self.name}] Warning: Table '{TABLE_NAME}' not found in offline DB. Skipping update.")
                except Exception as e:
                    print(f"[{self.name}] Error updating offline DB: {e}")
                    import traceback
                    traceback.print_exc()

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

                        # 1. Merge Global Output - SKIPPED as per user request
                        # We preserve existing merged output if it exists, but don't add to it
                        merged_output = existing_data.get("merged_output", {})
                        
                        # If we were merging, we would do this:
                        # for kb_id, value_dict in reformatted_merged_data.items():
                        #     if kb_id in existing_merged:
                        #         ...
                        #     else:
                        #         existing_merged[kb_id] = value_dict
                        # merged_output = existing_merged

                        # 2. Append Per-File Results
                        existing_per_file = existing_data.get("per_file_results", [])
                        # Optional: Check for duplicates based on filename to avoid double-adding if re-run
                        existing_filenames = {entry.get("file") for entry in existing_per_file}
                        
                        for new_entry in per_file_results:
                            if new_entry["file"] not in existing_filenames:
                                existing_per_file.append(new_entry)
                            else:
                                # If file already exists, we might want to update it or skip. 
                                # For now, let's skip to avoid duplication, assuming files are processed once.
                                print(f"[{self.name}] Warning: Results for {new_entry['file']} already exist. Skipping append.")
                        
                        per_file_results = existing_per_file

                    except Exception as e:
                        print(f"[{self.name}] Warning: Could not merge with existing file. Overwriting. Error: {e}")
                        merged_output = reformatted_merged_data

                mention_count = _count_mentions(merged_output)

                # Fix: If merged_output is empty (disabled), count from per_file_results
                if mention_count == 0 and per_file_results:
                    for entry in per_file_results:
                        for kb_id, val in entry.get("entities", {}).items():
                            mention_count += len(val.get("mentions", []))

                final_output_dict = {
                    "error": False,
                    "results_file": str(output_path),
                    "mention_count": mention_count,
                }

                
                save_output_dict = {
                    "error": False,
                    "results_file": str(output_path),
                    "mention_count": mention_count,
                    "merged_output": merged_output,
                    "per_file_results": per_file_results
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
def _filter_relevant_sections(text: str) -> str:
    """
    If text contains 'Results' or 'Discussion' sections (marked by '## '),
    return only those sections. Otherwise return full text.
    """
    if not text:
        return ""
    
    lines = text.split('\n')
    relevant_parts = []
    in_relevant_section = False
    found_any_relevant = False
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            title = stripped[3:].lower()
            # Check for keywords
            if "result" in title or "discus" in title:
                in_relevant_section = True
                found_any_relevant = True
                relevant_parts.append(line)
            else:
                in_relevant_section = False
        elif in_relevant_section:
            relevant_parts.append(line)
            
    if found_any_relevant:
        return "\n".join(relevant_parts)
    return text


