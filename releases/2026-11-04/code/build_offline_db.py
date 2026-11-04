import os
import glob
import json
import shutil
import sys
import time
import argparse
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

import numpy as np
from tqdm import tqdm

try:
    import pandas as pd
except Exception:
    pd = None

try:
    import pyarrow as pa
except Exception:
    pa = None

# Add current directory to sys.path to ensure imports work
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

import lancedb
from lancedb.pydantic import LanceModel, Vector
from lancedb.embeddings import get_registry
from lancedb.rerankers import RRFReranker
from langchain_text_splitters import RecursiveCharacterTextSplitter


# --- Default Configuration ---
LANCEDB_URI = "/data/chen/GNPS_SIM/pmc_lancedb_index"
TABLE_NAME = "papers_index"
EMBEDDING_MODEL_NAME = os.environ.get("OFFLINE_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
INPUT_DIR = "/data/chen/pubmed_corpus/pmc_extracted_text"

DEFAULT_CHUNK_SIZE = 1500
DEFAULT_CHUNK_OVERLAP = 100

# tqdm behavior for nohup / logs
TQDM_MININTERVAL = float(os.environ.get("TQDM_MININTERVAL", "5"))
TQDM_DISABLE = os.environ.get("TQDM_DISABLE", "0") == "1"


def make_pbar(*args, **kwargs):
    defaults = dict(
        file=sys.stdout,
        ascii=True,
        dynamic_ncols=True,
        mininterval=TQDM_MININTERVAL,
        disable=TQDM_DISABLE,
    )
    defaults.update(kwargs)
    return tqdm(*args, **defaults)


def log_runtime_info():
    print("=" * 80)
    print("Runtime info")
    print(f"python executable : {sys.executable}")
    print(f"python version    : {sys.version.split()[0]}")
    print(f"lancedb version   : {getattr(lancedb, '__version__', 'unknown')}")
    print(f"lancedb location  : {getattr(lancedb, '__file__', 'unknown')}")
    if pa is not None:
        print(f"pyarrow version   : {getattr(pa, '__version__', 'unknown')}")
        print(f"pyarrow location  : {getattr(pa, '__file__', 'unknown')}")
    else:
        print("pyarrow           : not importable")
    if pd is not None:
        print(f"pandas version    : {getattr(pd, '__version__', 'unknown')}")
    else:
        print("pandas            : not importable")
    print("=" * 80)


def get_existing_table_names(db) -> List[str]:
    """
    LanceDB compatibility helper.
    Supports both older `table_names()` and newer table-listing APIs.
    """
    if hasattr(db, "list_tables"):
        try:
            res = db.list_tables()

            if hasattr(res, "tables"):
                names = []
                for t in res.tables:
                    if isinstance(t, str):
                        names.append(t)
                    elif hasattr(t, "name"):
                        names.append(str(t.name))
                    elif isinstance(t, dict) and "name" in t:
                        names.append(str(t["name"]))
                    else:
                        names.append(str(t))
                return names

            try:
                return [str(x) for x in list(res)]
            except TypeError:
                pass
        except Exception:
            pass

    if hasattr(db, "table_names"):
        try:
            return [str(x) for x in db.table_names()]
        except Exception:
            pass

    raise AttributeError(
        "This LanceDB connection exposes neither usable list_tables() nor table_names()."
    )


def _safe_json_string(x: Any) -> str:
    if isinstance(x, str):
        return x if x.strip() else "{}"
    try:
        return json.dumps(x, ensure_ascii=True)
    except Exception:
        return "{}"


def _safe_float32_vector(vector: Any) -> List[float]:
    return np.asarray(vector, dtype=np.float32).tolist()


def make_text_splitter(chunk_size: int, chunk_overlap: int):
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )


def split_text_paragraph_aware(
    text: str,
    text_splitter: RecursiveCharacterTextSplitter,
    chunk_size: int,
    chunk_overlap: int,
) -> List[str]:
    """
    Prefer paragraph-coherent chunks for scientific text.
    Falls back to RecursiveCharacterTextSplitter only for oversized paragraphs.
    """
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p and p.strip()]
    if not paragraphs:
        return text_splitter.split_text(text)

    chunks: List[str] = []
    current_parts: List[str] = []
    current_len = 0

    def flush_current():
        nonlocal current_parts, current_len
        if current_parts:
            chunks.append("\n\n".join(current_parts).strip())
            current_parts = []
            current_len = 0

    for para in paragraphs:
        if len(para) > chunk_size:
            flush_current()
            chunks.extend(text_splitter.split_text(para))
            continue

        sep_len = 2 if current_parts else 0
        projected_len = current_len + sep_len + len(para)

        if projected_len <= chunk_size:
            current_parts.append(para)
            current_len = projected_len
            continue

        flush_current()

        if chunk_overlap > 0 and chunks:
            overlap_seed = chunks[-1][-min(chunk_overlap, len(chunks[-1])):].strip()
            if overlap_seed:
                current_parts = [overlap_seed, para]
                current_len = len(overlap_seed) + 2 + len(para)
                if current_len > chunk_size:
                    current_parts = [para]
                    current_len = len(para)
            else:
                current_parts = [para]
                current_len = len(para)
        else:
            current_parts = [para]
            current_len = len(para)

    flush_current()
    return chunks


