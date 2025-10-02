# pip install sentence-transformers
# pip install langchain-huggingface
# conda install -c pytorch faiss-cpu (python=3.13 not allowed)

## Reflection Workflow
## Revised by JUHEE
"""
End‑to‑End LC‑MS Protocol *Reflection* Workflow
----------------------------------------------
This refactor keeps the three‑agent (generator → critic → optimiser)
loop you already like – **but** every agent now shares the *same*
short‑term chat buffer, entity memory *and* a durable SQLite
check‑pointer, so they can see each other’s actions across
iterations or kernel restarts.

Run with:
    python reflection_workflow.py  # interactive CLI demo
"""
from __future__ import annotations

import datetime
import logging
import re, logging, warnings, sqlite3
from pathlib import Path
from typing import List

from langchain.memory import (
    ConversationBufferMemory,
    ConversationEntityMemory,
    CombinedMemory,
)
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, START, END
from langchain_google_vertexai import ChatVertexAI, VertexAIEmbeddings
from langchain.embeddings import SentenceTransformerEmbeddings
#from langchain.document_loaders import PyPDFLoader
#from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.vectorstores import InMemoryVectorStore
from langchain.chains import RetrievalQA
from langchain_core.messages import HumanMessage, SystemMessage
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

# ───────────────────────────── Logging ──────────────────────────────
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("reflection")


# ─────────────────────────── Embeddings ─────────────────────────────

logging.info(
    f"Loading SentenceTransformer embeddings"
)
model_name = "sentence-transformers/all-MiniLM-L6-v2"

try:
    embeddings = HuggingFaceEmbeddings(
         model_name=model_name,
   )
    logging.info("Embedding model loaded successfully.")
except Exception:
   embeddings = VertexAIEmbeddings(model_name="text-embedding-004")
   logging.info(f"model={embeddings.model_name}")

# --- Custom Knowledge Base Loader ---
def load_knowledge_base_from_json(filepath: Path) -> List[Document]:
    """Loads and transforms the enriched JSON data into LangChain Documents."""
    logging.info(f"Loading and processing knowledge base from {filepath}...")
    all_documents = []
    if not filepath.exists():
        logging.error(f"Knowledge base file not found: {filepath}")
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    for doc in data.get("documents", []):
        doc_name = doc.get("document_name", "Unknown")
        # Text Chunks
        for chunk in doc.get("chunk_id", []):
            all_documents.append(
                Document(
                    page_content=chunk.get("contextualized_text", ""),
                    metadata={
                        "source": doc_name,
                        "type": "text",
                        "chunk_id": chunk.get("chunk_id"),
                    },
                )
            )
        # Image Descriptions
        for image in doc.get("images", []):
            if image.get("vlm"):
                page_content = f"Image Caption: {image.get('caption', 'N/A')}\n\nAI-Generated Analysis:\n{i>
                all_documents.append(
                    Document(
                        page_content=page_content,
                        metadata={
                            "source": doc_name,
                            "type": "image",
                            "page_no": image.get("page_no"),
                            "image_id": image.get("image_id"),
                        },
                    )
                )
        # Table Descriptions
        for table in doc.get("tables", []):
            if table.get("vlm"):
                page_content = (
                    f"Table Caption: {table.get('caption', 'N/A')}\n\n"
                    f"AI-Generated Analysis:\n{table['vlm']}\n\n"
                    f"Table Data (Markdown):\n{table.get('markdown_text', '')}"
                )
                all_documents.append(
                    Document(
                        page_content=page_content,
                        metadata={
                            "source": doc_name,
                            "type": "table",
                            "page_no": table.get("page_no"),
                            "table_id": table.get("table_id"),
                        },
                    )
                )
    logging.info(
        f"Successfully created {len(all_documents)} documents for the knowledge base."
    )
    return all_documents

# Local path to save  the FAISS index
FAISS_INDEX_PATH = "FAISS_lcms"

# --- Knowledge Base Indexing ---
ENRICHED_DATA_FILE = Path("docling_all_output/enriched_data.json")
# all_docs = load_knowledge_base_from_json(ENRICHED_DATA_FILE)
# knowledge_base_store = InMemoryVectorStore(embedding=embeddings)
# if all_docs:
#     knowledge_base_store.add_documents(all_docs)

# Check if the FAISS index already exists
if os.path.exists(FAISS_INDEX_PATH):
    logging.info(f"Loading existing FAISS index from {FAISS_INDEX_PATH}...")
    knowledge_base_store = FAISS.load_local(
        FAISS_INDEX_PATH, embeddings, allow_dangerous_deserialization=True
    )
    logging.info("FAISS index loaded successfully.")
else:
    logging.info(f"No FAISS index found at {FAISS_INDEX_PATH}. Building a new one...")
    all_docs = load_knowledge_base_from_json(ENRICHED_DATA_FILE)
    if all_docs:
        knowledge_base_store = FAISS.from_documents(all_docs, embeddings)
        knowledge_base_store.save_local(FAISS_INDEX_PATH)
        logging.info(f"New FAISS index created and saved to {FAISS_INDEX_PATH}.")
    else:
        logging.warning("No documents loaded. Using an empty vector store.")
        knowledge_base_store = InMemoryVectorStore(embedding=embeddings)

