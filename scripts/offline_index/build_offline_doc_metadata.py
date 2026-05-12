#!/usr/bin/env python3
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import pathlib
import re
import time
import zlib
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

try:
    import sqlite3 as _sqlite_mod
    SQLITE_BACKEND = "sqlite3"
except Exception:
    _sqlite_mod = None
    SQLITE_BACKEND = ""
if _sqlite_mod is None:
    import apsw as _sqlite_mod  # type: ignore
    SQLITE_BACKEND = "apsw"

TEXT_EXTS = {".txt", ".md", ".text", ".xml", ".nxml", ".html", ".htm"}
PDF_EXTS = {".pdf"}
ALL_EXTS = TEXT_EXTS | PDF_EXTS
PMC_BASENAME_RE = re.compile(r"^(PMC\d+)(?:\..*)?$", re.I)
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", flags=re.I)
PMID_RE = re.compile(r"\bPMID\s*:?\s*(\d+)\b", flags=re.I)
PMCID_RE = re.compile(r"\b(PMC\d+)\b", flags=re.I)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_WORKER_ROOT: Optional[pathlib.Path] = None
_WORKER_HEAD_CHARS = 0
_WORKER_FILENAME_PMCID_ONLY = True


def clean_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def detect_title(lines: List[str], fallback_name: str) -> str:
    for line in lines[:20]:
        low = line.lower().strip()
        if low.startswith("title:"):
            title = clean_ws(line.split(":", 1)[1])
            if title:
                return title
    for line in lines[:20]:
        line = clean_ws(line)
        if not line:
            continue
        if 15 < len(line) < 240 and line.lower() not in {"abstract", "introduction", "background"}:
            return line
    return fallback_name