# --- 1. Initialize Components ---
registry = get_registry()
try:
    func = registry.get("huggingface").create(name=EMBEDDING_MODEL_NAME, device="cuda")
except Exception as e:
    print(f"Warning: Could not load embedding model on CUDA: {e}. Falling back to CPU.")
    func = registry.get("huggingface").create(name=EMBEDDING_MODEL_NAME)


class PaperChunk(LanceModel):
    text: str
    vector: Vector(func.ndims())
    doc_id: str
    title: str
    year: str
    source: str
    chunk_id: int
    ner_results: str


reranker = RRFReranker()


def compute_embeddings_batched(
    texts: List[str],
    embed_batch_size: int,
    show_progress: bool = False,
    desc: str = "embed",
) -> List[List[float]]:
    vectors: List[List[float]] = []

    iterator = range(0, len(texts), embed_batch_size)
    if show_progress and len(texts) > embed_batch_size:
        iterator = make_pbar(
            iterator,
            total=(len(texts) + embed_batch_size - 1) // embed_batch_size,
            desc=desc,
            unit="emb_batch",
            position=2,
            leave=False,
        )

    for start in iterator:
        end = min(start + embed_batch_size, len(texts))
        batch_vecs = func.compute_source_embeddings(texts[start:end])
        vectors.extend(_safe_float32_vector(v) for v in batch_vecs)

    return vectors


def try_tbl_add(tbl, data, write_progress: bool) -> Optional[str]:
    """
    Try multiple add() signatures because LanceDB versions differ.
    Returns a short string describing the successful mode, or None if all failed.
    """
    candidate_kwargs = [
        {"mode": "append", "on_bad_vectors": "error", "progress": write_progress},
        {"mode": "append", "progress": write_progress},
        {"mode": "append", "on_bad_vectors": "error"},
        {"mode": "append"},
        {},
    ]

    for kwargs in candidate_kwargs:
        try:
            tbl.add(data, **kwargs)
            return f"kwargs={kwargs}"
        except TypeError:
            continue
        except Exception:
            continue

    return None


def add_rows_with_fallbacks(
    tbl,
    rows: List[Dict[str, Any]],
    write_progress: bool = False,
    allow_split_retry: bool = True,
    min_split_size: int = 1000,
    subbatch_label: str = "",
) -> str:
    """
    Safely add rows to LanceDB using multiple data formats.
    If a large batch fails, optionally split and retry recursively.
    """
    format_candidates = [("dict", rows)]

    if pd is not None:
        try:
            format_candidates.append(("pandas", pd.DataFrame(rows)))
        except Exception:
            pass

    if pa is not None:
        try:
            format_candidates.append(("pyarrow_table", pa.Table.from_pylist(rows)))
        except Exception:
            pass

    errors = []

    for fmt_name, payload in format_candidates:
        try:
            used = try_tbl_add(tbl, payload, write_progress=write_progress)
            if used is not None:
                return f"{fmt_name} ({used})"
            errors.append(f"{fmt_name}: all add() signatures failed")
        except Exception as e:
            errors.append(f"{fmt_name}: {type(e).__name__}: {e}")

    if allow_split_retry and len(rows) > min_split_size:
        mid = len(rows) // 2
        print(
            f"[WARN] add failed for {subbatch_label or 'subbatch'} with {len(rows)} rows; "
            f"splitting into {mid} and {len(rows) - mid}."
        )
        left = add_rows_with_fallbacks(
            tbl,
            rows[:mid],
            write_progress=write_progress,
            allow_split_retry=allow_split_retry,
            min_split_size=min_split_size,
            subbatch_label=f"{subbatch_label}:left",
        )
        right = add_rows_with_fallbacks(
            tbl,
            rows[mid:],
            write_progress=write_progress,
            allow_split_retry=allow_split_retry,
            min_split_size=min_split_size,
            subbatch_label=f"{subbatch_label}:right",
        )
        return f"split -> [{left}] + [{right}]"

    joined = "\n".join(errors)
    hint = ""
    if "set_column" in joined or "RecordBatch" in joined:
        hint = (
            "\nLikely LanceDB/PyArrow compatibility issue. "
            "Please verify the versions printed at startup and consider pinning "
            "a compatible pair or upgrading both in the same environment."
        )

    raise RuntimeError(
        f"Failed to add rows to LanceDB for {subbatch_label or 'subbatch'}.\n"
        f"Tried formats/signatures:\n{joined}{hint}"
    )