# This retriever is now powered by our custom, enriched data.
textbook_retriever = knowledge_base_store.as_retriever(search_kwargs={"k": 5})

# This QA chain is used by the agents for fact-checking against our knowledge base.
textbook_qa = RetrievalQA.from_chain_type(
    llm=ChatVertexAI(model_name="gemini-2.0-flash", temperature=0.0),
    chain_type="stuff",
    retriever=textbook_retriever,
    verbose=False,
)

##################Change Version1 : ONLY PAGE_CONTENT #################

# ───────────────────────── Shared MEMORY ────────────────────────────
# --- The Bridge: This helper function now uses enriched retriever ---
def rag_snippet(query: str, n: int = 2) -> str:
    """Return *n* most similar passages from our knowledge base."""
    docs = textbook_retriever.get_relevant_documents(query)[:n]
    return "\n---\n".join(d.page_content for d in docs)


####################################Change Version1 END#################

####################################Change Version2: Use Page_content and metadata#################

# # ───────────────────────── Shared MEMORY ────────────────────────────
# # --- The Bridge: This helper function now uses enriched retriever ---
# def rag_snippet(query: str, n: int = 2) -> str:
#     """Return *n* most similar passages from our knowledge base."""
#     docs = textbook_retriever.get_relevant_documents(query)[:n]
#     formatted_strings = []
#     for i, doc in enumerate(docs, 1):
#         metadata = doc.metadata
#         doc_type = metadata.get("type", "unknown")
#         source = metadata.get("source", "Unknown Source")

#         header = f"--- Evidence {i} from: {source} (Type: {doc_type}"

#         if doc_type == "text":
#             chunk_id = metadata.get("chunk_id")
#             if chunk_id:
#                 header += f", Chunk ID: {chunk_id}"

#         elif doc_type == "image":
#             page_no = metadata.get("page_no")
#             image_id = metadata.get("image_id")
#             if page_no:
#                 header += f", Page: {page_no}"
#             if image_id:
#                 header += f", Image ID: {image_id}"

#         elif doc_type == "table":
#             page_no = metadata.get("page_no")
#             table_id = metadata.get("table_id")
#             if page_no:
#                 header += f", Page: {page_no}"
#             if table_id:
#                 header += f", Table ID: {table_id}"

#         header += ") ---"

#         content = doc.page_content
#         formatted_strings.append(f"{header}\n{content}")

#     return "\n\n".join(formatted_strings)

####################################Change Version2 END#################


##################Original (Chen's code) #################

# ─────────────────────── Textbook Retriever (RAG) ───────────────────
# _DOC_DIR = Path("/home/chen/GNPS_SIM/agent/chem_agent/doc")


# def build_textbook_retriever(pdf_dir: Path = _DOC_DIR, k: int = 8):
#     pages: List = []
#     for pdf in pdf_dir.glob("*.pdf"):
#         try:
#             pages.extend(PyPDFLoader(str(pdf)).load())
#         except Exception as e:
#             warnings.warn(f"⚠️  Skipping {pdf.name}: {e}")

#     chunks = RecursiveCharacterTextSplitter(
#         chunk_size=1_000, chunk_overlap=200
#     ).split_documents(pages)
#     vs = InMemoryVectorStore(embedding=embeddings)
#     vs.add_documents(chunks)
#     retriever = vs.as_retriever(search_kwargs={"k": k})

#     qa = RetrievalQA.from_chain_type(
#         llm=ChatVertexAI(model_name="gemini-2.0-flash", temperature=0.0),
#         chain_type="stuff",
#         retriever=retriever,
#     )
#     return retriever, qa


# textbook_retriever, textbook_qa = build_textbook_retriever()


# # ───────────────────────── Shared MEMORY ────────────────────────────
# def rag_snippet(query: str, n: int = 2) -> str:
#     """Return *n* most similar textbook passages concatenated."""
#     docs = textbook_retriever.get_relevant_documents(query)[:n]
#     return "\n---\n".join(d.page_content for d in docs)

####################################Original (Chen's code) END#################

##CONTINUE FROM HERE
# ───────────────────────── Fixed SQLite Setup ────────────────────────────
def setup_sqlite_checkpointer(db_path: str = "reflection_run.db") -> SqliteSaver:
    """Properly initialize SQLite checkpointer"""
    try:
        # Ensure the database file exists
        db_file = Path(db_path)
        if not db_file.exists():
            db_file.touch()

        # Create connection and pass to SqliteSaver
        conn = sqlite3.connect(db_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn)
        log.info(f"SQLite checkpointer initialized: {db_path}")
        return checkpointer

    except Exception as e:
        log.error(f"Failed to create SQLite checkpointer: {e}")
        # Fallback to in-memory checkpointer
        from langgraph.checkpoint.memory import MemorySaver

        log.warning("Using in-memory checkpointer as fallback")
        return MemorySaver()
