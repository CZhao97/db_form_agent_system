#!/usr/bin/env python3
import os
import json
import glob
import gzip
import tarfile
import logging
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
from tqdm import tqdm

# LangChain imports
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_core.documents import Document

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("offline_ingester")

class PMCDownloader:
    """Downloads Open Access XML bulk archives from NCBI."""
    BASE_URL = "https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_bulk/"
    
    def __init__(self, download_dir: str):
        self.download_dir = os.path.join(download_dir, "pmc")
        os.makedirs(self.download_dir, exist_ok=True)

    def fetch_file_list(self) -> List[str]:
        """Scrapes the FTP directory to find the latest commercial/non-commercial XML tar.gz files."""
        try:
            url = self.BASE_URL + "oa_comm/xml/"
            log.info(f"Fetching file list from {url}...")
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            
            # Simple regex to find tar.gz links
            import re
            # Look for href="oa_comm_xml.PMC....tar.gz"
            links = re.findall(r'href="(oa_comm_xml\.PMC[^"]+\.tar\.gz)"', r.text)
            
            full_urls = [url + l for l in links]
            log.info(f"Found {len(full_urls)} archives.")
            return full_urls
        except Exception as e:
            log.error(f"Failed to fetch file list: {e}")
            return []

    def download_and_extract(self, url: str):
        filename = url.split('/')[-1]
        local_path = os.path.join(self.download_dir, filename)
        
        if not os.path.exists(local_path):
            log.info(f"Downloading {url}...")
            try:
                with requests.get(url, stream=True) as r:
                    r.raise_for_status()
                    with open(local_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
            except Exception as e:
                log.error(f"Failed to download {url}: {e}")
                return None
        
        extract_path = os.path.join(self.download_dir, "extracted")
        os.makedirs(extract_path, exist_ok=True)
        
        log.info(f"Extracting {filename} to {extract_path}...")
        try:
            if filename.endswith(".tar.gz") or filename.endswith(".tgz"):
                with tarfile.open(local_path, "r:gz") as tar:
                    tar.extractall(path=extract_path)
            elif filename.endswith(".zip"):
                import zipfile
                with zipfile.ZipFile(local_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_path)
        except Exception as e:
            log.error(f"Failed to extract {filename}: {e}")
            return None
            
        return extract_path

class S2Downloader:
    """Downloads Semantic Scholar Open Research Corpus (S2ORC) via Datasets API."""
    API_URL = "https://api.semanticscholar.org/datasets/v1"
    
    def __init__(self, download_dir: str, api_key: Optional[str] = None):
        self.download_dir = os.path.join(download_dir, "s2")
        self.headers = {"x-api-key": api_key} if api_key else {}
        os.makedirs(self.download_dir, exist_ok=True)

    def get_download_links(self, dataset="papers") -> List[str]:
        """
        Gets the latest release download links. 
        """
        try:
            # 1. Get available releases
            r = requests.get(f"{self.API_URL}/release/", headers=self.headers)
            r.raise_for_status()
            releases = r.json()
            if not releases:
                return []
            latest = releases[-1] # Get latest release ID
            
            # 2. Get download links
            url = f"{self.API_URL}/release/{latest}/dataset/{dataset}"
            r = requests.get(url, headers=self.headers)
            r.raise_for_status()
            data = r.json()
            return data.get("files", [])
        except Exception as e:
            log.error(f"S2 Download Error: {e}")
            return []

def parse_jats_xml(file_path: str) -> Optional[Document]:
    """Parses a local PMC JATS XML file into a LangChain Document."""
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # 1. Metadata
        article_meta = root.find(".//article-meta")
        if article_meta is None: 
            # Fallback for some XML structures
            article_meta = root.find(".//front/article-meta")
            
        if article_meta is None:
            return None
        
        title_node = article_meta.find(".//article-title")
        title = "".join(title_node.itertext()) if title_node is not None else "No Title"
        
        pmid = article_meta.findtext(".//article-id[@pub-id-type='pmid']")
        doi = article_meta.findtext(".//article-id[@pub-id-type='doi']")
        
        # 2. Abstract
        abstract_node = article_meta.find(".//abstract")
        abstract_text = ""
        if abstract_node:
            abstract_text = " ".join("".join(p.itertext()) for p in abstract_node.findall(".//p"))
            
        # 3. Body Text (Simple extraction)
        body = root.find(".//body")
        body_text = ""
        if body:
            # Extract text from paragraphs, preserving order
            body_text = "\n\n".join("".join(p.itertext()) for p in body.findall(".//p"))
        
        full_text = f"{title}\n\nABSTRACT:\n{abstract_text}\n\nBODY:\n{body_text}"
        
        if len(full_text) < 200: # Skip stubs/empty
            return None

        return Document(
            page_content=full_text,
            metadata={
                "source": "LocalPMC",
                "title": title,
                "doi": doi or "",
                "pmid": pmid or "",
                "file_path": file_path,
                "has_fulltext": True
            }
        )
    except Exception as e:
        log.warning(f"Failed to parse {file_path}: {e}")
        return None

def build_index(data_dir: str, index_path: str):
    """Walks through data_dir, parses XMLs, and builds FAISS index."""
    log.info(f"Scanning {data_dir} for XML files...")
    # Find all .xml or .nxml files recursively
    xml_files = glob.glob(f"{data_dir}/**/*.xml", recursive=True) + \
                glob.glob(f"{data_dir}/**/*.nxml", recursive=True)
    
    log.info(f"Found {len(xml_files)} files. Parsing...")
    
    documents = []
    # Use ProcessPool if parsing logic is heavy, ThreadPool for I/O bound
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(parse_jats_xml, f) for f in xml_files]
        for future in tqdm(as_completed(futures), total=len(xml_files)):
            doc = future.result()
            if doc:
                documents.append(doc)
    
    if not documents:
        log.error("No valid documents found. Exiting.")
        return

    log.info(f"Embedding {len(documents)} documents. This may take a while...")
    # Using SentenceTransformerEmbeddings compatible with the environment
    embeddings = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")
    
    # Process in batches to avoid OOM
    batch_size = 1000
    vector_store = None
    
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i+batch_size]
        log.info(f"Processing batch {i}-{i+len(batch)}...")
        if vector_store is None:
            vector_store = FAISS.from_documents(batch, embeddings)
        else:
            vector_store.add_documents(batch)
            
    log.info(f"Saving index to {index_path}...")
    vector_store.save_local(index_path)
    log.info("Done.")

if __name__ == "__main__":
    # Configuration
    WORK_DIR = "./offline_data"
    INDEX_DIR = "./pmc_faiss_index"
    
    # Ensure directories exist
    os.makedirs(WORK_DIR, exist_ok=True)
    
    # 1. Download (Example with PMC)
    downloader = PMCDownloader(WORK_DIR)
    
    # Check if we have data
    existing_xmls = glob.glob(f"{WORK_DIR}/**/*.xml", recursive=True) + \
                    glob.glob(f"{WORK_DIR}/**/*.nxml", recursive=True)
                    
    if not existing_xmls:
        log.info("No XML files found. Attempting to download a sample archive...")
        files = downloader.fetch_file_list()
        if files:
            # Pick the smallest one (PMC000xxxxxx usually) or just the first one
            # Sort to likely get PMC000 first
            files.sort()
            target = files[0]
            log.info(f"Selected {target} for download.")
            downloader.download_and_extract(target)
        else:
            log.error("Could not find any files to download.")
    
    # 2. Build Index
    # Ensure you have some .xml files in ./offline_data/pmc/extracted/ before running
    # For testing, we can look in the whole WORK_DIR
    build_index(WORK_DIR, INDEX_DIR)
