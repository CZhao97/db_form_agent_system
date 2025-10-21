#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FullTextJournalSearchTool
- PubMed/PMC (JATS full text when available)
- arXiv (PDF to text)
- bioRxiv (API + JATS source XML parsing)

Usage:
    tool = FullTextJournalSearchTool(results_base_dir="searching_results")
    files = tool._run('["mass spectrometry metabolomics", "LC-MS/MS fragmentation"]', max_results=20)

Environment:
    ENTREZ_EMAIL       : overrides default Entrez email
    ENTREZ_API_KEY     : optional NCBI API key
    SEARCH_RESULTS_DIR : base directory for run folders (fallback if results_base_dir not set)
    SEARCH_SESSION_DIR : if set, reuse this existing folder for current run
"""
from __future__ import annotations

import os, re, csv, json, time, html, string, logging, pathlib, hashlib, io
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Type

import requests
import xml.etree.ElementTree as ET
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pydantic import BaseModel, Field

# Optional dependencies / fail gracefully
try:
    from Bio import Entrez
except Exception:
    Entrez = None  # type: ignore

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None  # type: ignore

try:
    import pdfplumber
except Exception:
    pdfplumber = None  # type: ignore

try:
    from pdfminer.high_level import extract_text as pdf_extract_text
except Exception:
    pdf_extract_text = None  # type: ignore

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None  # type: ignore

# LangChain BaseTool (graceful fallback if not installed)
try:
    from langchain.tools import BaseTool
except Exception:
    class BaseTool:  # minimal shim
        name: str = ""
        description: str = ""
        args_schema: Type[BaseModel] = BaseModel
        def __init__(self, **kwargs): pass
        def _run(self, *args, **kwargs): raise NotImplementedError

log = logging.getLogger("fulltext_journal_search")
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


# ----------------------------- Models & Utilities -----------------------------
class FullTextJournalSearchInput(BaseModel):
    query: str = Field(..., description="Academic search terms, '||' separated or JSON list for multi-query")
    max_results: int = Field(20, description="Maximum number of results to return (per source)")
    include_preprints: bool = Field(True, description="Include arXiv/bioRxiv (PDF/JATS parsing)")
    include_pubmed: bool = Field(True, description="Include PubMed/PMC")
    include_biorxiv: bool = Field(True, description="Include bioRxiv (API on/off)")


def make_requests_session(total_retries: int = 5, backoff: float = 0.5,
                          status_forcelist=(429, 500, 502, 503, 504)) -> requests.Session:
    retry = Retry(
        total=total_retries, read=total_retries, connect=total_retries,
        backoff_factor=backoff, status_forcelist=status_forcelist,
        allowed_methods=frozenset(["GET", "POST"]), raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Enhanced-Journal-Search/1.0 (mailto: laozc@student.ubc.ca)"})
    sess.mount("http://", adapter); sess.mount("https://", adapter)
    return sess


def sanitize_filename(name: str, max_len: int = 120) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    allowed = f"-_.() {string.ascii_letters}{string.digits}"
    cleaned = "".join(c for c in name if c in allowed)
    return cleaned[:max_len] if cleaned else hashlib.sha1(name.encode()).hexdigest()[:16]


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


def strip_html_tags(s: str) -> str:
    if not s: return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def jats_nodes_to_sections(root: ET.Element) -> List[Dict[str, str]]:
    """Turn JATS <body>/<sec> into a list of {title, text} sections."""
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
    description: str = "Fetch articles from PubMed/PMC, and (optionally) arXiv/bioRxiv; save full text when available."
    args_schema: Type[FullTextJournalSearchInput] = FullTextJournalSearchInput

    _entrez_email: str = "laozc@student.ubc.ca"
    _max_retries: int = 3
    _backoff_base: float = 1.5
    _http: requests.Session

    # exposed flags
    include_pubmed: bool = True
    include_preprints: bool = True
    include_biorxiv: bool = True

    results_base_dir: Optional[pathlib.Path] = None

    def __init__(self, **data):
        super().__init__(**data)
        self._http = make_requests_session()
        self._current_run_assets_dir: Optional[pathlib.Path] = None
        self.include_pubmed = data.get("include_pubmed", True)
        self.include_preprints = data.get("include_preprints", True)
        self.include_biorxiv = data.get("include_biorxiv", True)

    # ---------------- Entrez Helpers ----------------
    def _init_entrez(self) -> None:
        if Entrez is None:
            raise RuntimeError("Bio.Entrez not available. Install Biopython.")
        try:
            Entrez.email = os.environ.get("ENTREZ_EMAIL", self._entrez_email)
            api_key = os.environ.get("ENTREZ_API_KEY")
            if api_key:
                Entrez.api_key = api_key
        except Exception:
            pass

    def _entrez_fetch_and_parse(self, func, description: str, *args, **kwargs):
        """Return a parsed object via Entrez.read from raw bytes."""
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
        """Return raw bytes (for PMC JATS XML, etc.)."""
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
    def search_pubmed_pmc(self, query: str, max_results: int) -> List[Dict]:
        results: List[Dict] = []
        try:
            search = self._entrez_fetch_and_parse(
                Entrez.esearch, "during esearch(pubmed)",
                db="pubmed", term=query, retmax=max_results, sort="relevance",
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
                # Entrez esummary returns dict-like entries with fields
                pmid = rec.get("Id", "")
                title = rec.get("Title", "") or ""
                jname = first(rec.get("FullJournalName"), rec.get("Source"), "")
                pubdate = rec.get("PubDate", "")
                doi = rec.get("DOI", "")
                authors = rec.get("AuthorList", []) or []
                author_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")

                # attempt abstract
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

                # Full text via PMC JATS if linked
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
                time.sleep(0.34)  # be polite to NCBI
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

    # ---------------- arXiv (PDF → text) ----------------
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

    # ---------------- bioRxiv ----------------
    def search_biorxiv(self, query: str, max_results: int) -> List[Dict]:
        """Lightweight recent-window scan then filter locally by substring match."""
        results: List[Dict] = []
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=3*365)
            url = f"https://api.biorxiv.org/details/biorxiv/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
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

                base = f"https://www.biorxiv.org/content/{doi}"
                landing  = f"{base}v{version}" if version else base
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
                    "source": "bioRxiv",
                    "ids": {"doi": doi, "version": version},
                    "title": title,
                    "authors": author_str,
                    "journal": "bioRxiv preprint",
                    "pubdate": p.get("date","") or "",
                    "doi": doi,
                    "url": landing,
                    "abstract": abstract,
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
            log.error(f"bioRxiv search error: {e}")
        return results

    def get_biorxiv_jats_fulltext(self, doi: str, version: Optional[str]) -> Tuple[str, List[Dict[str, str]], Optional[str]]:
        """Fetch and parse bioRxiv JATS XML. Returns (full_text, sections, xml_path)."""
        if not doi:
            return "", [], None
        try:
            base = f"https://www.biorxiv.org/content/{doi}"
            xml_url = f"{base}v{version}.source.xml" if (version and version.strip()) else f"{base}.source.xml"
            r = self._http.get(xml_url, timeout=60)
            r.raise_for_status()

            xml_path = None
            if self._current_run_assets_dir:
                xml_name = sanitize_filename(doi + (f"v{version}" if version else "")) + ".source.xml"
                xml_fpath = self._current_run_assets_dir / xml_name
                xml_fpath.write_bytes(r.content)
                xml_path = str(xml_fpath)

            root = ET.fromstring(r.content)
            sections = jats_nodes_to_sections(root)
            full_text = sections_to_markdown(sections)
            return full_text, sections, xml_path
        except Exception as e:
            log.debug(f"bioRxiv JATS fetch/parse failed for {doi}v{version or ''}: {e}")
            return "", [], None

    # ---------------- Fetchers & Parsers ----------------
    def download_to_path(self, url: str, path: pathlib.Path) -> bool:
        try:
            with self._http.get(url, timeout=60, stream=True) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk: f.write(chunk)
            return True
        except Exception as e:
            log.debug(f"Download failed {url}: {e}")
            return False

    def html_to_main_text(self, html_bytes: bytes) -> Tuple[str, List[Dict[str, str]]]:
        if not BeautifulSoup:
            return "", []
        try:
            soup = BeautifulSoup(html_bytes, "lxml")
            main = (soup.find("div", class_="fulltext-view")
                    or soup.find("div", class_="content-block-markup")
                    or soup.find("div", {"id":"page-content"})
                    or soup.find("div", {"class":re.compile(r"article|content|main", re.I)}))
            if not main: main = soup.body or soup

            sections: List[Dict[str,str]] = []
            buf: List[str] = []
            current_title = ""
            for node in main.descendants:
                node_name = getattr(node, 'name', None)
                if node_name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                    if buf:
                        sections.append({"title": current_title, "text": "\n".join(buf).strip()})
                        buf = []
                    current_title = node.get_text(" ", strip=True)
                elif node_name in ["p", "li"] and node.get_text(strip=True):
                    txt = node.get_text(" ", strip=True)
                    if txt: buf.append(txt)
            if buf: sections.append({"title": current_title, "text": "\n".join(buf).strip()})

            full_text = sections_to_markdown(sections)
            return full_text, sections
        except Exception as e:
            log.debug(f"HTML parse failed: {e}")
            return "", []

    def pdf_to_text_tables_figures(self, pdf_path: pathlib.Path, assets_dir: pathlib.Path) -> Tuple[str, List[Dict], List[str]]:
        text, tables, figures = "", [], []
        try:
            if pdfplumber is not None:
                with pdfplumber.open(str(pdf_path)) as pdf:
                    pages_text = [p.extract_text() or "" for p in pdf.pages]
                    text = "\n\n".join(filter(None, pages_text)).strip()
                    for i, page in enumerate(pdf.pages):
                        try:
                            for t_i, table in enumerate(page.extract_tables() or []):
                                tables.append({'page': i+1, 'table_index': t_i, 'rows': table})
                        except Exception:
                            pass
            elif pdf_extract_text is not None:
                text = pdf_extract_text(str(pdf_path)) or ""

            if fitz is not None:
                try:
                    doc = fitz.open(str(pdf_path))
                    for i in range(len(doc)):
                        for img in doc.get_page_images(i):
                            xref = img[0]
                            pix = fitz.Pixmap(doc, xref)
                            img_ext = "png" if pix.alpha else "jpg"
                            fname = f"{pdf_path.stem}_p{i+1}_img{xref}.{img_ext}"
                            fpath = assets_dir / fname
                            if pix.alpha:
                                pix = fitz.Pixmap(fitz.csRGB, pix)
                            pix.save(str(fpath))
                            figures.append(str(fpath))
                    doc.close()
                except Exception:
                    pass
        except Exception as e:
            log.debug(f"PDF multimodal extraction failed {pdf_path}: {e}")
        return text, tables, figures

    def clean_extracted_text(self, text: str, source: str = "") -> str:
        if not text: return ""
        t = re.sub(r"\r", "\n", text)
        t = re.sub(r"\n{3,}", "\n\n", t)
        t = re.sub(r"^\s*\d{1,3}\s*$", "", t, flags=re.M)  # strip page-number-only lines
        m = re.search(r"\n\s*(references|bibliography)\b", t, flags=re.I)
        if m: t = t[:m.start()].strip()
        if source.lower() in {"arxiv", "biorxiv"}:
            t = re.sub(r"arXiv:\s*\S+", "", t)
            t = re.sub(r"bioRxiv\s+preprint\s+.*?doi:\s*\S+.*?$", "", t, flags=re.I|re.M)
        t = re.sub(r"[ \t]+", " ", t).strip()
        return t

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

    def save_results(self, papers: List[Dict], run_dir: pathlib.Path) -> Tuple[List[str], str, str]:
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

    # ---------------- Orchestrator ----------------
    def _run(self, query: str, max_results: int = 20, include_preprints: bool = True) -> List[str]:
        """
        Backward-compatible signature for LangChain Tool.
        - query: str (can be JSON list or '||'-separated)
        - returns: List[str] of saved JSON file paths with full text

        The include_* flags on the instance control which sources are searched.
        """
        # parse multi-query inputs
        queries: List[str] = []
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
            return []

        # session/run dir handling
        all_saved_files: List[str] = []
        session_dir = os.environ.get("SEARCH_SESSION_DIR")
        if session_dir:
            run_dir = pathlib.Path(session_dir).resolve()
            log.info(f"Reusing existing session directory: {run_dir}")
        else:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            configured = getattr(self, "results_base_dir", None)
            if configured:
                base_dir = pathlib.Path(configured).resolve()
            else:
                base_dir = pathlib.Path(os.environ.get(
                    "SEARCH_RESULTS_DIR",
                    pathlib.Path(__file__).resolve().parent / "searching_results"
                )).resolve()
            run_dir = (base_dir / f"run_{ts}").resolve()

        assets_dir = run_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        self._current_run_assets_dir = assets_dir

        all_results: List[Dict] = []

        for idx, q in enumerate(queries, start=1):
            log.info(f"Starting search #{idx}/{len(queries)} for query: {q!r}; saving to {run_dir}")

            if self.include_pubmed:
                log.info(f"[{idx}/{len(queries)}] Searching PubMed/PMC…")
                try:
                    all_results.extend(self.search_pubmed_pmc(q, max_results))
                except Exception as e:
                    log.error(f"PubMed/PMC search error for '{q}': {e}")

            if self.include_preprints:
                log.info(f"[{idx}/{len(queries)}] Searching arXiv…")
                try:
                    all_results.extend(self.search_arxiv(q, max_results))
                except Exception as e:
                    log.error(f"arXiv search error for '{q}': {e}")

            if self.include_biorxiv and self.include_preprints:
                log.info(f"[{idx}/{len(queries)}] Searching bioRxiv…")
                try:
                    all_results.extend(self.search_biorxiv(q, max_results))
                except Exception as e:
                    log.error(f"bioRxiv search error for '{q}': {e}")

        # Deduplicate across ALL queries combined
        papers = self.deduplicate(all_results)
        log.info(f"Found {len(all_results)} results total, {len(papers)} unique. Fetching full text...")

        # Try to fetch full text for sources with URLs
        for p in papers:
            if p.get("has_fulltext"):
                continue

            source = p.get("source", "")
            pdf_url = p.get("pdf_url") or ""
            html_url = p.get("html_url") if "html_url" in p else ""

            # bioRxiv JATS (preferred over PDF because structure)
            if source == "bioRxiv":
                full_text, sections, xml_path = self.get_biorxiv_jats_fulltext(p.get("doi",""), p.get("ids",{}).get("version"))
                if full_text:
                    p.update({"full_text": full_text, "sections": sections, "html_path": xml_path or "", "has_fulltext": True})
                    log.info(f"[JATS OK] bioRxiv: {p.get('title','')[:60]}")
                    continue

            # PDF fallback
            if pdf_url:
                pdf_name = sanitize_filename(first(p.get("doi"), p.get("ids", {}).get("arxiv"), p.get("title"), "paper")) + ".pdf"
                pdf_path = assets_dir / pdf_name
                if self.download_to_path(pdf_url, pdf_path):
                    text, tables, figures = self.pdf_to_text_tables_figures(pdf_path, assets_dir)
                    text = self.clean_extracted_text(text, source=source)
                    if text:
                        p.update({"full_text": text, "pdf_path": str(pdf_path), "tables": tables, "figures": figures, "has_fulltext": True})
                        log.info(f"[PDF OK] {source}: {p.get('title','')[:60]}")
                    else:
                        p.update({"pdf_path": str(pdf_path), "tables": tables, "figures": figures})
                        log.warning(f"[PDF EMPTY] {source}: {p.get('title','')[:60]}")
                    continue

            # (Optional) HTML parsing if you decide to download landing pages
            # if html_url:
            #     try:
            #         r = self._http.get(html_url, timeout=30); r.raise_for_status()
            #         full_text, sections = self.html_to_main_text(r.content)
            #         if full_text:
            #             html_name = sanitize_filename(p.get("title","") or p.get("doi","") or "article") + ".html"
            #             html_path = assets_dir / html_name
            #             html_path.write_bytes(r.content)
            #             p.update({"full_text": full_text, "sections": sections, "html_path": str(html_path), "has_fulltext": True})
            #             log.info(f"[HTML OK] {source}: {p.get('title','')[:60]}")
            #     except Exception as e:
            #         log.debug(f"HTML fetch/parse failed: {e}")

        # Sort papers: fulltext first, then by source priority
        priority = {"PubMed": 0, "bioRxiv": 1, "arXiv": 2}
        papers.sort(key=lambda x: (not x.get("has_fulltext", False), priority.get(x.get("source", ""), 99)))

        # ONLY save papers with full text
        papers_with_fulltext = [p for p in papers if p.get("has_fulltext", False)]
        log.info(f"Filtered to {len(papers_with_fulltext)} papers with full text (skipped {len(papers) - len(papers_with_fulltext)} without)")

        saved_files, _, _ = self.save_results(papers_with_fulltext, run_dir)
        log.info(f"Saved {len(saved_files)} records with full text to {run_dir}")
        all_saved_files.extend(saved_files)

        log.info(f"Completed {len(queries)} search run(s). Total saved files: {len(all_saved_files)}")
        return all_saved_files