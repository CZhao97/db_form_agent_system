from __future__ import annotations
import os, re, csv, json, time, html, string, logging, pathlib, hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Type

import requests
import xml.etree.ElementTree as ET
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pydantic import BaseModel, Field
from Bio import Entrez
from http.client import IncompleteRead

from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text as pdf_extract_text

import pdfplumber
import fitz
from langchain.tools import BaseTool


log = logging.getLogger("fulltext_journal_search")
# Only set basicConfig if root logger not already configured
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

class FullTextJournalSearchInput(BaseModel):
    query: str = Field(..., description="Academic search terms")
    max_results: int = Field(20, description="Maximum number of results to return")
    include_preprints: bool = Field(True, description="Include arXiv")
    include_pubmed: bool = Field(True, description="Include PubMed/PMC")
    include_crossref: bool = Field(False, description="Include Crossref (API on/off)")
    include_biorxiv: bool = Field(False, description="Include bioRxiv (API on/off)")

def make_requests_session(total_retries: int = 5, backoff: float = 0.5, status_forcelist=(429,500,502,503,504)):
    retry = Retry(
        total=total_retries, read=total_retries, connect=total_retries,
        backoff_factor=backoff, status_forcelist=status_forcelist,
        allowed_methods=frozenset(["GET","POST"]), raise_on_status=False,
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

def first(val, *fallbacks):
    for v in (val, *fallbacks):
        if v: return v
    return ""

def extract_year_from_crossref(item: dict) -> str:
    p = item.get("published-print", {}).get("date-parts") or item.get("published-online", {}).get("date-parts")
    if p and p[0]: return str(p[0][0])
    return ""

def strip_html_tags(s: str) -> str:
    if not s: return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()

def jats_nodes_to_sections(root: ET.Element) -> List[Dict[str, str]]:
    """Turn JATS <body>/<sec> into a list of {title, text} sections."""
    sections: List[Dict[str, str]] = []
    
    # Prefer <body>, but accept top-level <sec> as fallback
    body = root.find(".//body")
    targets = [body] if body is not None else root.findall(".//sec")
    
    def clean_text(element_text):
        if not element_text: return ""
        return re.sub(r'\s+', ' ', element_text).strip()

    for target_node in targets:
        # Find all sections directly under the target node
        for sec in target_node.findall("./sec"):
            title = clean_text(sec.findtext("title"))
            # Concatenate all paragraph texts within this section
            text_parts = [clean_text("".join(p.itertext())) for p in sec.findall(".//p")]
            text = "\n".join(part for part in text_parts if part)
            if title or text:
                sections.append({"title": title, "text": text})

    # Fallback: if no structured sections but body exists, keep plain body text
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


class FullTextJournalSearchTool(BaseTool):
    name: str = "fulltext_journal_search"
    description: str = "Fetch articles from PubMed/PMC, Crossref, and (optionally) arXiv/bioRxiv; save full context (full text) locally when available."
    args_schema: Type[FullTextJournalSearchInput] = FullTextJournalSearchInput

    _entrez_email: str = "laozc@student.ubc.ca"
    _max_retries: int = 3
    _backoff_base: float = 1.5
    _http: requests.Session
    # Exposed configuration flags (declare as fields so pydantic/BaseTool accepts them)
    include_pubmed: bool = True
    include_preprints: bool = False
    results_base_dir: Optional[pathlib.Path] = None

    def __init__(self, **data):
        super().__init__(**data)
        self._http = make_requests_session()
        self._current_run_assets_dir: Optional[pathlib.Path] = None
        self.include_pubmed = data.get("include_pubmed", True)
        self.include_preprints = data.get("include_preprints", True)

    # ---------------- Entrez ----------------
    def entrez_call(self, func, *args, **kwargs):
        last_err = None
        for attempt in range(self._max_retries):
            try:
                return func(*args, **kwargs)
            except (IncompleteRead, Exception) as e:
                last_err = e
                log.warning(f"Entrez error (attempt {attempt+1}/{self._max_retries}): {e}")
                time.sleep((self._backoff_base ** attempt))
        if last_err: raise last_err

    # ---------------- PubMed / PMC ----------------
    def search_pubmed_pmc(self, query: str, max_results: int) -> List[Dict]:
        Entrez.email = self._entrez_email
        results: List[Dict] = []
        try:
            h = self.entrez_call(Entrez.esearch, db="pubmed", term=query, retmax=max_results, sort="relevance")
            search = self.entrez_call(Entrez.read, h)
            pmids = search.get("IdList", [])
            if not pmids: return results

            hsum = self.entrez_call(Entrez.esummary, db="pubmed", id=",".join(pmids), retmode="xml")
            recs = self.entrez_call(Entrez.read, hsum)

            for rec in recs:
                pmid = rec.get("Id", "")
                title = rec.get("Title", "") or ""
                jname = first(rec.get("FullJournalName"), rec.get("Source"), "")
                pubdate = rec.get("PubDate", "")
                doi = rec.get("DOI", "")
                authors = rec.get("AuthorList", [])
                author_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")

                abstract = ""
                try:
                    hf = self.entrez_call(Entrez.efetch, db="pubmed", id=pmid, retmode="xml")
                    art = self.entrez_call(Entrez.read, hf)
                    ab = art["PubmedArticle"][0]["MedlineCitation"]["Article"].get("Abstract", {}).get("AbstractText", [])
                    abstract = " ".join([str(x) for x in ab]) or ""
                except Exception:
                    pass

                # Full text from PMC
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
                    "pdf_path": "",
                    "html_path": "",
                    "has_fulltext": bool(full_text),
                })
                time.sleep(0.34)
        except Exception as e:
            log.error(f"PubMed search error: {e}")
        return results

    def get_pmc_fulltext(self, pmid: str) -> Tuple[str, List[Dict[str, str]]]:
        try:
            link_handle = self.entrez_call(Entrez.elink, dbfrom="pubmed", db="pmc", id=pmid)
            link_data = self.entrez_call(Entrez.read, link_handle)
            pmcids = [
                lnk["Id"]
                for ls in link_data
                for lset in ls.get("LinkSetDb", []) if lset.get("DbTo") == "pmc"
                for lnk in lset.get("Link", []) if "Id" in lnk
            ]
            if not pmcids:
                return "", []

            pmc_handle = self.entrez_call(Entrez.efetch, db="pmc", id=pmcids[0], retmode="xml")
            root = ET.parse(pmc_handle).getroot()
            
            sections = jats_nodes_to_sections(root)
            full_text = sections_to_markdown(sections)
            
            return full_text, sections
        except Exception as e:
            log.debug(f"PMC full-text extraction error for PMID {pmid}: {e}")
            return "", []

    # ---------------- arXiv (PDF → text) ----------------
    def search_arxiv(self, query: str, max_results: int) -> List[Dict]:
        results: List[Dict] = []
        try:
            url = "http://export.arxiv.org/api/query"
            params = {"search_query": f'all:"{query}"', "start": 0, "max_results": max_results,
                      "sortBy": "relevance", "sortOrder": "descending"}
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
                    if title_attr.lower() == "pdf" or (rel == "related" and href.endswith(".pdf")):
                        pdf_url = href
                if not pdf_url and arxiv_id:
                    m = re.search(r"arxiv.org/abs/(\S+)", arxiv_id)
                    if m:
                        pdf_url = f"https://arxiv.org/pdf/{m.group(1)}.pdf"

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

    # # ---------------- bioRxiv ----------------
    # def search_biorxiv(self, query: str, max_results: int) -> List[Dict]:
    #     results: List[Dict] = []
    #     try:
    #         end_date = datetime.utcnow()
    #         start_date = end_date - timedelta(days=3*365)
    #         url = f"https://api.biorxiv.org/details/biorxiv/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
    #         r = self._http.get(url, timeout=60); r.raise_for_status()
    #         data = r.json()
    #         if not (data.get("messages") and data["messages"][0].get("status") == "ok"):
    #             return results

    #         ql = (query or "").lower()
    #         for p in data.get("collection", []):
    #             title = p.get("title","") or ""; abstract = p.get("abstract","") or ""
    #             if ql and (ql not in title.lower() and ql not in abstract.lower()):
    #                 continue

    #             doi = (p.get("doi") or "").strip()
    #             version = str(p.get("version") or "").strip()
    #             if not doi: continue

    #             base = f"https://www.biorxiv.org/content/{doi}"
    #             landing  = f"{base}v{version}" if version else base
    #             html_url = f"{landing}.full"
    #             pdf_url  = f"{landing}.full.pdf"

    #             authors_raw = p.get("authors","") or ""
    #             author_list = []
    #             for a in [x.strip() for x in authors_raw.split(";") if x.strip()]:
    #                 if "," in a:
    #                     last, first = a.split(",",1); author_list.append(f"{first.strip()} {last.strip()}")
    #                 else:
    #                     author_list.append(a)
    #             author_str = ", ".join(author_list[:3]) + (" et al." if len(author_list) > 3 else "")

    #             results.append({
    #                 "source": "bioRxiv",
    #                 "ids": {"doi": doi},
    #                 "title": title,
    #                 "authors": author_str,
    #                 "journal": "bioRxiv preprint",
    #                 "pubdate": p.get("date","") or "",
    #                 "doi": doi,
    #                 "url": landing,
    #                 "abstract": abstract,
    #                 "html_url": html_url,
    #                 "pdf_url": pdf_url,
    #                 "full_text": "",
    #                 "sections": [],
    #                 "pdf_path": "",
    #                 "html_path": "",
    #                 "has_fulltext": False,
    #             })
    #             if len(results) >= max_results:
    #                 break
    #     except Exception as e:
    #         log.error(f"bioRxiv search error: {e}")
    #     return results

    # def get_biorxiv_jats_fulltext(self, doi: str, version: Optional[str]) -> Tuple[str, List[Dict[str, str]], Optional[str]]:
    #     """Fetch and parse bioRxiv JATS XML. Returns (full_text, sections, xml_path)."""
    #     try:
    #         base = f"https://www.biorxiv.org/content/{doi}"
    #         xml_url = f"{base}v{version}.source.xml" if (version and version.strip()) else f"{base}.source.xml"

    #         r = self._http.get(xml_url, timeout=60)
    #         r.raise_for_status()
            
    #         xml_path = None
    #         if self._current_run_assets_dir:
    #             xml_name = sanitize_filename(doi + (f"v{version}" if version else "")) + ".source.xml"
    #             xml_fpath = self._current_run_assets_dir / xml_name
    #             xml_fpath.write_bytes(r.content)
    #             xml_path = str(xml_fpath)

    #         root = ET.fromstring(r.content)
    #         sections = jats_nodes_to_sections(root)
    #         full_text = sections_to_markdown(sections)
    #         return full_text, sections, xml_path
    #     except Exception as e:
    #         log.debug(f"bioRxiv JATS fetch/parse failed for {doi}v{version or ''}: {e}")
    #         return "", [], None

    # # ---------------- Crossref ----------------
    # def search_crossref(self, query: str, max_results: int) -> List[Dict]:
    #     # (Function is unchanged)
    #     results: List[Dict] = []
    #     try:
    #         url = "https://api.crossref.org/works"
    #         params = {"query": query, "rows": max_results, "sort": "relevance", "order": "desc"}
    #         r = self._http.get(url, params=params, timeout=30); r.raise_for_status()
    #         data = r.json()
    #         for item in data.get("message", {}).get("items", []):
    #             title = " ".join(item.get("title", []) or [])
    #             if not title: continue
    #             authors_fmt = []
    #             for a in item.get("author", []) or []:
    #                 given, family = a.get("given",""), a.get("family","")
    #                 if given and family: authors_fmt.append(f"{given} {family}")
    #             author_str = ", ".join(authors_fmt[:3]) + (" et al." if len(authors_fmt) > 3 else "")
    #             journal = " ".join(item.get("container-title", []) or [])
    #             pubyear = extract_year_from_crossref(item)
    #             doi = item.get("DOI","") or ""
    #             landing = item.get("URL","") or ""
    #             abstract = strip_html_tags(item.get("abstract",""))

    #             pdf_url = ""
    #             for link in item.get("link", []) or []:
    #                 if link.get("content-type","").lower() == "application/pdf" and link.get("URL"):
    #                     pdf_url = link["URL"]; break

    #             results.append({
    #                 "source": "CrossRef",
    #                 "ids": {"doi": doi},
    #                 "title": title,
    #                 "authors": author_str,
    #                 "journal": journal,
    #                 "pubdate": pubyear,
    #                 "doi": doi,
    #                 "url": landing,
    #                 "abstract": abstract,
    #                 "pdf_url": pdf_url,
    #                 "full_text": "",
    #                 "sections": [],
    #                 "pdf_path": "",
    #                 "html_path": "",
    #                 "has_fulltext": False,
    #             })
    #     except Exception as e:
    #         log.error(f"CrossRef search error: {e}")
    #     return results

    # ---------------- Fetchers & Parsers ----------------
    def download_to_path(self, url: str, path: pathlib.Path) -> bool:
        # (Function is unchanged)
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
        # (Function is the same as the last corrected version)
        try:
            soup = BeautifulSoup(html_bytes, "lxml")
            main = soup.find("div", class_="fulltext-view") or \
                   soup.find("div", class_="content-block-markup") or \
                   soup.find("div", {"id":"page-content"}) or \
                   soup.find("div", {"class":re.compile(r"article|content|main", re.I)})

            if not main: main = soup.body or soup

            sections: List[Dict[str,str]] = []
            buf = []
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
        # (Function is unchanged)
        text, tables, figures = "", [], []
        try:
            if pdfplumber:
                with pdfplumber.open(str(pdf_path)) as pdf:
                    pages_text = [p.extract_text() or "" for p in pdf.pages]
                    text = "\n\n".join(filter(None, pages_text)).strip()
                    for i, page in enumerate(pdf.pages):
                        try:
                            for t_i, table in enumerate(page.extract_tables() or []):
                                tables.append({'page': i+1, 'table_index': t_i, 'rows': table})
                        except Exception: pass
            else:
                text = pdf_extract_text(str(pdf_path)) or ""

            if fitz:
                try:
                    doc = fitz.open(str(pdf_path))
                    for i in range(len(doc)):
                        for img in doc.get_page_images(i):
                            xref = img[0]
                            pix = fitz.Pixmap(doc, xref)
                            img_ext = "png" if pix.alpha else "jpg"
                            fname = f"{pdf_path.stem}_p{i+1}_img{xref}.{img_ext}"
                            fpath = assets_dir / fname
                            if pix.alpha: pix = fitz.Pixmap(fitz.csRGB, pix)
                            pix.save(str(fpath))
                            figures.append(str(fpath))
                    doc.close()
                except Exception: pass
        except Exception as e:
            log.debug(f"PDF multimodal extraction failed {pdf_path}: {e}")
        return text, tables, figures
    
    def clean_extracted_text(self, text: str, source: str = "") -> str:
        # (Function is unchanged)
        if not text: return ""
        t = re.sub(r"\r", "\n", text)
        t = re.sub(r"\n{3,}", "\n\n", t)
        t = re.sub(r"^\s*\d{1,3}\s*$", "", t, flags=re.M)
        m = re.search(r"\n\s*(references|bibliography)\b", t, flags=re.I)
        if m: t = t[:m.start()].strip()
        if source.lower() == "arxiv": t = re.sub(r"arXiv:\s*\S+", "", t)
        t = re.sub(r"[ \t]+", " ", t).strip()
        return t

    # ---------------- Dedup & Save ----------------
    def deduplicate(self, items: List[Dict]) -> List[Dict]:
        # (Function is unchanged)
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
        # (Function is unchanged)
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
    # ---------------- Orchestrator ----------------
    def _run(self, query: str, max_results: int = 20, include_preprints: bool = True) -> List[str]:
        """
        Backward-compatible:
        - Input:  query is still a str (per args_schema)
        - Output: List[str] of saved file paths (flattened across all runs)

        New flexibility:
        - If `query` is a JSON array string (e.g., '["q1","q2"]'), run each.
        - If `query` contains '||', split on '||' into multiple queries.
        - Otherwise, treat as a single query.
        """
        import json
        from datetime import datetime
        import pathlib

        # Allow Entrez email override
        try:
            Entrez.email = os.environ.get("ENTREZ_EMAIL", self._entrez_email)
        except Exception:
            pass

        # --- Normalize into a list of queries without changing args_schema ---
        queries: List[str] = []
        q_str = (query or "").strip()
        if q_str.startswith("[") and q_str.endswith("]"):
            try:
                parsed = json.loads(q_str)
                if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                    queries = [x.strip() for x in parsed if x and x.strip()]
            except Exception:
                # fall back to single
                queries = [q_str]
        if not queries:
            # support simple delimiter for multiple variants
            if "||" in q_str:
                queries = [x.strip() for x in q_str.split("||") if x and x.strip()]
            else:
                queries = [q_str] if q_str else []

        if not queries:
            log.info("No query provided.")
            return []

        all_saved_files: List[str] = []
        
        # Check if a session directory is already set (for multiple searches in one user query)
        session_dir = os.environ.get("SEARCH_SESSION_DIR")
        
        if session_dir:
            # Reuse existing session directory
            run_dir = pathlib.Path(session_dir).resolve()
            log.info(f"Reusing existing session directory: {run_dir}")
        else:
            # Create ONE timestamp for ALL queries (single folder per search session)
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            
            # Prefer an explicit results_base_dir attribute if the object was constructed with one.
            # Fallback to environment variable SEARCH_RESULTS_DIR, then to the repository default.
            try:
                configured = getattr(self, "results_base_dir", None)
            except Exception:
                configured = None

            if configured:
                base_dir = pathlib.Path(configured).resolve()
            else:
                base_dir = pathlib.Path(os.environ.get("SEARCH_RESULTS_DIR", pathlib.Path(__file__).resolve().parent.parent / "searching_results")).resolve()

            # Single run directory for all queries
            run_dir = (base_dir / f"run_{ts}").resolve()
        
        assets_dir = run_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        self._current_run_assets_dir = assets_dir
        
        all_results: List[Dict] = []

        for idx, q in enumerate(queries, start=1):
            log.info(f"Starting search #{idx}/{len(queries)} for query: {q!r}; saving to {run_dir}")

            all_results: List[Dict] = []

            if self.include_pubmed:
                log.info(f"[{idx}/{len(queries)}] Searching PubMed/PMC…")
                try:
                    all_results.extend(self.search_pubmed_pmc(q, max_results))
                except Exception as e:
                    log.error(f"PubMed/PMC search error for '{q}': {e}")

            # Note: searches are performed above respecting self.include_pubmed and self.include_preprints

            # (Crossref/bioRxiv remain disabled exactly as in your current code)

        # Deduplicate across ALL queries combined
        papers = self.deduplicate(all_results)
        log.info(f"Found {len(all_results)} results total, {len(papers)} unique. Fetching full text...")

        for p in papers:
            if p.get("has_fulltext"):
                continue

            source = p.get("source", "")
            pdf_url = p.get("pdf_url")

            # --- PDF (final fallback for all sources) ---
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

        # Sort papers: fulltext first, then by source priority
        priority = {"PubMed": 0, "CrossRef": 1, "arXiv": 2, "bioRxiv": 2}
        papers.sort(key=lambda x: (not x.get("has_fulltext", False), priority.get(x.get("source", ""), 99)))

        # ONLY save papers with full text
        papers_with_fulltext = [p for p in papers if p.get("has_fulltext", False)]
        log.info(f"Filtered to {len(papers_with_fulltext)} papers with full text (skipped {len(papers) - len(papers_with_fulltext)} without)")

        saved_files, _, _ = self.save_results(papers_with_fulltext, run_dir)
        log.info(f"Saved {len(saved_files)} records with full text to {run_dir}")
        all_saved_files.extend(saved_files)

        log.info(f"Completed {len(queries)} search run(s). Total saved files: {len(all_saved_files)}")
        return all_saved_files