def _read_and_prepare_one_file_skip_ner(
    fpath: str,
    index_section_mode: str,
    chunk_size: int,
    chunk_overlap: int,
    filter_sections_fn=None,
    source: str = "PMC",
) -> Dict[str, Any]:
    """
    Read one file, extract metadata, split into chunks, and build rows.
    Intended for the --skip_ner path.
    """
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        title = "Unknown Title"
        year = "Unknown Year"

        for line in lines[:10]:
            if line.startswith("Title: "):
                title = line.replace("Title: ", "").strip()
            elif line.startswith("Year: "):
                year = line.replace("Year: ", "").strip()

        doc_id = os.path.basename(fpath)

        if index_section_mode == "results_discussion" and filter_sections_fn is not None:
            try:
                index_content = filter_sections_fn(content)
            except Exception:
                index_content = content
        else:
            index_content = content

        local_splitter = make_text_splitter(chunk_size, chunk_overlap)
        chunks = split_text_paragraph_aware(
            index_content,
            text_splitter=local_splitter,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        ner_json = "{}"
        rows = []
        for chunk_id, chunk_text in enumerate(chunks):
            contextualized_text = f"Title: {title}. {chunk_text}"
            rows.append({
                "text": contextualized_text,
                "doc_id": doc_id,
                "title": title,
                "year": year,
                "source": source,
                "chunk_id": chunk_id,
                "ner_results": ner_json,
            })

        return {
            "ok": True,
            "doc_id": doc_id,
            "rows": rows,
            "num_chunks": len(rows),
            "error": None,
        }

    except Exception as e:
        return {
            "ok": False,
            "doc_id": os.path.basename(fpath),
            "rows": [],
            "num_chunks": 0,
            "error": str(e),
        }


def _flush_rows_to_lancedb(
    tbl,
    rows: List[Dict[str, Any]],
    embed_batch_size: int,
    write_progress: bool,
    split_retry_min_rows: int,
    batch_num: int,
    flush_idx: int,
) -> Dict[str, Any]:
    """
    Embed and write one flush of rows.
    """
    t0 = time.time()

    texts = [row["text"] for row in rows]
    vectors = compute_embeddings_batched(
        texts,
        embed_batch_size=embed_batch_size,
        show_progress=False,
        desc=f"Batch {batch_num} embed",
    )

    materialized_rows = []
    for row, vector in zip(rows, vectors):
        out = dict(row)
        out["vector"] = vector
        materialized_rows.append(out)

    used_mode = add_rows_with_fallbacks(
        tbl,
        materialized_rows,
        write_progress=write_progress,
        allow_split_retry=True,
        min_split_size=split_retry_min_rows,
        subbatch_label=f"batch={batch_num},flush={flush_idx},rows={len(materialized_rows)}",
    )

    return {
        "written": len(materialized_rows),
        "mode": used_mode,
        "elapsed": time.time() - t0,
    }


def build_database(
    limit: int = None,
    shard_id: int = 0,
    num_shards: int = 1,
    gpu_id: int = 0,
    file_batch_size: int = 1000,
    progress_interval: int = 250,
    write_batch_size: int = 5000,
    embed_batch_size: int = 256,
    ner_batch_size: int = 256,
    linker_batch_size: int = 1024,
    skip_index: bool = False,
    index_section_mode: str = "full",
    skip_ner: bool = False,
    reuse_ner_db_path: str = "",
    reuse_ner_table: str = "papers_index",
    allow_wipe_db: bool = False,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    write_progress: bool = False,
    split_retry_min_rows: int = 1000,
    prep_workers: int = 8,
):
    extract_chemicals_with_nen_batch = None
    filter_sections_fn = None

    text_splitter = make_text_splitter(chunk_size, chunk_overlap)

    if not skip_ner or index_section_mode == "results_discussion":
        try:
            from chemical_ner_tool import extract_chemicals_with_nen_batch, _filter_relevant_sections
            filter_sections_fn = _filter_relevant_sections
        except ImportError:
            code_dir = os.path.join(os.getcwd(), "code")
            if os.path.exists(code_dir) and code_dir not in sys.path:
                sys.path.append(code_dir)
            from chemical_ner_tool import extract_chemicals_with_nen_batch, _filter_relevant_sections
            filter_sections_fn = _filter_relevant_sections

    if allow_wipe_db and os.path.exists(LANCEDB_URI) and shard_id == 0 and num_shards == 1:
        print(f"[DANGER] Removing existing database at {LANCEDB_URI} (allow_wipe_db=true)")
        shutil.rmtree(LANCEDB_URI)

    print(f"Embedding model: {EMBEDDING_MODEL_NAME}")
    print(f"Connecting to LanceDB at {LANCEDB_URI}...")
    db = lancedb.connect(LANCEDB_URI)

    existing_tables = get_existing_table_names(db)
    print(f"Existing tables: {existing_tables}")

    table_preexisted = TABLE_NAME in existing_tables
    if table_preexisted:
        print(f"Opening existing table: {TABLE_NAME}")
        tbl = db.open_table(TABLE_NAME)
    else:
        print(f"Creating new table: {TABLE_NAME}")
        tbl = db.create_table(TABLE_NAME, schema=PaperChunk, mode="overwrite")

    index_section_mode = str(index_section_mode or "full").strip().lower()
    if index_section_mode not in {"full", "results_discussion"}:
        raise ValueError(
            f"Unsupported index_section_mode={index_section_mode}; "
            f"use 'full' or 'results_discussion'."
        )

    print(f"Index section mode : {index_section_mode}")
    print(f"Chunk size         : {chunk_size}")
    print(f"Chunk overlap      : {chunk_overlap}")
    print(f"Write batch size   : {write_batch_size}")
    print(f"Embed batch size   : {embed_batch_size}")
    print(f"Write progress     : {write_progress}")
    print(f"Prep workers       : {prep_workers}")

    ner_lookup_table = None
    ner_lookup_cache: Dict[str, str] = {}

    if reuse_ner_db_path:
        try:
            ner_db = lancedb.connect(reuse_ner_db_path)
            ner_tables = get_existing_table_names(ner_db)
            if reuse_ner_table in ner_tables:
                ner_lookup_table = ner_db.open_table(reuse_ner_table)
                print(f"Reusing NER from {reuse_ner_db_path}:{reuse_ner_table}")
            else:
                print(f"Warning: reuse_ner_table not found: {reuse_ner_table}")
        except Exception as e:
            print(f"Warning: failed to connect reuse NER table: {e}")

    if skip_ner:
        if ner_lookup_table:
            print("NER mode: skip recompute; hydrate ner_results from reuse table by doc_id.")
        else:
            print("NER mode: skip recompute; ner_results will be empty JSON.")
    else:
        print("NER mode: recompute via extract_chemicals_with_nen_batch.")

    def _lookup_cached_ner(doc_id: str) -> str:
        if not doc_id:
            return "{}"
        if doc_id in ner_lookup_cache:
            return ner_lookup_cache[doc_id]
        if ner_lookup_table is None:
            ner_lookup_cache[doc_id] = "{}"
            return "{}"

        try:
            safe_doc_id = str(doc_id).replace("'", "''")
            rows = ner_lookup_table.search().where(f"doc_id = '{safe_doc_id}'").limit(1).to_pandas()
            if rows is not None and not rows.empty:
                val = rows.iloc[0].get("ner_results", "")
                if isinstance(val, str) and val.strip():
                    ner_lookup_cache[doc_id] = val
                    return val
                if val is not None and str(val).strip():
                    payload = json.dumps(val, ensure_ascii=True)
                    ner_lookup_cache[doc_id] = payload
                    return payload
        except Exception as e:
            print(f"Warning: failed NER lookup for doc_id={doc_id}: {e}")

        ner_lookup_cache[doc_id] = "{}"
        return "{}"

    current_input_dir = INPUT_DIR
    print(f"Scanning {current_input_dir} for text files...")
    if not os.path.exists(current_input_dir):
        print(f"Error: Input directory {current_input_dir} does not exist.")
        current_input_dir = "./pmc_extracted_text"
        print(f"Trying local directory: {current_input_dir}")

    txt_files = glob.glob(os.path.join(current_input_dir, "*.txt"))
    txt_files.sort()

    if not txt_files:
        print(f"No text files found in {current_input_dir}!")
        return

    total_files = len(txt_files)

    if num_shards > 1:
        shard_size = total_files // num_shards
        start_idx = shard_id * shard_size
        end_idx = start_idx + shard_size if shard_id < num_shards - 1 else total_files
        files_to_process = txt_files[start_idx:end_idx]
        print(f"Processing Shard {shard_id + 1}/{num_shards} (files {start_idx} to {end_idx})...")
    else:
        files_to_process = txt_files

    if limit:
        files_to_process = files_to_process[:limit]

    print(f"Processing {len(files_to_process)} files (Total available: {total_files})...")

    checkpoint_dir = "checkpoints"
    os.makedirs(checkpoint_dir, exist_ok=True)

    checkpoint_stub = f"{TABLE_NAME}_shard_{shard_id}_of_{num_shards}"
    checkpoint_path = os.path.join(checkpoint_dir, f"{checkpoint_stub}_progress.txt")

    start_offset = 0
    if os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, "r") as f:
                start_offset = int(f.read().strip())
            if not table_preexisted and start_offset > 0:
                print(
                    f"Warning: found checkpoint at {checkpoint_path}, but table {TABLE_NAME} "
                    f"was newly created. Ignoring checkpoint and starting from 0."
                )
                start_offset = 0
            else:
                print(f"Found checkpoint. Resuming Shard {shard_id} from file index {start_offset}...")
        except Exception as e:
            print(f"Error reading checkpoint: {e}. Starting from 0.")

    start_time = time.time()
    processed_count = start_offset

    overall_pbar = make_pbar(
        total=len(files_to_process),
        initial=start_offset,
        desc=f"Shard {shard_id + 1}/{num_shards} files",
        unit="file",
        position=0,
        leave=True,
    )

    try:
        for i in range(start_offset, len(files_to_process), file_batch_size):
            t_batch_start = time.time()
            batch_files = files_to_process[i:i + file_batch_size]
            batch_num = i // file_batch_size + 1

            print(
                f"\n[Batch {batch_num}] Starting {len(batch_files)} files "
                f"(global offset {i} / {len(files_to_process)})"
            )

            # Parallel fast path for --skip_ner
            if skip_ner and prep_workers > 1:
                t_parallel_start = time.time()
                write_elapsed = 0.0
                pending_rows: deque = deque()
                total_chunks = 0
                flushed_chunks = 0
                flush_idx = 0
                ok_files = 0

                print(
                    f"[Batch {batch_num}] Parallel prep enabled with {prep_workers} workers "
                    f"(skip_ner path)."
                )

                with ThreadPoolExecutor(max_workers=prep_workers) as ex:
                    futures = [
                        ex.submit(
                            _read_and_prepare_one_file_skip_ner,
                            fpath,
                            index_section_mode,
                            chunk_size,
                            chunk_overlap,
                            filter_sections_fn,
                            "PMC",
                        )
                        for fpath in batch_files
                    ]

                    prep_pbar = make_pbar(
                        as_completed(futures),
                        total=len(futures),
                        desc=f"Batch {batch_num} prep+write",
                        unit="file",
                        position=1,
                        leave=False,
                    )

                    for done_idx, fut in enumerate(prep_pbar, 1):
                        res = fut.result()

                        if not res["ok"]:
                            print(f"Error preparing {res['doc_id']}: {res['error']}")
                            continue

                        ok_files += 1
                        rows = res["rows"]
                        total_chunks += res["num_chunks"]
                        pending_rows.extend(rows)

                        while len(pending_rows) >= write_batch_size:
                            flush_idx += 1
                            flush_rows = [pending_rows.popleft() for _ in range(write_batch_size)]

                            out = _flush_rows_to_lancedb(
                                tbl,
                                flush_rows,
                                embed_batch_size=embed_batch_size,
                                write_progress=write_progress,
                                split_retry_min_rows=split_retry_min_rows,
                                batch_num=batch_num,
                                flush_idx=flush_idx,
                            )
                            flushed_chunks += out["written"]
                            write_elapsed += out["elapsed"]

                        prep_pbar.set_postfix(
                            docs=done_idx,
                            ok=ok_files,
                            chunks=total_chunks,
                            queued=len(pending_rows),
                            written=flushed_chunks,
                            refresh=False,
                        )

                if pending_rows:
                    flush_idx += 1
                    flush_rows = list(pending_rows)
                    out = _flush_rows_to_lancedb(
                        tbl,
                        flush_rows,
                        embed_batch_size=embed_batch_size,
                        write_progress=write_progress,
                        split_retry_min_rows=split_retry_min_rows,
                        batch_num=batch_num,
                        flush_idx=flush_idx,
                    )
                    flushed_chunks += out["written"]
                    write_elapsed += out["elapsed"]
                    pending_rows.clear()

                t_parallel_end = time.time()

                next_start = i + len(batch_files)
                with open(checkpoint_path, "w") as f:
                    f.write(str(next_start))

                processed_count += len(batch_files)
                overall_pbar.update(len(batch_files))
                overall_pbar.set_postfix(batch=batch_num, refresh=False)

                elapsed = time.time() - start_time
                avg_time_per_file = elapsed / processed_count if processed_count > 0 else 0.0
                remaining_files = len(files_to_process) - processed_count
                est_remaining = remaining_files * avg_time_per_file

                total_batch_time = t_parallel_end - t_parallel_start
                prep_only_est = max(0.0, total_batch_time - write_elapsed)

                print(f"Batch {batch_num}: {len(batch_files)} files. Total: {total_batch_time:.2f}s")
                print(f"  Parallel prep: {prep_only_est:.2f}s, DB(embed+write): {write_elapsed:.2f}s")
                print(f"  Prepared chunks: {total_chunks}, Written chunks: {flushed_chunks}, Flushes: {flush_idx}")
                print(
                    f"Processed {processed_count}/{len(files_to_process)} files. "
                    f"Avg: {avg_time_per_file:.2f}s/file. "
                    f"Est remaining: {est_remaining / 60:.1f} min. "
                    f"Total Est (for {total_files} files): {(total_files * avg_time_per_file) / 3600:.1f} hours"
                )

                continue

            # Serial path (used for non-skip_ner or prep_workers <= 1)
            batch_contents = []
            batch_metadata = []

            # 1. Read
            t_read_start = time.time()
            read_pbar = make_pbar(
                batch_files,
                desc=f"Batch {batch_num} read",
                unit="file",
                position=1,
                leave=False,
            )

            for fpath in read_pbar:
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()

                    lines = content.split("\n")
                    title = "Unknown Title"
                    year = "Unknown Year"

                    for line in lines[:10]:
                        if line.startswith("Title: "):
                            title = line.replace("Title: ", "").strip()
                        elif line.startswith("Year: "):
                            year = line.replace("Year: ", "").strip()

                    doc_id = os.path.basename(fpath)

                    batch_contents.append(content)
                    batch_metadata.append({
                        "doc_id": doc_id,
                        "title": title,
                        "year": year,
                        "source": "PMC",
                    })
                except Exception as e:
                    print(f"Error reading {fpath}: {e}")
                    continue

            t_read_end = time.time()

            if not batch_contents:
                continue

            # 2. NER
            t_ner_start = time.time()
            if skip_ner:
                ner_results_list = [_lookup_cached_ner(meta["doc_id"]) for meta in batch_metadata]
            else:
                try:
                    ner_results_list = extract_chemicals_with_nen_batch(
                        batch_contents,
                        verbose=True,
                        ner_gpu=gpu_id,
                        linker_gpu=gpu_id,
                        ner_mini_batch_size=ner_batch_size,
                        linker_mini_batch_size=linker_batch_size,
                        disable_linking=False,
                    )
                except Exception as e:
                    print(f"Error in NER batch: {e}")
                    ner_results_list = [{}] * len(batch_contents)
            t_ner_end = time.time()

            # 3. Prepare rows
            t_prep_start = time.time()
            data_to_index = []

            prep_pbar = make_pbar(
                enumerate(batch_contents),
                total=len(batch_contents),
                desc=f"Batch {batch_num} prep",
                unit="file",
                position=1,
                leave=False,
            )

            for idx, content in prep_pbar:
                meta = batch_metadata[idx]
                ner_res = ner_results_list[idx] if idx < len(ner_results_list) else {}
                ner_json = _safe_json_string(ner_res)

                if index_section_mode == "results_discussion":
                    index_content = filter_sections_fn(content) if filter_sections_fn else content
                else:
                    index_content = content

                chunks = split_text_paragraph_aware(
                    index_content,
                    text_splitter=text_splitter,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )

                for chunk_id, chunk_text in enumerate(chunks):
                    contextualized_text = f"Title: {meta['title']}. {chunk_text}"
                    data_to_index.append({
                        "text": contextualized_text,
                        "doc_id": meta["doc_id"],
                        "title": meta["title"],
                        "year": meta["year"],
                        "source": meta["source"],
                        "chunk_id": chunk_id,
                        "ner_results": ner_json,
                    })

                prep_pbar.set_postfix(docs=idx + 1, chunks=len(data_to_index), refresh=False)

            t_prep_end = time.time()

            # 4. Embedding + write
            t_db_start = time.time()
            if data_to_index:
                total_chunks = len(data_to_index)
                effective_write_batch_size = total_chunks if write_batch_size <= 0 else write_batch_size
                num_write_batches = (total_chunks + effective_write_batch_size - 1) // effective_write_batch_size

                print(
                    f"[Batch {batch_num}] Writing {total_chunks} chunks to LanceDB "
                    f"in {num_write_batches} sub-batches of up to {effective_write_batch_size}..."
                )

                write_ranges = range(0, total_chunks, effective_write_batch_size)
                write_pbar = make_pbar(
                    write_ranges,
                    total=num_write_batches,
                    desc=f"Batch {batch_num} write",
                    unit="subbatch",
                    position=1,
                    leave=False,
                )

                total_written = 0
                for write_start in write_pbar:
                    write_end = min(write_start + effective_write_batch_size, total_chunks)
                    write_slice = data_to_index[write_start:write_end]

                    write_pbar.set_postfix(
                        chunk_start=write_start,
                        chunk_end=write_end,
                        refresh=False,
                    )

                    texts = [row["text"] for row in write_slice]
                    vectors = compute_embeddings_batched(
                        texts,
                        embed_batch_size=embed_batch_size,
                        show_progress=False,
                        desc=f"Batch {batch_num} embed",
                    )

                    materialized_rows = []
                    for row, vector in zip(write_slice, vectors):
                        out = dict(row)
                        out["vector"] = vector
                        materialized_rows.append(out)

                    used_mode = add_rows_with_fallbacks(
                        tbl,
                        materialized_rows,
                        write_progress=write_progress,
                        allow_split_retry=True,
                        min_split_size=split_retry_min_rows,
                        subbatch_label=f"batch={batch_num},rows={write_start}:{write_end}",
                    )
                    total_written += len(materialized_rows)

                    write_pbar.set_postfix(
                        chunk_start=write_start,
                        chunk_end=write_end,
                        written=total_written,
                        mode=used_mode,
                        refresh=False,
                    )

            t_db_end = time.time()

            next_start = i + len(batch_files)
            with open(checkpoint_path, "w") as f:
                f.write(str(next_start))

            processed_count += len(batch_files)
            overall_pbar.update(len(batch_files))
            overall_pbar.set_postfix(batch=batch_num, refresh=False)

            elapsed = time.time() - start_time
            avg_time_per_file = elapsed / processed_count if processed_count > 0 else 0.0
            remaining_files = len(files_to_process) - processed_count
            est_remaining = remaining_files * avg_time_per_file

            t_read = t_read_end - t_read_start
            t_ner = t_ner_end - t_ner_start
            t_prep = t_prep_end - t_prep_start
            t_db = t_db_end - t_db_start
            t_total_batch = time.time() - t_batch_start

            print(f"Batch {batch_num}: {len(batch_files)} files. Total: {t_total_batch:.2f}s")
            print(f"  Read: {t_read:.2f}s, NER+Link: {t_ner:.2f}s, Prep: {t_prep:.2f}s, DB: {t_db:.2f}s")
            print(
                f"Processed {processed_count}/{len(files_to_process)} files. "
                f"Avg: {avg_time_per_file:.2f}s/file. "
                f"Est remaining: {est_remaining / 60:.1f} min. "
                f"Total Est (for {total_files} files): {(total_files * avg_time_per_file) / 3600:.1f} hours"
            )

    finally:
        overall_pbar.close()

    if not skip_index:
        print("Building FTS Index...")
        tbl.create_fts_index("text", replace=True)
        print("Indexing complete.")
    else:
        print("Skipping FTS Index build as requested.")


