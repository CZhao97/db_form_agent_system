import os
import ftplib
import tarfile
import re
import xml.etree.ElementTree as ET
from datetime import datetime
import time
from tqdm import tqdm

# --- CONFIGURATION ---
START_YEAR = 1970
END_YEAR = 2025
DOWNLOAD_DIR = "./pmc_bulk_data"
EXTRACT_DIR = "./pmc_extracted_text"
# Set to True to actually download. Set to False to just see what would be downloaded.
EXECUTE_DOWNLOAD = True 
DELETE_AFTER_PROCESSING = True # Delete tar.gz after extraction to save space 

# NCBI FTP details
FTP_HOST = "ftp.ncbi.nlm.nih.gov"
BASE_DIR = "/pub/pmc/oa_bulk/"
SUBDIRS = ["oa_comm/xml", "oa_noncomm/xml"] # Commercial and Non-Commercial subsets

def get_ftp_file_list(ftp, subdir):
    """
    Connects to FTP and lists all 'baseline' tar.gz files.
    """
    files = []
    full_subdir = f"{BASE_DIR}{subdir}"
    try:
        ftp.cwd(full_subdir)
        listing = []
        ftp.retrlines("LIST", listing.append)
        
        # Parse listing to find baseline files
        # Pattern: oa_comm_xml.PMC00xxxxxx.baseline.2024-12-18.tar.gz
        for line in listing:
            parts = line.split()
            filename = parts[-1]
            if "baseline" in filename and filename.endswith(".tar.gz"):
                files.append(f"{full_subdir}/{filename}")
    except Exception as e:
        print(f"Error listing {full_subdir}: {e}")
    finally:
        ftp.cwd("/") # Reset to root
    return files

def download_file(ftp, ftp_path, local_path):
    """
    Downloads a file with a progress bar. Resumes if file exists but is incomplete.
    """
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    # Get remote size
    ftp.voidcmd('TYPE I')
    remote_size = ftp.size(ftp_path)
    
    if os.path.exists(local_path):
        local_size = os.path.getsize(local_path)
        if local_size == remote_size:
            print(f"Skipping {ftp_path} (already downloaded)")
            return
        # If incomplete, we restart (simple retry) or resume. 
        # For simplicity here, we overwrite.
        print(f"Redownloading incomplete file: {ftp_path}")
    
    print(f"Downloading {ftp_path} ({remote_size / (1024*1024):.1f} MB)...")
    
    with open(local_path, 'wb') as f:
        with tqdm(total=remote_size, unit='B', unit_scale=True, desc=os.path.basename(ftp_path)) as pbar:
            def callback(data):
                f.write(data)
                pbar.update(len(data))
            
            ftp.retrbinary(f"RETR {ftp_path}", callback)

