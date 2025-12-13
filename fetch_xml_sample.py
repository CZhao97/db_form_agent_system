from Bio import Entrez
import ssl
import re

# Fix for SSL certificate issue if any
ssl._create_default_https_context = ssl._create_unverified_context

Entrez.email = "laozc@student.ubc.ca"

pmcid = "PMC7095355" # Known open access paper

try:
    print(f"Fetching XML for {pmcid} from NCBI...")
    handle = Entrez.efetch(db="pmc", id=pmcid, retmode="xml")
    xml_content = handle.read()
    handle.close()
    
    # Decode bytes to string if needed
    if isinstance(xml_content, bytes):
        xml_content = xml_content.decode("utf-8")
        
    print("Successfully fetched XML!")
    
    # Find table-wrap
    match = re.search(r'(<table-wrap.*?</table-wrap>)', xml_content, re.DOTALL)
    if match:
        print("Found table-wrap:")
        print(match.group(1))
    else:
        print("No table-wrap found in this paper.")
        # Try to find just table
        match = re.search(r'(<table.*?</table >)', xml_content, re.DOTALL)
        if match:
             print("Found table:")
             print(match.group(1))
        else:
             print("No table found.")
    
except Exception as e:
    print(f"Error: {e}")
