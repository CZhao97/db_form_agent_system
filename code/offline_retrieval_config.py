import os
from typing import Dict, Any

DEFAULT_OFFLINE_SQLITE_PATH = os.environ.get("OFFLINE_SQLITE_PATH", "")
DEFAULT_OFFLINE_DOC_DIR = os.environ.get("OFFLINE_DOC_DIR", "")
DEFAULT_OFFLINE_INDEX_PATH = os.environ.get("OFFLINE_INDEX_PATH", "")
DEFAULT_ENABLE_OFFLINE_VECTOR_SEARCH = os.environ.get("ENABLE_OFFLINE_VECTOR_SEARCH", "0").strip().lower() in {"1", "true", "yes", "on"}


def default_offline_search_kwargs() -> Dict[str, Any]:
    return {
        "offline_sqlite_path": DEFAULT_OFFLINE_SQLITE_PATH,
        "offline_doc_dir": DEFAULT_OFFLINE_DOC_DIR,
        "offline_index_path": DEFAULT_OFFLINE_INDEX_PATH,
        "enable_offline_vector_search": DEFAULT_ENABLE_OFFLINE_VECTOR_SEARCH,
    }