def detect_abstract(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    m = re.search(
        r"\n\s*abstract\s*\n(.{80,2500}?)(?:\n\s*(introduction|background|methods|materials|results|discussion)\s*\n)",
        text,
        flags=re.I | re.S,
    )
    if m:
        return clean_ws(m.group(1))[:3000]
    paras = [clean_ws(p) for p in re.split(r"\n{2,}", text) if clean_ws(p)]
    for para in paras[:6]:
        if len(para) >= 120:
            return para[:3000]
    return ""


def init_db(path: pathlib.Path, rebuild: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    if SQLITE_BACKEND == "sqlite3":
        conn = _sqlite_mod.connect(str(path))
        conn.row_factory = _sqlite_mod.Row
    else:
        conn = _sqlite_mod.Connection(str(path))
    if rebuild:
        conn.execute("DROP TABLE IF EXISTS documents")
        conn.execute("DROP TABLE IF EXISTS documents_fts")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            doc_id TEXT PRIMARY KEY,
            title TEXT,
            abstract TEXT,
            doi TEXT,
            pmid TEXT,
            pmcid TEXT,
            year TEXT,
            journal TEXT,
            authors TEXT,
            source TEXT,
            url TEXT,
            local_txt_path TEXT,
            local_pdf_path TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            doc_id UNINDEXED,
            title,
            abstract,
            identifiers,
            tokenize='unicode61'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_doi ON documents(doi)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_pmid ON documents(pmid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_pmcid ON documents(pmcid)")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-200000")
    except Exception:
        pass
    commit_if_supported(conn)
    return conn


def commit_if_supported(conn) -> None:
    if hasattr(conn, "commit"):
        conn.commit()


def iter_local_docs(root: pathlib.Path, recursive: bool) -> Iterator[pathlib.Path]:
    if recursive:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in ALL_EXTS:
                yield path
        return
    with os.scandir(root) as it:
        for entry in it:
            if entry.is_file():
                path = pathlib.Path(entry.path)
                if path.suffix.lower() in ALL_EXTS:
                    yield path


def fast_doc_key(path: pathlib.Path) -> str:
    m = PMC_BASENAME_RE.match(path.name)
    if m:
        return f"pmcid:{m.group(1).upper()}"
    stem = path.stem.lower()
    stem = re.sub(r"\.(fulltext|main|article)$", "", stem)
    stem = re.sub(r"[_\-\s]+", "_", stem)
    return f"stem:{stem}"


def shard_for_doc_id(doc_id: str, shard_count: int) -> int:
    if shard_count <= 1:
        return 0
    return zlib.crc32(doc_id.encode("utf-8")) % shard_count


def load_existing_doc_ids(conn, threshold: int = 1000000) -> Optional[set[str]]:
    try:
        if SQLITE_BACKEND == "sqlite3":
            cur = conn.execute("select count(*) from documents")
            row_count = cur.fetchone()[0]
            if row_count > threshold:
                return None
            cur = conn.execute("select doc_id from documents")
            return {row[0] for row in cur.fetchall()}
        cur = conn.cursor()
        row_count = next(cur.execute("select count(*) from documents"))[0]
        if row_count > threshold:
            return None
        cur = conn.cursor()
        return {row[0] for row in cur.execute("select doc_id from documents")}
    except Exception:
        return None


def doc_exists(conn, doc_id: str) -> bool:
    try:
        if SQLITE_BACKEND == "sqlite3":
            cur = conn.execute("select 1 from documents where doc_id = ? limit 1", (doc_id,))
            return cur.fetchone() is not None
        cur = conn.cursor()
        return next(cur.execute("select 1 from documents where doc_id = ? limit 1", (doc_id,)), None) is not None
    except Exception:
        return False


def read_head(path: pathlib.Path, head_chars: int) -> str:
    if head_chars <= 0 or path.suffix.lower() not in TEXT_EXTS:
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            return fh.read(head_chars)
    except Exception:
        return ""


def path_to_url(doi: str, pmid: str, pmcid: str) -> str:
    if doi:
        return f"https://doi.org/{doi}"
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    if pmcid:
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
    return ""


def build_record_from_path(root: pathlib.Path, path: pathlib.Path, head_chars: int, filename_pmcid_only: bool) -> Tuple[Tuple[str, ...], str]:
    rel = str(path.relative_to(root))
    doc_id = fast_doc_key(path)
    suffix = path.suffix.lower()
    local_txt_path = rel if suffix in TEXT_EXTS else ""
    local_pdf_path = rel if suffix in PDF_EXTS else ""

    fallback_name = path.stem.replace("_", " ").replace("-", " ")
    pmcid = ""
    pmid = ""
    doi = ""
    year = ""
    journal = ""
    authors = ""
    abstract = ""
    title = fallback_name

    m = PMC_BASENAME_RE.match(path.name)
    if m:
        pmcid = m.group(1).upper()

    head = ""
    if not filename_pmcid_only or not pmcid:
        head = read_head(path, head_chars)
    elif head_chars > 0 and suffix in TEXT_EXTS:
        head = read_head(path, min(head_chars, 4096))

    if head:
        lines = [line.strip() for line in head.splitlines() if line.strip()]
        title = detect_title(lines, fallback_name)
        abstract = detect_abstract(head)
        if not doi:
            m = DOI_RE.search(head)
            doi = m.group(1).strip() if m else ""
        m = PMID_RE.search(head)
        pmid = m.group(1).strip() if m else ""
        if not pmcid:
            m = PMCID_RE.search(rel + "\n" + head)
            pmcid = m.group(1).upper() if m else ""
        m = YEAR_RE.search(head)
        year = m.group(0) if m else ""
        m = re.search(r"\n\s*journal\s*:?\s*(.+)", head, flags=re.I)
        if m:
            journal = clean_ws(m.group(1))[:300]
        m = re.search(r"\n\s*authors?\s*:?\s*(.+)", head, flags=re.I)
        if m:
            authors = clean_ws(m.group(1))[:500]

    url = path_to_url(doi, pmid, pmcid)
    rec = (
        doc_id,
        title,
        abstract,
        doi,
        pmid,
        pmcid,
        year,
        journal,
        authors,
        "offline_metadata",
        url,
        local_txt_path,
        local_pdf_path,
    )
    identifiers = " ".join([x for x in [doi, pmid, pmcid, doc_id] if x]).strip()
    return rec, identifiers


def init_worker(root_str: str, head_chars: int, filename_pmcid_only: bool) -> None:
    global _WORKER_ROOT, _WORKER_HEAD_CHARS, _WORKER_FILENAME_PMCID_ONLY
    _WORKER_ROOT = pathlib.Path(root_str)
    _WORKER_HEAD_CHARS = head_chars
    _WORKER_FILENAME_PMCID_ONLY = filename_pmcid_only


def build_record_from_relpath(rel_path: str) -> Tuple[str, Tuple[str, ...], str]:
    if _WORKER_ROOT is None:
        raise RuntimeError("Worker not initialized")
    path = _WORKER_ROOT / rel_path
    rec, identifiers = build_record_from_path(
        root=_WORKER_ROOT,
        path=path,
        head_chars=_WORKER_HEAD_CHARS,
        filename_pmcid_only=_WORKER_FILENAME_PMCID_ONLY,
    )
    return rec[0], rec, identifiers


def upsert_record(conn, rec: Tuple[str, ...], identifiers: str, skip_fts_during_ingest: bool = False) -> None:
    conn.execute(
        """
        INSERT INTO documents (
            doc_id, title, abstract, doi, pmid, pmcid, year, journal,
            authors, source, url, local_txt_path, local_pdf_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(doc_id) DO UPDATE SET
            title = CASE WHEN excluded.title != '' THEN excluded.title ELSE documents.title END,
            abstract = CASE WHEN excluded.abstract != '' THEN excluded.abstract ELSE documents.abstract END,
            doi = CASE WHEN excluded.doi != '' THEN excluded.doi ELSE documents.doi END,
            pmid = CASE WHEN excluded.pmid != '' THEN excluded.pmid ELSE documents.pmid END,
            pmcid = CASE WHEN excluded.pmcid != '' THEN excluded.pmcid ELSE documents.pmcid END,
            year = CASE WHEN excluded.year != '' THEN excluded.year ELSE documents.year END,
            journal = CASE WHEN excluded.journal != '' THEN excluded.journal ELSE documents.journal END,
            authors = CASE WHEN excluded.authors != '' THEN excluded.authors ELSE documents.authors END,
            source = excluded.source,
            url = CASE WHEN excluded.url != '' THEN excluded.url ELSE documents.url END,
            local_txt_path = CASE WHEN excluded.local_txt_path != '' THEN excluded.local_txt_path ELSE documents.local_txt_path END,
            local_pdf_path = CASE WHEN excluded.local_pdf_path != '' THEN excluded.local_pdf_path ELSE documents.local_pdf_path END
        """,
        rec,
    )
    if skip_fts_during_ingest:
        return
    conn.execute("DELETE FROM documents_fts WHERE doc_id = ?", (rec[0],))
    conn.execute(
        "INSERT INTO documents_fts(doc_id, title, abstract, identifiers) VALUES (?, ?, ?, ?)",
        (rec[0], rec[1], rec[2], identifiers),
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Build SQLite doc-level metadata DB from local full-text files.")
    ap.add_argument("--local-doc-dir", required=True)
    ap.add_argument("--db-path", required=True)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--recursive", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--commit-every", type=int, default=50000)
    ap.add_argument("--progress-every", type=int, default=50000)
    ap.add_argument("--head-chars", type=int, default=4096)
    ap.add_argument("--resume", action="store_true", help="Skip doc_ids already present in the DB.")
    ap.add_argument("--filename-pmcid-only", action="store_true", default=True, help="Prefer PMCID from filename and avoid unnecessary file parsing.")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--chunksize", type=int, default=512)
    ap.add_argument("--skip-fts-during-ingest", action="store_true")
    ap.add_argument("--shard-count", type=int, default=1)
    ap.add_argument("--shard-index", type=int, default=0)
    args = ap.parse_args()

    if args.shard_count < 1:
        raise ValueError("--shard-count must be >= 1")
    if not (0 <= args.shard_index < args.shard_count):
        raise ValueError("--shard-index must satisfy 0 <= shard-index < shard-count")

    root = pathlib.Path(args.local_doc_dir).resolve()
    conn = init_db(pathlib.Path(args.db_path).resolve(), rebuild=args.rebuild)

    existing_ids = load_existing_doc_ids(conn) if args.resume and not args.rebuild else None
    t0 = time.time()
    scanned = 0
    written = 0
    skipped_existing = 0
    last_progress_bucket = -1

    def maybe_print_progress() -> None:
        nonlocal last_progress_bucket
        if args.progress_every <= 0:
            return
        bucket = scanned // args.progress_every
        if bucket <= last_progress_bucket or scanned == 0:
            return
        last_progress_bucket = bucket
        if scanned >= bucket * args.progress_every:
            elapsed = time.time() - t0
            rate = scanned / elapsed if elapsed > 0 else 0.0
            print(
                f"scanned={scanned} written={written} skipped_existing={skipped_existing} "
                f"elapsed_s={elapsed:.1f} rate_files_per_s={rate:.1f}",
                flush=True,
            )

    def iter_pending_relpaths() -> Iterator[str]:
        nonlocal scanned, skipped_existing
        for path in iter_local_docs(root, recursive=args.recursive):
            scanned += 1
            doc_id = fast_doc_key(path)
            if shard_for_doc_id(doc_id, args.shard_count) != args.shard_index:
                maybe_print_progress()
                if args.limit and scanned >= args.limit:
                    return
                continue
            if existing_ids is not None:
                if doc_id in existing_ids:
                    skipped_existing += 1
                    maybe_print_progress()
                    if args.limit and scanned >= args.limit:
                        return
                    continue
            elif args.resume and doc_exists(conn, doc_id):
                skipped_existing += 1
                maybe_print_progress()
                if args.limit and scanned >= args.limit:
                    return
                continue
            yield str(path.relative_to(root))
            if args.limit and scanned >= args.limit:
                return

    worker_count = max(1, int(args.workers))
    if worker_count == 1:
        init_worker(str(root), args.head_chars, args.filename_pmcid_only)
        for doc_id, rec, identifiers in (build_record_from_relpath(rel_path) for rel_path in iter_pending_relpaths()):
            upsert_record(conn, rec, identifiers, skip_fts_during_ingest=args.skip_fts_during_ingest)
            written += 1
            if existing_ids is not None:
                existing_ids.add(doc_id)
            if written % args.commit_every == 0:
                commit_if_supported(conn)
            maybe_print_progress()
    else:
        with mp.Pool(
            processes=worker_count,
            initializer=init_worker,
            initargs=(str(root), args.head_chars, args.filename_pmcid_only),
        ) as pool:
            for doc_id, rec, identifiers in pool.imap_unordered(
                build_record_from_relpath,
                iter_pending_relpaths(),
                chunksize=max(1, int(args.chunksize)),
            ):
                upsert_record(conn, rec, identifiers, skip_fts_during_ingest=args.skip_fts_during_ingest)
                written += 1
                if existing_ids is not None:
                    existing_ids.add(doc_id)
                if written % args.commit_every == 0:
                    commit_if_supported(conn)
                maybe_print_progress()

    commit_if_supported(conn)
    elapsed = time.time() - t0
    print(
        f"done scanned={scanned} written={written} skipped_existing={skipped_existing} elapsed_s={elapsed:.1f} db={args.db_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