def search_papers(query: str, query_type: str = "vector"):
    print(f"\n--- Running Search for: '{query}' (type={query_type}) ---")

    db = lancedb.connect(LANCEDB_URI)
    if TABLE_NAME not in get_existing_table_names(db):
        print(f"Table {TABLE_NAME} not found.")
        return

    tbl = db.open_table(TABLE_NAME)

    query_type = (query_type or "vector").strip().lower()

    if query_type == "vector":
        qvec = func.compute_source_embeddings([query])[0]
        qvec = _safe_float32_vector(qvec)

        results = (
            tbl.search(qvec, vector_column_name="vector", query_type="vector")
            .limit(3)
            .to_pandas()
        )

    elif query_type == "fts":
        results = (
            tbl.search(query, query_type="fts")
            .limit(3)
            .to_pandas()
        )

    else:
        raise ValueError("query_type must be one of: 'vector', 'fts'")

    if results.empty:
        print("No results found.")
        return

    for _, row in results.iterrows():
        doc_id = row.get("doc_id", "N/A")
        title = row.get("title", "N/A")
        chunk_text = row.get("text", "")
        ner_res = row.get("ner_results", "")
        distance = row.get("_distance", None)
        score = row.get("_relevance_score", None)

        if distance is not None:
            print(f"\nRANK (Distance: {distance})")
        elif score is not None:
            print(f"\nRANK (Score: {score})")
        else:
            print("\nRANK")

        print(f"  ID: {doc_id}")
        print(f"  Title: {title}")
        print(f"  Match: {chunk_text[:300]}...")
        print(f"  NER Results (preview): {str(ner_res)[:200]}...")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build offline LanceDB from PMC text files.")

    parser.add_argument("--limit", type=int, default=None, help="Limit number of files to process.")
    parser.add_argument("--shard_id", type=int, default=0, help="Shard ID (0-indexed) for parallel processing.")
    parser.add_argument("--num_shards", type=int, default=1, help="Total number of shards.")
    parser.add_argument("--gpu_id", type=int, default=0, help="GPU ID to use (relative to visible devices).")

    parser.add_argument("--file_batch_size", type=int, default=2000, help="Number of files to read per batch.")
    parser.add_argument("--progress_interval", type=int, default=250, help="Legacy arg; retained for compatibility.")
    parser.add_argument("--write_batch_size", type=int, default=5000, help="How many prepared chunks to add per write call.")
    parser.add_argument("--embed_batch_size", type=int, default=256, help="Mini-batch size for embedding model.")
    parser.add_argument("--ner_batch_size", type=int, default=320, help="Mini-batch size for NER model.")
    parser.add_argument("--linker_batch_size", type=int, default=2048, help="Mini-batch size for Linker model.")

    parser.add_argument("--chunk_size", type=int, default=DEFAULT_CHUNK_SIZE, help="Chunk size for splitting.")
    parser.add_argument("--chunk_overlap", type=int, default=DEFAULT_CHUNK_OVERLAP, help="Chunk overlap for splitting.")
    parser.add_argument("--write_progress", action="store_true", help="Ask LanceDB to show write progress if supported.")
    parser.add_argument("--split_retry_min_rows", type=int, default=1000, help="If add fails, split retries only above this row count.")
    parser.add_argument(
        "--prep_workers",
        type=int,
        default=max(4, min(16, (os.cpu_count() or 8) // 2)),
        help="Number of CPU worker threads for file read + chunk prep in --skip_ner mode.",
    )

    parser.add_argument("--input_dir", type=str, default=INPUT_DIR, help="Directory containing text files to process.")
    parser.add_argument("--table_name", type=str, default="papers_index", help="Name of the LanceDB table to write to.")
    parser.add_argument("--skip_index", action="store_true", help="Skip building FTS index at the end.")

    parser.add_argument(
        "--index_section_mode",
        type=str,
        default="full",
        choices=["full", "results_discussion"],
        help="Text scope used for indexing chunks.",
    )
    parser.add_argument("--skip_ner", action="store_true", help="Do not recompute NER during indexing.")
    parser.add_argument("--reuse_ner_db_path", type=str, default="", help="Optional LanceDB path to reuse cached ner_results by doc_id.")
    parser.add_argument("--reuse_ner_table", type=str, default="papers_index", help="Table name for reused ner_results.")
    parser.add_argument("--allow_wipe_db", action="store_true", help="Dangerous: remove the DB path before building.")
    parser.add_argument("--run_demo_search", action="store_true", help="Run a couple of manual vector search demos at the end.")

    args = parser.parse_args()

    INPUT_DIR = args.input_dir
    TABLE_NAME = args.table_name

    log_runtime_info()

    try:
        build_database(
            limit=args.limit,
            shard_id=args.shard_id,
            num_shards=args.num_shards,
            gpu_id=args.gpu_id,
            file_batch_size=args.file_batch_size,
            progress_interval=args.progress_interval,
            write_batch_size=args.write_batch_size,
            embed_batch_size=args.embed_batch_size,
            ner_batch_size=args.ner_batch_size,
            linker_batch_size=args.linker_batch_size,
            skip_index=args.skip_index,
            index_section_mode=args.index_section_mode,
            skip_ner=args.skip_ner,
            reuse_ner_db_path=args.reuse_ner_db_path,
            reuse_ner_table=args.reuse_ner_table,
            allow_wipe_db=args.allow_wipe_db,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            write_progress=args.write_progress,
            split_retry_min_rows=args.split_retry_min_rows,
            prep_workers=args.prep_workers,
        )
    except Exception as e:
        print("\n[FATAL] build_database crashed.")
        print(f"Type   : {type(e).__name__}")
        print(f"Error  : {e}")
        print("Traceback:")
        traceback.print_exc()
        raise

    if args.run_demo_search and args.shard_id == 0:
        search_papers("chronic pain stress", query_type="vector")
        search_papers("brucellosis", query_type="vector")