def parse_and_extract(tar_path):
    """
    Reads a tar.gz stream, parses XMLs, filters by Year, and extracts Full Text.
    """
    print(f"Processing {tar_path}...")
    try:
        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith(".xml"):
                    continue

                # Extract file object (in memory)
                f = tar.extractfile(member)
                if f:
                    try:
                        content = f.read()
                        root = ET.fromstring(content)
                        
                        # --- 1. CHECK DATE ---
                        # Look for <pub-date pub-type="epub"> or "ppub"
                        pub_year = None
                        for date_node in root.findall(".//pub-date"):
                            year_node = date_node.find("year")
                            if year_node is not None and year_node.text:
                                try:
                                    y = int(year_node.text)
                                    # Prefer epub date, but take any valid year
                                    pub_year = y
                                    if START_YEAR <= y <= END_YEAR:
                                        break
                                except ValueError:
                                    continue
                        
                        if not pub_year or not (START_YEAR <= pub_year <= END_YEAR):
                            continue # Skip this article
                        
                        # --- 2. EXTRACT TEXT ---
                        # Simple JATS extraction
                        article_meta = root.find(".//article-meta")
                        title = "No Title"
                        if article_meta:
                            t_node = article_meta.find(".//article-title")
                            if t_node is not None:
                                title = "".join(t_node.itertext())
                        
                        body = root.find(".//body")
                        body_text = ""

                        def clean_text(element_text):
                            if not element_text: return ""
                            return re.sub(r'\s+', ' ', element_text).strip()

                        def parse_table(table_node):
                            rows = []
                            # thead
                            thead = table_node.find("thead")
                            if thead is not None:
                                for tr in thead.findall("tr"):
                                    cells = [clean_text("".join(th.itertext())) for th in tr.findall("th")]
                                    if not cells: cells = [clean_text("".join(td.itertext())) for td in tr.findall("td")]
                                    rows.append("| " + " | ".join(cells) + " |")
                                    rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
                            # tbody
                            tbody = table_node.find("tbody")
                            if tbody is not None:
                                for tr in tbody.findall("tr"):
                                    cells = [clean_text("".join(td.itertext())) for td in tr.findall("td")]
                                    rows.append("| " + " | ".join(cells) + " |")
                            return "\n".join(rows)

                        if body is not None:
                            sections_text = []
                            # Try to find top-level sections
                            secs = body.findall("./sec")
                            
                            if secs:
                                for sec in secs:
                                    sec_title = clean_text(sec.findtext("title"))
                                    if sec_title:
                                        sections_text.append(f"\n## {sec_title}")
                                    
                                    # Get all paragraphs in this section (flattened)
                                    text_parts = [clean_text("".join(p.itertext())) for p in sec.findall(".//p")]
                                    
                                    # Get all tables in this section
                                    tables = []
                                    for tw in sec.findall(".//table-wrap"):
                                        label = clean_text(tw.findtext("label"))
                                        caption = clean_text("".join(tw.find("caption").itertext())) if tw.find("caption") is not None else ""
                                        t_content = ""
                                        table_node = tw.find("table")
                                        if table_node is not None:
                                            t_content = parse_table(table_node)
                                        table_str = f"\n\n**Table: {label}**\n*{caption}*\n{t_content}\n"
                                        tables.append(table_str)
                                    
                                    sec_content = "\n".join(part for part in text_parts if part)
                                    if tables:
                                        sec_content += "\n" + "\n".join(tables)
                                    
                                    if sec_content:
                                        sections_text.append(sec_content)
                            else:
                                # No sections, just grab everything from body
                                text_parts = [clean_text("".join(p.itertext())) for p in body.findall(".//p")]
                                
                                tables = []
                                for tw in body.findall(".//table-wrap"):
                                    label = clean_text(tw.findtext("label"))
                                    caption = clean_text("".join(tw.find("caption").itertext())) if tw.find("caption") is not None else ""
                                    t_content = ""
                                    table_node = tw.find("table")
                                    if table_node is not None:
                                        t_content = parse_table(table_node)
                                    table_str = f"\n\n**Table: {label}**\n*{caption}*\n{t_content}\n"
                                    tables.append(table_str)
                                
                                body_content = "\n".join(part for part in text_parts if part)
                                if tables:
                                    body_content += "\n" + "\n".join(tables)
                                sections_text.append(body_content)

                            body_text = "\n\n".join(sections_text)
                        
                        full_content = f"Title: {title}\nYear: {pub_year}\n\n{body_text}"
                        
                        # --- 3. SAVE ---
                        # Use PMCID as filename if available, else tar member name
                        pmcid_node = root.find(".//article-id[@pub-id-type='pmc']")
                        out_name = pmcid_node.text if pmcid_node is not None else os.path.basename(member.name)
                        out_name = f"{out_name}.txt"
                        
                        out_path = os.path.join(EXTRACT_DIR, out_name)
                        with open(out_path, "w", encoding="utf-8") as out_f:
                            out_f.write(full_content)
                            
                    except Exception as e:
                        # XML parsing errors are common in bulk data
                        pass
    except Exception as e:
        print(f"Error reading tar {tar_path}: {e}")

def main():
    if EXECUTE_DOWNLOAD:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        os.makedirs(EXTRACT_DIR, exist_ok=True)

    # 1. Get List of Files
    all_remote_files = []
    try:
        print("Connecting to FTP to retrieve file list...")
        with ftplib.FTP(FTP_HOST) as ftp:
            ftp.login() 
            for subdir in SUBDIRS:
                print(f"Scanning {subdir}...")
                files = get_ftp_file_list(ftp, subdir)
                all_remote_files.extend(files)
    except Exception as e:
        print(f"Error retrieving file list: {e}")
        return
            
    print(f"Found {len(all_remote_files)} baseline archives to process.")

    if not EXECUTE_DOWNLOAD:
        print("Dry run complete. Set EXECUTE_DOWNLOAD = True to proceed.")
        return

    # 2. Pipeline Loop: Download -> Process -> Delete
    print("Starting pipeline: Download -> Extract -> Delete")
    
    ftp = None
    try:
        ftp = ftplib.FTP(FTP_HOST)
        ftp.login()
        
        for remote_file in tqdm(all_remote_files, desc="Overall Progress"):
            local_fname = remote_file.replace("/", "_") # Flatten structure
            local_path = os.path.join(DOWNLOAD_DIR, local_fname)
            
            # --- Step A: Download with Retry ---
            success = False
            retries = 3
            while retries > 0:
                try:
                    # Ensure connection is alive
                    try:
                        ftp.voidcmd("NOOP")
                    except Exception:
                        print("Reconnecting FTP...")
                        try:
                            ftp.close()
                        except:
                            pass
                        ftp = ftplib.FTP(FTP_HOST)
                        ftp.login()

                    download_file(ftp, remote_file, local_path)
                    success = True
                    break
                except Exception as e:
                    print(f"Download error for {remote_file}: {e}")
                    retries -= 1
                    time.sleep(5)
            
            if not success:
                print(f"Skipping {remote_file} due to persistent download failure.")
                continue

            # --- Step B: Process ---
            try:
                parse_and_extract(local_path)
            except Exception as e:
                print(f"Processing error for {local_path}: {e}")

            # --- Step C: Cleanup ---
            if DELETE_AFTER_PROCESSING:
                try:
                    if os.path.exists(local_path):
                        os.remove(local_path)
                        # print(f"Deleted {local_path}") 
                except Exception as e:
                    print(f"Error deleting {local_path}: {e}")

    except KeyboardInterrupt:
        print("\nPipeline interrupted by user.")
    except Exception as e:
        print(f"\nCritical pipeline error: {e}")
    finally:
        if ftp:
            try:
                ftp.quit()
            except:
                pass

if __name__ == "__main__":
    main()