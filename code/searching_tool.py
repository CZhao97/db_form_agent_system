#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Full-text literature fetcher (PubMed/PMC + preprints) with Europe PMC + Unpaywall.
- PubMed search biased to "Free full text".
- Europe PMC search (articles + preprints) with JATS (/fullTextXML) extraction.
- Unpaywall fallback for any DOI → best OA PDF/HTML.
- arXiv, medRxiv, ChemRxiv (via Figshare) kept.
- Saves only items with has_fulltext=True (JATS or parsed text).

Speed-ups in this version:
- Parallel source searches across queries & sources (ThreadPoolExecutor).
- Parallel Phase-1 enrich (JATS / Unpaywall lookups) with backoff.
- Docling-from-URL for PDFs (no pre-download), with graceful fallback to pdfminer.

Knobs:
- max_search_workers: parallelism for search fan-out.
- max_phase1_workers: parallelism for JATS/Unpaywall enrichment.
- max_parallel_docling: parallel Docling conversions (PDF URLs).

Notes:
- If Docling is unavailable, the code silently falls back to pdfminer.
- If Docling import works, we try directly from the PDF URL first.
"""

from __future__ import annotations

import os, re, csv, json, time, string, logging, pathlib, hashlib, io
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Type, Any
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import xml.etree.ElementTree as ET
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pydantic import BaseModel, Field

from Bio import Entrez
from pdfminer.high_level import extract_text as pdf_extract_text
from langchain.tools import BaseTool

# -------------------- Optional Docling --------------------
try:
    from docling.document_converter import DocumentConverter
    _DOCLING_AVAILABLE = True
except Exception:
    DocumentConverter = None  # type: ignore
    _DOCLING_AVAILABLE = False

log = logging.getLogger("fulltext_journal_search")
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# -------------------------------------------------------------------
# ContextVar to carry the per-run session directory (env-free, safe)
# -------------------------------------------------------------------
_SESSION_DIR_CVAR: ContextVar[Optional[str]] = ContextVar("SEARCH_SESSION_DIR", default=None)

# ----------------------------- Models & Utilities -----------------------------
class FullTextJournalSearchInput(BaseModel):
    query: str | List[str] = Field(..., description="Academic search terms, '||' separated or JSON list for multi-query")
    max_results: int = Field(20, description="Maximum number of results to return (per source, global default)")
    
    # --- START CHANGE ---
    # Per-source 'k' values. If not set, the global 'max_results' is used.
    max_results_pubmed: Optional[int] = Field(None, description="Max results for PubMed (overrides global max_results)")
    max_results_eupmc: Optional[int] = Field(None, description="Max results for Europe PMC (overrides global max_results)")
    max_results_arxiv: Optional[int] = Field(None, description="Max results for arXiv (overrides global max_results)")
    max_results_medrxiv: Optional[int] = Field(None, description="Max results for medRxiv (overrides global max_results)")
    max_results_chemrxiv: Optional[int] = Field(None, description="Max results for ChemRxiv (overrides global max_results)")
    # --- END CHANGE ---

    # Date range filters
    min_date: Optional[str] = Field(None, description="Minimum publication date (YYYY, YYYY/MM, or YYYY/MM/DD format)")
    max_date: Optional[str] = Field(None, description="Maximum publication date (YYYY, YYYY/MM, or YYYY/MM/DD format)")

    include_preprints: bool = Field(True, description="Include preprints")
    include_pubmed: bool = Field(True, description="Include PubMed/PMC")
    include_arxiv: bool = Field(False, description="Include arXiv (off by default)")
    include_medrxiv: bool = Field(True, description="Include medRxiv")
    include_chemrxiv: bool = Field(True, description="Include ChemRxiv (via Figshare)")
    include_eupmc: bool = Field(True, description="Include Europe PMC search (JATS fullTextXML when available)")
    use_pubmed_free_fulltext_bias: bool = Field(True, description="Bias PubMed query to Free full text[Filter]")

    # Set more reasonable, conservative defaults to avoid rate-limiting
    max_parallel_downloads: int = Field(4, description="(Legacy) kept for backward compat; not used if Docling is on")
    max_search_workers: int = Field(2, description="Max concurrent search tasks across sources & queries")
    max_phase1_workers: int = Field(8, description="Max concurrent JATS/Unpaywall enrich tasks")
    max_parallel_docling: int = Field(4, description="Max concurrent Docling URL conversions")
    processing_chunk_size: int = Field(50, description="Number of papers to process in a single in-memory chunk")


def make_requests_session(total_retries: int = 5, backoff: float = 0.5,status_forcelist=(429, 500, 502, 503, 504)) -> requests.Session:
    retry = Retry(
        total=total_retries, read=total_retries, connect=total_retries,
        backoff_factor=backoff, status_forcelist=status_forcelist,
        allowed_methods=frozenset(["GET", "POST"]), raise_on_status=False,
        )
    adapter = HTTPAdapter(max_retries=retry)
    # --- START CHANGE ---
    # Increase pool size to handle high concurrency
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=50,  # Default is 10
        pool_maxsize=50       # Default is 10
    )
    # --- END CHANGE ---
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Enhanced-Journal-Search/2.0 (mailto: laozc@student.ubc.ca)"})
    sess.mount("http://", adapter); sess.mount("https://", adapter)
    return sess


def sanitize_filename(name: str, max_len: int = 120) -> str:
    original = name
    name = re.sub(r"\s+", " ", name or "").strip()
    allowed = f"-_.() {string.ascii_letters}{string.digits}"
    cleaned = "".join(c for c in name if c in allowed)
    if cleaned:
        return cleaned[:max_len]
    # fall back to deterministic hash on original (may contain disallowed chars)
    return hashlib.sha1((original or "").encode()).hexdigest()[:16]


def norm_title(t: str) -> str:
    t = (t or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def jaccard(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb: return 0.0
    return len(sa & sb) / len(sa | sb)


def title_close(a: str, b: str) -> bool:
    A, B = norm_title(a), norm_title(b)
    if not A or not B: return False
    return jaccard(A, B) >= 0.72


def first(*vals: Optional[str]) -> str:
    for v in vals:
        if v: return v
    return ""


def jats_nodes_to_sections(root: ET.Element) -> List[Dict[str, str]]:
    sections: List[Dict[str, str]] = []
    body = root.find(".//body")
    targets = [body] if body is not None else root.findall(".//sec")

    def clean_text(element_text):
        if not element_text: return ""
        return re.sub(r'\s+', ' ', element_text).strip()

    for target_node in targets:
        for sec in target_node.findall("./sec"):
            title = clean_text(sec.findtext("title"))
            text_parts = [clean_text("".join(p.itertext())) for p in sec.findall(".//p")]
            text = "\n".join(part for part in text_parts if part)
            if title or text:
                sections.append({"title": title, "text": text})

    if not sections and body is not None:
        text_parts = [clean_text("".join(p.itertext())) for p in body.findall(".//p")]
        txt = "\n".join(part for part in text_parts if part)
        if txt:
            sections.append({"title": "", "text": txt})
    return sections


def sections_to_markdown(sections: List[Dict[str, str]]) -> str:
    return "\n\n".join(
        [f"## {s['title']}\n{s['text']}" if s.get("title") else s.get("text","") for s in sections]
    ).strip()


# ----------------------------- Main Tool -----------------------------
class FullTextJournalSearchTool(BaseTool):
    name: str = "fulltext_journal_search"
    description: str = "Fetch articles from PubMed/PMC, Europe PMC, and preprint servers; save full text when available."
    args_schema: Type[FullTextJournalSearchInput] = FullTextJournalSearchInput

    _entrez_email: str = "laozc@student.ubc.ca"
    _max_retries: int = 3
    _backoff_base: float = 1.5
    _http: requests.Session

    include_pubmed: bool = True
    include_preprints: bool = True
    include_arxiv: bool = True
    include_medrxiv: bool = True
    include_chemrxiv: bool = True
    include_eupmc: bool = True
    use_pubmed_free_fulltext_bias: bool = True

    # parallel knobs (default overridden by input if provided)
    max_parallel_downloads: int = 6  # legacy
    max_search_workers: int = 8
    max_phase1_workers: int = 12
    max_parallel_docling: int = 6

    results_base_dir: Optional[pathlib.Path] = None
    
    # Date range filters
    min_date: Optional[str] = None
    max_date: Optional[str] = None

    def __init__(self, **data):
        super().__init__(**data)
        self._http = make_requests_session()
        self._current_run_assets_dir: Optional[pathlib.Path] = data.get("results_base_dir", None)
        # flags (allow override via constructor)
        self.include_pubmed = data.get("include_pubmed", True)
        self.include_preprints = data.get("include_preprints", True)
        self.include_arxiv = data.get("include_arxiv", False)
        self.include_medrxiv = data.get("include_medrxiv", True)
        self.include_chemrxiv = data.get("include_chemrxiv", True)
        self.include_eupmc = data.get("include_eupmc", True)
        self.use_pubmed_free_fulltext_bias = data.get("use_pubmed_free_fulltext_bias", True)
        self.max_parallel_downloads = int(data.get("max_parallel_downloads", 6))
        self.max_search_workers = int(data.get("max_search_workers", 8))
        self.max_phase1_workers = int(data.get("max_phase1_workers", 12))
        self.max_parallel_docling = int(data.get("max_parallel_docling", 6))

        # Note: min_date and max_date are now Pydantic fields, so they're set automatically
        
        # Docling converter (optional)
        self._docling = DocumentConverter() if _DOCLING_AVAILABLE else None

    # ---- API for nodes to seed the current run dir (env-free, thread/async safe)
    @staticmethod
    def set_session_dir(path: Optional[str]) -> None:
        _SESSION_DIR_CVAR.set(path)

    # ---------------- Entrez Helpers ----------------
    def _init_entrez(self) -> None:
        if Entrez is None:
            raise RuntimeError("Bio.Entrez not available. Install Biopython.")
        try:
            Entrez.email = self._entrez_email
            Entrez.api_key = os.environ.get("NCBI_API_KEY", None)
        except Exception:
            pass

    def _entrez_fetch_and_parse(self, func, description: str, *args, **kwargs):
        self._init_entrez()
        last_err = None
        for attempt in range(1, self._max_retries + 1):
            handle = None
            try:
                handle = func(*args, **kwargs)
                raw_content = handle.read()
                if not raw_content:
                    last_err = ValueError("Empty response returned by Entrez")
                    log.warning(f"Entrez error {description} (attempt {attempt}/{self._max_retries}): empty response")
                    time.sleep(self._backoff_base ** (attempt - 1))
                    continue
                try:
                    parsed = Entrez.read(io.BytesIO(raw_content))
                    return parsed
                except Exception as exc:
                    last_err = exc
                    log.warning(f"Entrez XML parse error {description} (attempt {attempt}/{self._max_retries}): {exc}")
                    time.sleep(self._backoff_base ** (attempt - 1))
            except Exception as exc:
                last_err = exc
                log.warning(f"Entrez network error {description} (attempt {attempt}/{self._max_retries}): {exc}")
                time.sleep(self._backoff_base ** (attempt - 1))
                continue
            finally:
                if handle is not None and hasattr(handle, "close"):
                    try: handle.close()
                    except Exception: pass
        if last_err:
            raise last_err
        raise RuntimeError(f"Entrez {description} failed without explicit error")

    def _entrez_get_bytes(self, func, description: str, *args, **kwargs) -> bytes:
        self._init_entrez()
        last_err = None
        for attempt in range(1, self._max_retries + 1):
            handle = None
            try:
                handle = func(*args, **kwargs)
                raw = handle.read()
                if not raw:
                    last_err = ValueError("Empty response returned by Entrez")
                    log.warning(f"Entrez empty response {description} (attempt {attempt}/{self._max_retries})")
                    time.sleep(self._backoff_base ** (attempt - 1))
                    continue
                return raw
            except Exception as exc:
                last_err = exc
                log.warning(f"Entrez network error {description} (attempt {attempt}/{self._max_retries}): {exc}")
                time.sleep(self._backoff_base ** (attempt - 1))
            finally:
                if handle is not None and hasattr(handle, "close"):
                    try: handle.close()
                    except Exception: pass
        if last_err:
            raise last_err
        raise RuntimeError(f"Entrez {description} failed without explicit error")

    # ---------------- PubMed / PMC ----------------
    def search_pubmed_pmc(self, query: str, max_results: int, min_date: Optional[str] = None, max_date: Optional[str] = None) -> List[Dict]:
        results: List[Dict] = []
        try:
            q_term = query
            if self.use_pubmed_free_fulltext_bias and query and "free full text[filter]" not in query.lower():
                q_term = f"({query}) AND free full text[Filter]"

            # Add date range to query if specified
            if min_date or max_date:
                mindate_str = min_date.replace("/", "") if min_date else ""
                maxdate_str = max_date.replace("/", "") if max_date else ""
                
                search = self._entrez_fetch_and_parse(
                    Entrez.esearch, "during esearch(pubmed)",
                    db="pubmed", term=q_term, retmax=max_results, sort="relevance",
                    mindate=mindate_str, maxdate=maxdate_str, datetype="pdat",
                )
            else:
                search = self._entrez_fetch_and_parse(
                    Entrez.esearch, "during esearch(pubmed)",
                    db="pubmed", term=q_term, retmax=max_results, sort="relevance",
                )
            pmids = []
            if isinstance(search, dict):
                pmids = search.get("IdList", []) or search.get("Idlist", []) or []
            pmids = [str(x) for x in pmids if x]
            if not pmids:
                return results

            recs = self._entrez_fetch_and_parse(
                Entrez.esummary, "during esummary(pubmed)",
                db="pubmed", id=",".join(pmids), retmode="xml",
            )

            if isinstance(recs, dict) and "DocSum" in recs:
                doc_sums = recs["DocSum"]
            elif isinstance(recs, list):
                doc_sums = recs
            else:
                log.warning("Unexpected esummary structure; skipping.")
                doc_sums = []

            for rec in doc_sums:
                pmid = rec.get("Id", "")
                title = rec.get("Title", "") or ""
                jname = (rec.get("FullJournalName") or rec.get("Source") or "")
                pubdate = rec.get("PubDate", "")
                doi = rec.get("DOI", "")
                authors = rec.get("AuthorList", []) or []
                author_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")

                abstract = ""
                try:
                    art = self._entrez_fetch_and_parse(
                        Entrez.efetch, f"during efetch(pubmed) for PMID {pmid}",
                        db="pubmed", id=pmid, retmode="xml",
                    )
                    if isinstance(art, dict) and art.get("PubmedArticle"):
                        ab = art["PubmedArticle"][0]["MedlineCitation"]["Article"].get("Abstract", {}).get("AbstractText", [])
                        abstract = " ".join([str(x) for x in ab]) or ""
                except Exception:
                    pass

                full_text, sections = self.get_pmc_fulltext(pmid)
                url = f"https://doi.org/{doi}" if doi else (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "")

                results.append({
                    "source": "PubMed",
                    "ids": {"pmid": pmid},
                    "title": title,
                    "authors": author_str,
                    "journal": jname,
                    "pubdate": pubdate,
                    "doi": doi,
                    "url": url,
                    "abstract": abstract,
                    "full_text": full_text,
                    "sections": sections,
                    "pdf_url": "",
                    "pdf_path": "",
                    "html_path": "",
                    "has_fulltext": bool(full_text),
                })
                time.sleep(0.34)  # NCBI politeness
        except Exception as e:
            log.error(f"PubMed search error: {e}")
        return results

    def get_pmc_fulltext(self, pmid: str) -> Tuple[str, List[Dict[str, str]]]:
        try:
            link_data = self._entrez_fetch_and_parse(
                Entrez.elink, f"during elink(pubmed->pmc) for PMID {pmid}",
                dbfrom="pubmed", db="pmc", id=pmid,
            )
            pmcids = [
                lnk["Id"]
                for ls in link_data
                for lset in ls.get("LinkSetDb", []) if lset.get("DbTo") == "pmc"
                for lnk in lset.get("Link", []) if "Id" in lnk
            ]
            if not pmcids:
                return "", []

            raw_xml = self._entrez_get_bytes(
                Entrez.efetch, f"during efetch(pmc) for PMID {pmid}",
                db="pmc", id=pmcids[0], retmode="xml",
            )
            root = ET.fromstring(raw_xml)
            sections = jats_nodes_to_sections(root)
            full_text = sections_to_markdown(sections)
            return full_text, sections
        except Exception as e:
            log.debug(f"PMC full-text extraction error for PMID {pmid}: {e}")
            return "", []

    # ---------------- Europe PMC (search + JATS fullTextXML) ----------------
    def search_eupmc(self, query: str, max_results: int, min_date: Optional[str] = None, max_date: Optional[str] = None) -> List[Dict]:
        results: List[Dict] = []
        try:
            # Build date range filter for Europe PMC
            q_term = query
            if min_date or max_date:
                # Europe PMC uses FIRST_PDATE:[mindate TO maxdate] format
                mindate_eupmc = min_date.replace("/", "-") if min_date else "*"
                maxdate_eupmc = max_date.replace("/", "-") if max_date else "*"
                q_term = f"({query}) AND FIRST_PDATE:[{mindate_eupmc} TO {maxdate_eupmc}]"
            
            url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            params = {"query": q_term, "format": "json", "pageSize": min(1000, max_results), "resultType": "core"}
            r = self._http.get(url, params=params, timeout=30); r.raise_for_status()
            data = r.json()
            for rec in (data.get("resultList", {}).get("result", []) or [])[:max_results]:
                doi   = (rec.get("doi") or "").strip()
                pmid  = (rec.get("pmid") or "").strip()
                pmcid = (rec.get("pmcid") or "").strip()
                src   = (rec.get("source") or "").strip()  # e.g., MEDRXIV, CHEMRXIV, PMCID, AGR
                title = rec.get("title","") or ""
                author_str = rec.get("authorString","") or ""
                journal = rec.get("journalTitle","") or rec.get("bookOrReportDetails","") or ""
                pubdate = (rec.get("firstPublicationDate") or rec.get("pubYear",""))[:10]
                pdf_url = ""
                for u in (rec.get("fullTextUrlList", {}) or {}).get("fullTextUrl", []) or []:
                    if u.get("documentStyle") == "pdf" and u.get("availability") in {"Open access","Open"}:
                        pdf_url = u.get("url",""); break
                results.append({
                    "source": f"EuropePMC:{src or 'article'}",
                    "ids": {"doi": doi, "pmid": pmid, "pmcid": pmcid, "eupmc_id": rec.get("id","")},
                    "title": title,
                    "authors": author_str,
                    "journal": journal,
                    "pubdate": pubdate,
                    "doi": doi,
                    "url": rec.get("url","") or (f"https://europepmc.org/article/{src}/{rec.get('id')}" if src and rec.get("id") else ""),
                    "abstract": rec.get("abstractText","") or "",
                    "pdf_url": pdf_url,
                    "full_text": "",
                    "sections": [],
                    "has_fulltext": False,
                    "xml_url": "",  # attempt via fullTextXML next
                })
        except Exception as e:
            log.error(f"Europe PMC search error: {e}")
        return results

    def eupmc_fulltext_jats(self, eupmc_source: str, eupmc_id: str) -> Tuple[str, List[Dict[str,str]], Optional[str]]:
        if not eupmc_source or not eupmc_id:
            return "", [], None
        base = "https://www.ebi.ac.uk/europepmc/webservices/rest"
        xml_url = f"{base}/{eupmc_source}/{eupmc_id}/fullTextXML"
        try:
            r = self._http.get(xml_url, timeout=60)
            if r.status_code == 404:
                return "", [], None
            r.raise_for_status()
            xml_path = None
            if self._current_run_assets_dir:
                fn = sanitize_filename(f"{eupmc_source}_{eupmc_id}") + ".xml"
                fp = self._current_run_assets_dir / fn
                fp.write_bytes(r.content); xml_path = str(fp)
            root = ET.fromstring(r.content)
            sections = jats_nodes_to_sections(root)
            full_text = sections_to_markdown(sections)
            return full_text, sections, xml_path
        except Exception as e:
            log.debug(f"Europe PMC fullTextXML fetch/parse failed for {eupmc_source}:{eupmc_id}: {e}")
            return "", [], None

    # ---------------- arXiv ----------------
    def search_arxiv(self, query: str, max_results: int) -> List[Dict]:
        if not query:
            return []
        results: List[Dict] = []
        try:
            url = "http://export.arxiv.org/api/query"
            params = {
                "search_query": f'all:"{query}"',
                "start": 0, "max_results": max_results,
                "sortBy": "relevance", "sortOrder": "descending",
            }
            r = self._http.get(url, params=params, timeout=30); r.raise_for_status()
            root = ET.fromstring(r.content); ns = {"atom": "http://www.w3.org/2005/Atom"}

            for entry in root.findall("atom:entry", ns):
                title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip().replace("\n"," ")
                abstract = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
                pub_date = entry.findtext("atom:published", default="", namespaces=ns) or ""
                pubdate = pub_date[:10] if pub_date else ""
                arxiv_id = entry.findtext("atom:id", default="", namespaces=ns) or ""
                authors = [a.findtext("atom:name", default="", namespaces=ns) or "" for a in entry.findall("atom:author", ns)]
                author_str = ", ".join([a for a in authors if a][:3]) + (" et al." if len(authors) > 3 else "")

                pdf_url = ""
                for link in entry.findall("atom:link", ns):
                    rel = link.attrib.get("rel",""); href = link.attrib.get("href",""); title_attr = link.attrib.get("title","")
                    if title_attr and title_attr.lower() == "pdf":
                        pdf_url = href
                    elif (rel == "related" and href.endswith(".pdf")):
                        pdf_url = href
                if not pdf_url and arxiv_id:
                    m = re.search(r"arxiv.org/abs/(\S+)", arxiv_id)
                    if m: pdf_url = f"https://arxiv.org/pdf/{m.group(1)}.pdf"

                results.append({
                    "source": "arXiv",
                    "ids": {"arxiv": arxiv_id},
                    "title": title,
                    "authors": author_str,
                    "journal": "arXiv preprint",
                    "pubdate": pubdate,
                    "doi": "",
                    "url": arxiv_id,
                    "abstract": abstract,
                    "pdf_url": pdf_url,
                    "full_text": "",
                    "sections": [],
                    "pdf_path": "",
                    "html_path": "",
                    "has_fulltext": False,
                })
        except Exception as e:
            log.error(f"arXiv search error: {e}")
        return results

    # ---------------- medRxiv ----------------
    def search_medrxiv(self, query: str, max_results: int) -> List[Dict]:
        results: List[Dict] = []
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=3*365)
            url = f"https://api.medrxiv.org/details/medrxiv/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
            r = self._http.get(url, timeout=60); r.raise_for_status()
            data = r.json()
            if not (data.get("messages") and data["messages"][0].get("status") == "ok"):
                return results

            ql = (query or "").lower()
            for p in data.get("collection", []):
                title = p.get("title","") or ""; abstract = p.get("abstract","") or ""
                if ql and (ql not in title.lower() and ql not in abstract.lower()):
                    continue

                doi = (p.get("doi") or "").strip()
                version = str(p.get("version") or "").strip()
                if not doi:
                    continue

                base = f"https://www.medrxiv.org/content/{doi}"
                landing = f"{base}v{version}" if version else base

                pub_date = p.get("date", "")
                if pub_date and len(pub_date) >= 10:
                    year, month, day = pub_date[:4], pub_date[5:7], pub_date[8:10]
                    doi_part = doi.replace("10.1101/", "")
                    xml_url = f"https://www.medrxiv.org/content/medrxiv/early/{year}/{month}/{day}/{doi_part}.source.xml"
                else:
                    xml_url = f"{landing}.source.xml"

                html_url = f"{landing}.full"
                pdf_url  = f"{landing}.full.pdf"

                authors_raw = p.get("authors","") or ""
                author_list = []
                for a in [x.strip() for x in authors_raw.split(";") if x.strip()]:
                    if "," in a:
                        last, first = a.split(",",1); author_list.append(f"{first.strip()} {last.strip()}")
                    else:
                        author_list.append(a)
                author_str = ", ".join(author_list[:3]) + (" et al." if len(author_list) > 3 else "")

                results.append({
                    "source": "medRxiv",
                    "ids": {"doi": doi, "version": version},
                    "title": title,
                    "authors": author_str,
                    "journal": "medRxiv preprint",
                    "pubdate": p.get("date","") or "",
                    "doi": doi,
                    "url": landing,
                    "abstract": abstract,
                    "xml_url": xml_url,
                    "html_url": html_url,
                    "pdf_url": pdf_url,
                    "full_text": "",
                    "sections": [],
                    "pdf_path": "",
                    "html_path": "",
                    "has_fulltext": False,
                })
                if len(results) >= max_results:
                    break
        except Exception as e:
            log.error(f"medRxiv search error: {e}")
        return results

    # ---------------- ChemRxiv via Figshare ----------------
    def search_chemrxiv_via_figshare(self, query: str, max_results: int) -> List[Dict]:
        results: List[Dict] = []
        try:
            q = query or ""
            url = f"https://api.figshare.com/v2/collections/3997422/articles?search_for={q}&page_size={min(100, max_results)}"
            r = self._http.get(url, timeout=60); r.raise_for_status()
            data = r.json()
            for item in data[:max_results]:
                title = item.get("title", "") or ""
                doi = item.get("doi", "") or ""
                published_date = (item.get("published_date") or "")[:10]
                article_id = item.get("id")
                pdf_url = ""
                if article_id:
                    try:
                        article_url = f"https://api.figshare.com/v2/articles/{article_id}"
                        r2 = self._http.get(article_url, timeout=60)
                        if r2.status_code == 200:
                            article_data = r2.json()
                            files = article_data.get("files", [])
                            for f in files:
                                if f.get("name", "").lower().endswith(".pdf"):
                                    pdf_url = f.get("download_url", "")
                                    break
                    except Exception:
                        pass

                results.append({
                    "source": "ChemRxiv",
                    "ids": {"doi": doi},
                    "title": title,
                    "authors": "",
                    "journal": "ChemRxiv preprint",
                    "pubdate": published_date,
                    "doi": doi,
                    "url": item.get("url_public_html", ""),
                    "abstract": "",
                    "xml_url": "",
                    "html_url": "",
                    "pdf_url": pdf_url,
                    "full_text": "",
                    "sections": [],
                    "pdf_path": "",
                    "html_path": "",
                    "has_fulltext": False,
                })
        except Exception as e:
            log.error(f"ChemRxiv (Figshare) search error for '{query}': {e}")
        return results

    # ---------------- Unpaywall (DOI → best OA location) ----------------
    def unpaywall_lookup(self, doi: str, email: str = "you@example.com") -> Tuple[str, str]:
        if not doi:
            return "", ""
        try:
            r = self._http.get(f"https://api.unpaywall.org/v2/{doi}", params={"email": email}, timeout=30)
            if r.status_code == 404:
                return "", ""
            r.raise_for_status()
            u = r.json()
            loc = u.get("best_oa_location") or {}
            pdf = (loc.get("url_for_pdf") or "") or ""
            landing = loc.get("url") or ""
            return pdf, landing
        except Exception as e:
            log.debug(f"Unpaywall lookup failed for {doi}: {e}")
            return "", ""

    # ---------------- Fetchers & Parsers (fallback helpers) ----------------
    def download_to_path(self, url: str, path: pathlib.Path) -> bool:
        try:
            with self._http.get(url, timeout=60, stream=True) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(8192):
                        if chunk: f.write(chunk)
            return True
        except Exception as e:
            log.debug(f"Download failed {url}: {e}")
            return False

    def pdf_to_text_tables_figures(self, pdf_path: pathlib.Path, assets_dir: pathlib.Path) -> Tuple[str, List[Dict], List[str]]:
        try:
            text = pdf_extract_text(str(pdf_path)) or ""
            return text, [], []
        except Exception as e:
            log.debug(f"PDF text extraction failed {pdf_path}: {e}")
            return "", [], []

    def clean_extracted_text(self, text: str, source: str = "") -> str:
        if not text: return ""
        t = re.sub(r"\r", "\n", text)
        t = re.sub(r"\n{3,}", "\n\n", t)
        t = re.sub(r"^\s*\d{1,3}\s*$", "", t, flags=re.M)
        m = re.search(r"\n\s*(references|bibliography)\b", t, flags=re.I)
        if m: t = t[:m.start()].strip()
        if source.lower() in {"arxiv", "biorxiv", "medrxiv", "chemrxiv"}:
            t = re.sub(r"arXiv:\s*\S+", "", t)
            t = re.sub(r"(bioRxiv|medRxiv)\s+preprint\s+.*?doi:\s*\S+.*?$", "", t, flags=re.I|re.M)
        t = re.sub(r"[ \t]+", " ", t).strip()
        return t

    # ---------------- Docling from URL ----------------
    def docling_url_to_text(self, pdf_url: str) -> Tuple[str, List[Dict], List[str]]:
        """Use Docling to convert a PDF directly from URL to text/sections.
        Falls back to legacy download+pdfminer if Docling isn't available or fails.
        """
        if not pdf_url:
            return "", [], []
        # Docling path
        if self._docling is not None:
            try:
                res = self._docling.convert(pdf_url)
                if not res or not getattr(res, "document", None):
                    return "", [], []
                doc = res.document
                full_text = None
                for attr in ("export_to_markdown", "to_markdown", "export_markdown"):
                    if hasattr(doc, attr):
                        full_text = getattr(doc, attr)()
                        break
                if full_text is None and hasattr(res, "text"):
                    full_text = res.text
                if full_text is None and hasattr(doc, "pages"):
                    try:
                        full_text = "\n\n".join(getattr(p, "text", "") for p in doc.pages)
                    except Exception:
                        full_text = ""
                full_text = self.clean_extracted_text(full_text or "")
                return full_text, [], []
            except Exception as e:
                log.debug(f"Docling URL convert failed, will fallback: {e}")
        # Fallback to legacy (download then parse)
        tmp_name = sanitize_filename(hashlib.md5(pdf_url.encode()).hexdigest()) + ".pdf"
        tmp_path = (self._current_run_assets_dir or pathlib.Path.cwd()) / tmp_name
        if self.download_to_path(pdf_url, tmp_path):
            txt, tables, figs = self.pdf_to_text_tables_figures(tmp_path, self._current_run_assets_dir or tmp_path.parent)
            return self.clean_extracted_text(txt), tables, figs
        return "", [], []

    # ---------------- Dedup & Save ----------------
    def deduplicate(self, items: List[Dict]) -> List[Dict]:
        seen_doi, seen_pmid, seen_arxiv, seen_title = set(), set(), set(), []
        uniq: List[Dict] = []
        for it in items:
            ids = it.get("ids", {}) or {}
            doi = (ids.get("doi") or it.get("doi") or "").lower().strip()
            pmid = (ids.get("pmid") or "").strip()
            arxiv_id = (ids.get("arxiv") or "").strip()

            if doi and doi in seen_doi: continue
            if pmid and pmid in seen_pmid: continue
            if arxiv_id and arxiv_id in seen_arxiv: continue

            t = it.get("title","") or ""
            if any(title_close(t, prev) for prev in seen_title): continue

            if doi: seen_doi.add(doi)
            if pmid: seen_pmid.add(pmid)
            if arxiv_id: seen_arxiv.add(arxiv_id)
            seen_title.append(t)
            uniq.append(it)
        return uniq

    def _save_batch_streaming(self, papers: List[Dict], run_dir: pathlib.Path, 
                              csv_writer, ndjson_file, saved_files_list: List[str]) -> int:
        """
        Save a batch of papers to disk and update index files (streaming mode).
        Returns the number of papers saved.
        """
        count = 0
        for p in papers:
            id_for_name = first(p.get("doi"), p.get("ids", {}).get("pmid"), p.get("ids", {}).get("arxiv"), p.get("title"), "paper")
            fname = sanitize_filename(id_for_name) + ".json"
            fpath = run_dir / fname
            
            try:
                with fpath.open("w", encoding="utf-8") as jf:
                    json.dump(p, jf, ensure_ascii=False, indent=2)
                
                saved_files_list.append(str(fpath.resolve()))
                
                csv_writer.writerow([
                    str(fpath), p.get("source",""), p.get("title",""), p.get("authors",""),
                    p.get("journal",""), p.get("pubdate",""), p.get("doi",""), p.get("url",""),
                    p.get("ids",{}).get("pmid",""), p.get("ids",{}).get("arxiv",""),
                    p.get("has_fulltext",False), p.get("pdf_path",""), p.get("html_path","")
                ])
                
                ndjson_file.write(json.dumps(p, ensure_ascii=False) + "\n")
                ndjson_file.flush()  # Ensure data is written immediately
                
                count += 1
            except Exception as e:
                log.error(f"Failed to save paper {fname}: {e}")
        
        return count

    def save_results(self, papers: List[Dict], run_dir: pathlib.Path) -> Tuple[List[str], str, str]:
        """
        Legacy method for backward compatibility. 
        New code should use _save_batch_streaming for memory efficiency.
        """
        run_dir.mkdir(parents=True, exist_ok=True)
        index_csv, index_ndjson = run_dir / "index.csv", run_dir / "index.ndjson"
        saved_files: List[str] = []

        with index_csv.open("w", newline="", encoding="utf-8") as fcsv, index_ndjson.open("w", encoding="utf-8") as fnd:
            writer = csv.writer(fcsv)
            writer.writerow(["file_path","source","title","authors","journal","pubdate","doi","url","pmid","arxiv_id","has_fulltext","pdf_path","html_path"])
            for p in papers:
                id_for_name = first(p.get("doi"), p.get("ids", {}).get("pmid"), p.get("ids", {}).get("arxiv"), p.get("title"), "paper")
                fname = sanitize_filename(id_for_name) + ".json"
                fpath = run_dir / fname
                with fpath.open("w", encoding="utf-8") as jf:
                    json.dump(p, jf, ensure_ascii=False, indent=2)
                saved_files.append(str(fpath.resolve()))
                writer.writerow([
                    str(fpath), p.get("source",""), p.get("title",""), p.get("authors",""),
                    p.get("journal",""), p.get("pubdate",""), p.get("doi",""), p.get("url",""),
                    p.get("ids",{}).get("pmid",""), p.get("ids",{}).get("arxiv",""),
                    p.get("has_fulltext",False), p.get("pdf_path",""), p.get("html_path","")
                ])
                fnd.write(json.dumps(p, ensure_ascii=False) + "\n")
        return saved_files, str(index_csv.resolve()), str(index_ndjson.resolve())

    # ---------------- Parallel workers ----------------
    def _resolve_url_to_pdf(self, url: str, max_redirects: int = 5) -> str:
        """
        Follow redirects and try to find actual PDF URL.
        Returns the final URL if it's a PDF, empty string otherwise.
        """
        try:
            # Follow redirects with HEAD request (faster)
            response = self._http.head(url, allow_redirects=True, timeout=10)
            final_url = response.url
            content_type = response.headers.get('Content-Type', '').lower()
            
            # Check if final URL is a PDF
            if 'application/pdf' in content_type or final_url.lower().endswith('.pdf'):
                log.debug(f"[Resolve] {url[:60]} → PDF: {final_url[:60]}")
                return final_url
            
            # Check if final URL contains PDF patterns
            if '/pdf/' in final_url.lower() or 'download' in final_url.lower():
                # Try modifying URL to get PDF
                pdf_attempts = [
                    final_url + '.pdf',
                    final_url + '/pdf',
                    final_url.replace('/abstract/', '/pdf/'),
                    final_url.replace('/full', '/pdf'),
                ]
                
                for pdf_url in pdf_attempts:
                    try:
                        check = self._http.head(pdf_url, allow_redirects=True, timeout=5)
                        if 'application/pdf' in check.headers.get('Content-Type', '').lower():
                            log.debug(f"[Resolve] Found PDF variant: {pdf_url[:60]}")
                            return pdf_url
                    except Exception:
                        continue
            
            log.debug(f"[Resolve] {url[:60]} → Not a PDF (content-type: {content_type})")
            return ""
            
        except Exception as e:
            log.debug(f"[Resolve] Failed to resolve {url[:60]}: {e}")
            return ""
    
    def _pdf_worker_docling(self, p: dict) -> dict:
        pdf_url = p.get("pdf_url") or ""
        if not pdf_url:
            return p
        
        # Try to resolve DOI redirects to actual PDF URLs
        if pdf_url.startswith("https://doi.org/") or pdf_url.startswith("http://doi.org/"):
            log.debug(f"[Docling] DOI redirect detected, attempting to resolve: {pdf_url[:60]}")
            resolved_url = self._resolve_url_to_pdf(pdf_url)
            
            if resolved_url:
                pdf_url = resolved_url
                p["pdf_url"] = resolved_url  # Update with resolved URL
                log.info(f"[Docling] Resolved DOI to PDF: {resolved_url[:60]}")
            else:
                log.warning(f"[Docling SKIP] Could not resolve DOI to PDF: {pdf_url[:60]}")
                p["has_fulltext"] = False
                return p
        
        # Try to resolve landing pages to PDF URLs
        landing_page_patterns = [
            ("wiley.com/doi/", lambda u: u.replace('/doi/', '/doi/pdf/') if '/pdf/' not in u else u),
            ("onlinelibrary.wiley.com/doi/", lambda u: u.replace('/doi/', '/doi/pdf/') if '/pdf/' not in u else u),
            ("sciencedirect.com/science/article/pii/", lambda u: u.replace('/article/pii/', '/article/pii/') + '/pdf' if not u.endswith('/pdf') else u),
            ("springer.com/article/", lambda u: u.replace('/article/', '/content/pdf/') + '.pdf' if not u.endswith('.pdf') else u),
            ("nature.com/articles/", lambda u: u.replace('/articles/', '/articles/') + '.pdf' if not u.endswith('.pdf') else u),
        ]
        
        for pattern, transform in landing_page_patterns:
            if pattern in pdf_url.lower() and not pdf_url.lower().endswith('.pdf'):
                attempted_pdf_url = transform(pdf_url)
                resolved_url = self._resolve_url_to_pdf(attempted_pdf_url)
                
                if resolved_url:
                    pdf_url = resolved_url
                    p["pdf_url"] = resolved_url
                    log.info(f"[Docling] Resolved landing page to PDF: {resolved_url[:60]}")
                    break
                else:
                    log.debug(f"[Docling] Could not resolve landing page: {pdf_url[:60]}")
        
        # Now try Docling with the (possibly resolved) URL
        try:
            text, tables, figures = self.docling_url_to_text(pdf_url)
            if text:
                p.update({"full_text": text, "tables": tables, "figures": figures, "has_fulltext": True})
                log.info(f"[Docling OK] {p.get('source','')}: {p.get('title','')[:60]}")
            else:
                log.warning(f"[Docling EMPTY] {p.get('source','')}: {p.get('title','')[:60]}")
                p["has_fulltext"] = False
        except Exception as e:
            log.warning(f"[Docling FAIL] {pdf_url[:80]}: {str(e)[:100]}")
            p["has_fulltext"] = False
        return p

    def _phase1_enrich_one(self, p: dict) -> dict:
        """Attempt JATS and Unpaywall for a single paper (no downloads)."""
        if p.get("has_fulltext"):
            return p
        try:
            source = p.get("source", "")
            ids = p.get("ids", {}) or {}
            xml_url = p.get("xml_url") or ""
            pdf_url = p.get("pdf_url") or ""
            html_url = p.get("html_url") if "html_url" in p else ""

            # 1) Europe PMC JATS fullTextXML
            if source.startswith("EuropePMC:") and ids.get("eupmc_id"):
                src_tag = source.split(":",1)[1]
                ft, sections, xml_path = self.eupmc_fulltext_jats(src_tag, ids["eupmc_id"])
                if ft:
                    p.update({"full_text": ft, "sections": sections, "html_path": xml_path or "", "has_fulltext": True})
                    log.info(f"[EUPMC JATS OK] {p.get('title','')[:60]}")
                    return p

            # 2) PubMed Central via PMID/PMCID (for papers with PMC access)
            pmid = ids.get("pmid") or ""
            pmcid = ids.get("pmcid") or ""
            if (pmid or pmcid) and not p.get("has_fulltext"):
                try:
                    # Try with PMID first, or use PMCID directly
                    ft, sections = self.get_pmc_fulltext(pmid if pmid else pmcid)
                    if ft:
                        p.update({"full_text": ft, "sections": sections, "has_fulltext": True})
                        log.info(f"[PMC OK] {source}: {p.get('title','')[:60]}")
                        return p
                except Exception as e:
                    log.debug(f"PMC extraction failed for PMID={pmid}, PMCID={pmcid}: {e}")

            # 3) Explicit XML URL (e.g., medRxiv)
            if xml_url:
                ft, sections, maybe_xml_path = self.get_jats_fulltext_from_url(xml_url)
                if ft:
                    p.update({"full_text": ft, "sections": sections, "html_path": maybe_xml_path or "", "has_fulltext": True})
                    log.info(f"[JATS OK] {source}: {p.get('title','')[:60]}")
                    return p

            # 4) Unpaywall - Enhanced to get direct PDF URLs
            doi = p.get("doi") or ids.get("doi") or ""
            if doi and not pdf_url:
                up_pdf, up_landing = self.unpaywall_lookup(doi, email=self._entrez_email)
                if up_pdf:
                    # Validate it's a direct PDF URL, not a landing page
                    if up_pdf.lower().endswith('.pdf') or '/pdf/' in up_pdf.lower():
                        p["pdf_url"] = up_pdf
                        log.debug(f"[Unpaywall] Found PDF: {up_pdf[:80]}")
                    else:
                        # It's a landing page, save for reference but don't use for PDF extraction
                        if not html_url:
                            p["html_url"] = up_pdf
                        log.debug(f"[Unpaywall] Found landing page (not PDF): {up_pdf[:80]}")
                elif up_landing and not html_url:
                    p["html_url"] = up_landing
        except Exception as e:
            log.debug(f"Phase-1 enrich failed for {p.get('title','')[:60]}: {e}")
        return p

    # ---------------- Orchestrator ----------------
    def _run(
        self,
        query: str | List[str],
        max_results: int = 20,
        max_results_pubmed: Optional[int] = None,
        max_results_eupmc: Optional[int] = None,
        max_results_arxiv: Optional[int] = None,
        max_results_medrxiv: Optional[int] = None,
        max_results_chemrxiv: Optional[int] = None,
        min_date: Optional[str] = None,
        max_date: Optional[str] = None,
        processing_chunk_size: int = 50,
        **kwargs
    ) -> str:
        # allow per-call flags
        for flag in [
            "include_pubmed","include_preprints","include_arxiv","include_medrxiv",
            "include_chemrxiv","include_eupmc","use_pubmed_free_fulltext_bias",
            "max_parallel_downloads","max_search_workers","max_phase1_workers","max_parallel_docling",
        ]:
            if flag in kwargs:
                setattr(self, flag, kwargs.get(flag, getattr(self, flag)))

        # Store date range parameters
        date_min = min_date or self.min_date
        date_max = max_date or self.max_date

        # Determine k for each source, falling back to the global max_results
        k_global = max_results # The global default
        k_pubmed = max_results_pubmed if max_results_pubmed is not None else k_global
        k_eupmc = max_results_eupmc if max_results_eupmc is not None else k_global
        k_arxiv = max_results_arxiv if max_results_arxiv is not None else k_global
        k_medrxiv = max_results_medrxiv if max_results_medrxiv is not None else k_global
        k_chemrxiv = max_results_chemrxiv if max_results_chemrxiv is not None else k_global

        # parse multi-query
        queries: List[str] = []
        if isinstance(query, list):
            queries = [q.strip() for q in query if q and q.strip()]
        else:
            q_str = (query or "").strip()
            if q_str.startswith("[") and q_str.endswith("]"):
                try:
                    parsed = json.loads(q_str)
                    if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                        queries = [x.strip() for x in parsed if x and x.strip()]
                except Exception:
                    queries = [q_str]
            if not queries:
                if "||" in q_str:
                    queries = [x.strip() for x in q_str.split("||") if x and x.strip()]
                else:
                    queries = [q_str] if q_str else []

        if not queries:
            log.info("No query provided.")
            return "No query provided. Nothing to search."

        # ---- Resolve session dir
        session_dir = _SESSION_DIR_CVAR.get()
        if session_dir:
            run_dir = pathlib.Path(session_dir).resolve()
            log.info(f"Using session directory: {run_dir}")
        else:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            configured = getattr(self, "results_base_dir", None)
            base_dir = pathlib.Path(configured or pathlib.Path(__file__).resolve().parent / "searching_results").resolve()
            run_dir = (base_dir / f"run_{ts}").resolve()
            log.warning("search_session_dir not in config/callback! Using tool default directory.")
        run_dir.mkdir(parents=True, exist_ok=True)

        assets_dir = run_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        self._current_run_assets_dir = assets_dir

        # ---------------- Parallel source searches ----------------
        all_results: List[Dict] = []
        source_counts: Dict[str,int] = {}

        def _schedule_search(q: str):
            tasks = []
            # --- START CHANGE ---
            # Use the per-source 'k' values and pass date range parameters
            if self.include_eupmc:
                tasks.append(("EuropePMC", self.search_eupmc, q, k_eupmc, date_min, date_max))
            if self.include_pubmed:
                tasks.append(("PubMed", self.search_pubmed_pmc, q, k_pubmed, date_min, date_max))
            if self.include_preprints and self.include_arxiv:
                tasks.append(("arXiv", self.search_arxiv, q, k_arxiv))
            if self.include_medrxiv and self.include_preprints:
                tasks.append(("medRxiv", self.search_medrxiv, q, k_medrxiv))
            if self.include_chemrxiv and self.include_preprints:
                tasks.append(("ChemRxiv", self.search_chemrxiv_via_figshare, q, k_chemrxiv))
            # --- END CHANGE ---
            return tasks

        futures = []
        with ThreadPoolExecutor(max_workers=self.max_search_workers) as ex:
            for q in queries:
                for task_info in _schedule_search(q):
                    tag = task_info[0]
                    fn = task_info[1]
                    q_ = task_info[2]
                    m = task_info[3]
                    # Pass date parameters if available (PubMed and EuropePMC only)
                    if len(task_info) > 4:
                        date_min_param = task_info[4]
                        date_max_param = task_info[5]
                        futures.append(ex.submit(fn, q_, m, date_min_param, date_max_param))
                    else:
                        futures.append(ex.submit(fn, q_, m))
            for fut in as_completed(futures):
                try:
                    results = fut.result() or []
                    all_results.extend(results)
                    if results:
                        key = results[0].get("source", "?")
                        source_counts[key] = source_counts.get(key, 0) + len(results)
                except Exception as e:
                    log.debug(f"Search task failed: {e}")

        papers = self.deduplicate(all_results)
        log.info(f"Found {len(all_results)} results total, {len(papers)} unique. Enriching...")
        log.info(f"Raw source counts before deduplication: {source_counts}")

        # -------- Phase 1 & 2: JATS + Unpaywall + PDF processing, STREAMING to disk in chunks --------
        index_csv = run_dir / "index.csv"
        index_ndjson = run_dir / "index.ndjson"
        all_saved_files = []
        
        with index_csv.open("w", newline="", encoding="utf-8") as fcsv, \
             index_ndjson.open("w", encoding="utf-8") as fnd:
            
            writer = csv.writer(fcsv)
            writer.writerow(["file_path","source","title","authors","journal","pubdate","doi","url","pmid","arxiv_id","has_fulltext","pdf_path","html_path"])

            # Process papers in chunks to manage memory
            for i in range(0, len(papers), processing_chunk_size):
                chunk = papers[i:i + processing_chunk_size]
                log.info(f"Processing chunk {i//processing_chunk_size + 1}/{(len(papers) + processing_chunk_size - 1)//processing_chunk_size} ({len(chunk)} papers)")

                # --- Phase 1: JATS + Unpaywall ---
                enriched_chunk_phase1 = []
                with ThreadPoolExecutor(max_workers=self.max_phase1_workers) as ex:
                    futures = [ex.submit(self._phase1_enrich_one, p) for p in chunk]
                    for fut in as_completed(futures):
                        try:
                            enriched_chunk_phase1.append(fut.result())
                        except Exception as e:
                            log.error(f"Phase-1 enrichment future failed: {e}")
                
                # --- Phase 2: PDF processing (Docling) ---
                papers_for_pdf = [p for p in enriched_chunk_phase1 if p.get("pdf_url") and not p.get("has_fulltext")]
                
                final_enriched_chunk = []
                if papers_for_pdf:
                    with ThreadPoolExecutor(max_workers=self.max_parallel_docling) as ex:
                        pdf_futures = {ex.submit(self._pdf_worker_docling, p): p for p in papers_for_pdf}
                        
                        # Create a map of original papers that don't need PDF processing
                        processed_dois = {p.get('doi') for p in papers_for_pdf if p.get('doi')}
                        final_enriched_chunk.extend([p for p in enriched_chunk_phase1 if p.get('doi') not in processed_dois])

                        for fut in as_completed(pdf_futures):
                            try:
                                final_enriched_chunk.append(fut.result())
                            except Exception as e:
                                original_paper = pdf_futures[fut]
                                log.error(f"PDF worker future failed for {original_paper.get('title', 'N/A')[:50]}: {e}")
                                final_enriched_chunk.append(original_paper) # append original on failure
                else:
                    final_enriched_chunk = enriched_chunk_phase1

                # Save the fully processed chunk
                saved_count = self._save_batch_streaming(final_enriched_chunk, assets_dir, writer, fnd, all_saved_files)
                log.info(f"Saved {saved_count} papers from this chunk.")
                fcsv.flush() # ensure the csv is written to disk per chunk
                fnd.flush()

        log.info(f"Enrichment complete. Total papers saved: {len(all_saved_files)}")
        return f"Total Papers Found: {len(all_saved_files)}. Run_dir: {run_dir}"

    # --- Helper to fetch arbitrary JATS XML URL (used by medRxiv, etc.)
    def get_jats_fulltext_from_url(self, xml_url: str) -> Tuple[str, List[Dict[str, str]], Optional[str]]:
        if not xml_url:
            return "", [], None
        try:
            r = self._http.get(xml_url, timeout=60)
            if r.status_code == 404:
                log.debug(f"JATS XML not found (404): {xml_url}")
                return "", [], None
            r.raise_for_status()
            xml_path = None
            if self._current_run_assets_dir:
                fname_part = xml_url.split('/')[-1].replace('.xml', '').replace('.source', '')
                xml_name = sanitize_filename(fname_part) + ".xml"
                xml_fpath = self._current_run_assets_dir / xml_name
                xml_fpath.write_bytes(r.content)
                xml_path = str(xml_fpath)

            root = ET.fromstring(r.content)
            sections = jats_nodes_to_sections(root)
            full_text = sections_to_markdown(sections)
            return full_text, sections, xml_path
        except Exception as e:
            log.debug(f"JATS XML fetch/parse failed for {xml_url}: {e}")
            return "", [], None
