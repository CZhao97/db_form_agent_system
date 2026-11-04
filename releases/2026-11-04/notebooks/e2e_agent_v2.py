# -------------------- stdlib --------------------
from pathlib import Path
from functools import lru_cache
import re, logging, warnings, os, time, random, pickle, requests
import json
import csv
import copy
import operator
from typing import Any, Dict, List, Optional, TypedDict, Annotated

# -------------------- langchain / langgraph --------------------
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.constants import Send
# Suppress LangGraph deprecation warning for create_react_agent
import warnings
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from langgraph.prebuilt import create_react_agent
from langgraph.errors import GraphRecursionError
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_core.tracers.langchain import wait_for_all_tracers
from langchain_openai import ChatOpenAI
from pydantic import Field, SecretStr
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
# from concurrent.futures import ThreadPoolExecutor, as_completed # Disabled
from langchain_core.utils.utils import secret_from_env
from dotenv import load_dotenv

# -------------------- local tools --------------------
# --- GLOBAL GPU DISTRIBUTION (Helper) ---
import torch
import multiprocessing as mp
import os

def setup_gpu_worker(gpu_id: int = None):
    """
    Explicitly set the GPU for this worker process.
    If gpu_id is None, it falls back to PID % n_gpus mechanism.
    """
    try:
        if gpu_id is not None:
             # Attempt to mask other GPUs
             os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
        
        if not torch.cuda.is_available():
            print(f"[Multi-GPU] CUDA not available.")
            return

        n_gpus = torch.cuda.device_count()
        current_pid = os.getpid()
        
        if n_gpus >= 1:
            if gpu_id is None:
                # Fallback / Auto-assign
                gpu_id = current_pid % n_gpus
                torch.cuda.set_device(gpu_id)
                print(f"[Multi-GPU] Worker {current_pid} auto-assigned to Physical GPU {gpu_id}")
            else:
                # We have a target GPU ID.
                # Check if masking worked.
                if n_gpus == 1:
                    # Masking worked! We are on a virtual 1-GPU system.
                    torch.cuda.set_device(0)
                    print(f"[Multi-GPU] Worker {current_pid} masked successfully. Using Virtual GPU 0 (Physical {gpu_id})")
                else:
                    # Masking failed (likely initialized early). Use explicit ID.
                    # Ensure the ID is valid
                    if gpu_id < n_gpus:
                        torch.cuda.set_device(gpu_id)
                        print(f"[Multi-GPU] Worker {current_pid} masking failed (saw {n_gpus} GPUs). Explicitly set to Physical GPU {gpu_id}")
                    else:
                        print(f"[Multi-GPU] Worker {current_pid} ERROR: Target GPU {gpu_id} >= Available {n_gpus}. Fallback to 0.")
                        torch.cuda.set_device(0)

    except Exception as e:
        print(f"[Multi-GPU] Failed to set device: {e}")

# DO NOT RUN AUTOMATICALLY AT IMPORT TIME
# The calling script must call setup_gpu_worker() explicitly inside the process.
# ---------------------------------------------------------------

import sys
import os
# Add the code directory to the path relative to this script
sys.path.append(os.path.join(os.path.dirname(__file__), '../code'))

# Flair versions pinned for this project expect the legacy Transformers name
# LayoutLMv2FeatureExtractor. Transformers 5 exposes the same image preprocessing
# class as LayoutLMv2ImageProcessor, so provide a local compatibility alias before
# importing Flair-dependent tools.
try:
    import transformers
    from transformers.models.layoutlmv2.image_processing_layoutlmv2 import LayoutLMv2ImageProcessor
    transformers.LayoutLMv2FeatureExtractor = LayoutLMv2ImageProcessor
except Exception as exc:
    print(f"[compat] Could not install LayoutLMv2FeatureExtractor alias: {exc}")

from searching_tool import FullTextJournalSearchTool
from offline_retrieval_config import default_offline_search_kwargs
from compound_tool import CompoundDatabaseTool
from fulltext_vector_tools import FullTextIndexTool, FullTextQueryTool
from ner_results_viewer import load_ner_results, ner_results_to_dataframe
from inspection_tool import InspectSearchResultsTool
from chemical_ner_tool import ChemicalNerTool
from candidate_ranking import rank_candidates_for_topic
from prompt_payloads import (
    build_critique_auto_approval_payload,
    build_critique_request_payload,
    build_default_search_budget,
    build_definition_confirmation_payload,
    build_query_generator_input,
    build_refinement_request,
    build_researcher_followup_payload,
    build_researcher_fallback_payload,
    build_upper_stream_request,
    build_verification_task_payload,
    extract_criteria_key_points,
    extract_fixed_criteria_key_points,
    extract_rubric_items,
    extract_next_queries_from_critique,
    extract_criteria_text,
)

# -------------------- logging & environment --------------------
logging.basicConfig(level=logging.WARNING, format='%(levelname)s | %(name)s | %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)
log = logging.getLogger("end_to_end_workflow")
load_dotenv()

os.environ["LANGCHAIN_TRACING_V2"] = os.getenv("LANGCHAIN_TRACING_V2", "true")
os.environ["LANGCHAIN_CALLBACKS_BACKGROUND"] = "false"

# -------------------- constants --------------------
MAX_ITERATIONS_UPPER = int(os.environ.get("MAX_ITERATIONS_UPPER", "50"))
MAX_ITERATIONS_DOWN = int(os.environ.get("MAX_ITERATIONS_DOWN", "60"))
MAX_ITERATIONS_E2E = int(os.environ.get("MAX_ITERATIONS_E2E", "100"))
PRE_CRITIQUE_RESEARCHER_ROUNDS = int(os.environ.get("PRE_CRITIQUE_RESEARCHER_ROUNDS", "3"))
NO_PROGRESS_EXHAUSTION_THRESHOLD = int(os.environ.get("NO_PROGRESS_EXHAUSTION_THRESHOLD", "2"))
BASE_RESULTS_DIR = "/home/chen/GNPS_SIM/agent/searching_results"
MIN_DATE = "1970"
MAX_DATE = "2025"
SEARCH_LIMIT = int(os.environ.get("SEARCH_LIMIT", "2000"))
TARGET_PAPERS = int(os.environ.get("TARGET_PAPERS", "2000"))
V2_QUERY_PLAN_LIMIT = int(os.environ.get("V2_QUERY_PLAN_LIMIT", "6"))
V2_SEARCH_MAX_RESULTS = int(os.environ.get("V2_SEARCH_MAX_RESULTS", "10"))
_FOLLOWUP_QUERY_HISTORY: dict[str, set[str]] = {}

def _vprint(*args, **kwargs):
    if os.getenv("NODE_LOGS", "1") in ("1", "true", "TRUE", "yes", "YES"):
        print(*args, **kwargs)

class ChatOpenRouter(ChatOpenAI):
    openai_api_key: Optional[SecretStr] = Field(
        alias="api_key", default_factory=secret_from_env("OPENROUTER_API_KEY", default=None)
    )
    @property
    def lc_secrets(self) -> dict[str, str]:
        return {"openai_api_key": "OPENROUTER_API_KEY"}

    def __init__(self,
                 openai_api_key: Optional[str] = None,
                 **kwargs):
        openai_api_key = openai_api_key or os.environ.get("OPENROUTER_API_KEY")
        super().__init__(base_url="https://openrouter.ai/api/v1", openai_api_key=openai_api_key, **kwargs)

# %% [markdown]
# ## 2. Upper-Stream Agent Definition
# 
# This section defines the first agent, which performs literature harvesting and chemical extraction.

# %%
# --- STATE --- #
class UpperAgentState(TypedDict):
    messages: List[HumanMessage | AIMessage]
    original_query: str
    search_session_dir: str
    iteration_count: int
    last_output: str | None

# --- PROMPT --- #
PROMPTS_DIR = Path("/home/chen/GNPS_SIM/agent/db_form_agent_system/prompts")
UPPER_STREAM_PROMPT_PATH = PROMPTS_DIR / "upper_stream_agent.md"
upper_prompt_text = UPPER_STREAM_PROMPT_PATH.read_text(encoding="utf-8")
upper_prompt_text = upper_prompt_text.replace("__SEARCH_LIMIT__", str(SEARCH_LIMIT))
upper_prompt_text = upper_prompt_text.replace("__TARGET_PAPERS__", str(TARGET_PAPERS))
UPPER_STREAM_AGENT_PROMPT = SystemMessage(content=upper_prompt_text)


def _model_name_from_env(env_key: str, default: str) -> str:
    value = os.environ.get(env_key, "").strip()
    return value or default

# --- TOOLS & MODEL --- #
upper_stream_model = ChatOpenRouter(
    model_name=_model_name_from_env("UPPER_STREAM_MODEL_NAME", "google/gemini-2.5-flash"),
    temperature=0.0,
)
upper_stream_tools = [FullTextJournalSearchTool(
        results_base_dir=BASE_RESULTS_DIR,
        include_pubmed=True,
        include_preprints=False,
        include_s2=True,
        include_arxiv=False,
        include_medrxiv=False,
        include_eupmc=True,
        use_pubmed_free_fulltext_bias=True,
        max_parallel_downloads=6,
        max_parallel_docling=6,
        min_date=MIN_DATE,  # Date range filter
        max_date=MAX_DATE,  # Date range filter
        **default_offline_search_kwargs()
    ), 
    InspectSearchResultsTool(),
    ChemicalNerTool()]

# --- AGENT --- #
# Add a checkpointer to the agent
upper_stream_memory = MemorySaver()
upper_stream_agent_executor = create_react_agent(
    upper_stream_model, 
    upper_stream_tools, 
    prompt=UPPER_STREAM_AGENT_PROMPT,
    checkpointer=upper_stream_memory,
)

def upper_stream_agent_node(state: UpperAgentState, config: RunnableConfig):
    _vprint("\n----- Upper-Stream Agent Node Invoked -----")
    session_dir = state.get("search_session_dir")
    
    # Ensure thread_id is passed to the agent's tool config
    tool_config = config.copy()
    tool_config["configurable"] = tool_config.get("configurable", {}).copy()
    tool_config["configurable"]["search_session_dir"] = session_dir
    
    FullTextJournalSearchTool.set_session_dir(session_dir)
    
    result = upper_stream_agent_executor.invoke({"messages": state["messages"]}, config=tool_config)
    ai_content = result['messages'][-1].content
    
    return {
        "messages": state["messages"] + [AIMessage(content=ai_content)],
        "iteration_count": state.get("iteration_count", 0) + 1,
        "last_output": ai_content,
    }

def upper_should_continue(state: UpperAgentState):
    if state["iteration_count"] >= MAX_ITERATIONS_UPPER:
        return END
    last_output = state.get("last_output", "")
    if "chemical_ner_results.json" in last_output:
        _vprint("\n----- Stopping Upper-Stream: NER deliverable produced -----")
        return END
    return "agent"

# --- WORKFLOW --- #
# upper_workflow definition removed as it is integrated into full_workflow

print("✓ Upper-Stream Agent Defined")

# %%
def extract_final_output(messages):
    """Extract structured output from final agent message."""
    if not messages:
        return {}
    
    last_content = messages[-1].content if messages else ""
    
    try:
        return json.loads(last_content)
    except json.JSONDecodeError:
        # Try to extract JSON from text
        match = re.search(r'\{[\s\S]*\}', last_content)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    
    return {"raw_output": last_content}


def _extract_candidate_name_from_mention(mention: str) -> str:
    if " (Context:" in mention:
        return mention.split(" (Context:")[0].strip()
    return mention.strip()


def _normalize_surface_form(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _normalize_surface_key(value: Any) -> str:
    text = _normalize_surface_form(value).casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def _same_surface_family(left: str, right: str) -> bool:
    left_key = _normalize_surface_key(left)
    right_key = _normalize_surface_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    if len(left_key) >= 6 and left_key in right_key:
        return True
    if len(right_key) >= 6 and right_key in left_key:
        return True
    return False


@lru_cache(maxsize=4096)
def _cached_compound_lookup(term: str) -> dict[str, Any] | None:
    text = _normalize_surface_form(term)
    if not text:
        return None
    try:
        payload = json.loads(CompoundDatabaseTool()._run(compound_name=text))
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("error"):
        return None
    return payload


def _compound_grounding_score(term: str) -> tuple[float, dict[str, Any] | None]:
    payload = _cached_compound_lookup(term)
    if not payload:
        return 0.0, None

    primary = payload.get("primary") or {}
    synonyms = payload.get("synonyms") or []
    candidates = payload.get("candidates") or []
    norm_term = _normalize_surface_form(term)
    primary_name = _normalize_surface_form(primary.get("name"))

    if primary_name and _normalize_surface_key(primary_name) == _normalize_surface_key(norm_term):
        return 1.0, payload
    if primary_name and _same_surface_family(norm_term, primary_name):
        return 0.9, payload

    for synonym in synonyms:
        syn_text = _normalize_surface_form(synonym)
        if syn_text and _normalize_surface_key(syn_text) == _normalize_surface_key(norm_term):
            return 0.85, payload
        if syn_text and _same_surface_family(norm_term, syn_text):
            return 0.75, payload

    for item in candidates:
        if not isinstance(item, dict):
            continue
        candidate_name = _normalize_surface_form(item.get("name"))
        if candidate_name and _normalize_surface_key(candidate_name) == _normalize_surface_key(norm_term):
            return 0.8, payload
        if candidate_name and _same_surface_family(norm_term, candidate_name):
            return 0.7, payload

    return 0.4, payload


def _append_unique_candidate_name(values: list[str], seen: set[str], candidate: str | None) -> None:
    text = _normalize_surface_form(candidate)
    if not text:
        return
    key = text.casefold()
    if key in seen:
        return
    seen.add(key)
    values.append(text)


def _choose_representative_name(
    mention_name_counts: dict[str, int],
    mention_name_forms: dict[str, str],
    fallback_names: list[str],
) -> tuple[str | None, list[str], list[dict[str, Any]]]:
    candidate_pool: list[str] = []
    seen_pool: set[str] = set()
    for text in mention_name_forms.values():
        _append_unique_candidate_name(candidate_pool, seen_pool, text)
    for text in fallback_names:
        _append_unique_candidate_name(candidate_pool, seen_pool, text)

    grounded_candidates: list[dict[str, Any]] = []
    for text in candidate_pool:
        score, payload = _compound_grounding_score(text)
        grounded_candidates.append(
            {
                "text": text,
                "score": round(score, 4),
                "mention_count": int(mention_name_counts.get(text.casefold(), 0)),
                "primary_name": _normalize_surface_form((payload or {}).get("primary", {}).get("name")),
            }
        )

    if grounded_candidates:
        grounded_candidates.sort(
            key=lambda item: (
                float(item["score"]),
                int(item["mention_count"]),
                len(item["text"]),
            ),
            reverse=True,
        )
        canonical_name = grounded_candidates[0]["text"]
        synonyms: list[str] = []
        seen: set[str] = {canonical_name.casefold()}
        for item in grounded_candidates[1:]:
            text = item["text"]
            if text.casefold() in seen:
                continue
            synonyms.append(text)
            seen.add(text.casefold())
        return canonical_name, synonyms, grounded_candidates

    if mention_name_counts:
        ordered_mention_names = sorted(
            mention_name_forms.items(),
            key=lambda item: (
                mention_name_counts.get(item[0], 0),
                len(item[1]),
            ),
            reverse=True,
        )
        canonical_name = ordered_mention_names[0][1]
        synonyms: list[str] = []
        seen: set[str] = {canonical_name.casefold()}
        for _, text in ordered_mention_names[1:]:
            if text.casefold() in seen:
                continue
            synonyms.append(text)
            seen.add(text.casefold())
        for name in fallback_names:
            key = name.casefold()
            if key in seen:
                continue
            synonyms.append(name)
            seen.add(key)
        return canonical_name, synonyms, []

    if not fallback_names:
        return None, [], []

    canonical_name = fallback_names[0]
    synonyms = [name for name in fallback_names[1:] if name.casefold() != canonical_name.casefold()]
    return canonical_name, synonyms, []


def load_candidates_from_ner_results(ner_results_file: str | Path) -> list[dict[str, Any]]:
    path = Path(ner_results_file)
    ner_data = json.loads(path.read_text(encoding="utf-8"))
    merged = ner_data.get("merged_output") or {}

    if not merged and ner_data.get("per_file_results"):
        aggregated: dict[str, dict[str, Any]] = {}
        for file_entry in ner_data["per_file_results"]:
            if not isinstance(file_entry, dict):
                continue
            entities = file_entry.get("entities") or file_entry.get("output") or {}
            if not isinstance(entities, dict):
                continue
            for kb_id, details in entities.items():
                if not isinstance(details, dict):
                    continue
                if kb_id not in aggregated:
                    aggregated[kb_id] = {"synonyms": [], "mentions": []}
                aggregated[kb_id]["synonyms"].extend(details.get("synonyms") or [])
                aggregated[kb_id]["mentions"].extend(details.get("mentions") or [])
        merged = aggregated

    candidates: list[dict[str, Any]] = []
    for kb_id, details in merged.items():
        if not isinstance(details, dict):
            continue
        ordered_names: list[str] = []
        seen_names: set[str] = set()
        mention_name_counts: dict[str, int] = {}
        mention_name_forms: dict[str, str] = {}

        for syn in details.get("synonyms", []) or []:
            if isinstance(syn, str):
                _append_unique_candidate_name(ordered_names, seen_names, syn)

        mentions = details.get("mentions", []) or []
        flat_mentions: list[str] = []
        for mention in mentions:
            if isinstance(mention, dict):
                for text in mention.get("text", []) or []:
                    if isinstance(text, str) and text.strip():
                        flat_mentions.append(text.strip())
            elif isinstance(mention, str) and mention.strip():
                flat_mentions.append(mention.strip())

        for mention in flat_mentions:
            extracted_name = _extract_candidate_name_from_mention(mention)
            text = extracted_name.strip()
            if not text:
                continue
            key = text.casefold()
            mention_name_counts[key] = mention_name_counts.get(key, 0) + 1
            mention_name_forms.setdefault(key, text)

        canonical_name, synonyms, grounded_candidates = _choose_representative_name(
            mention_name_counts,
            mention_name_forms,
            ordered_names,
        )

        if not canonical_name:
            continue

        candidates.append(
            {
                "entity_id": str(kb_id),
                "candidate_name": canonical_name,
                "canonical_name": canonical_name,
                "entity_synonyms": synonyms,
                "mention_count": len(flat_mentions),
                "mention_samples": flat_mentions,
                "mention_contexts": _mention_context_items(flat_mentions),
                "mention_name_counts": {
                    mention_name_forms[key]: count
                    for key, count in mention_name_counts.items()
                },
                "grounded_name_candidates": grounded_candidates[:10],
            }
        )

    return candidates


def _mention_context_items(mentions: list[str], limit: int = 5) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for mention in mentions:
        if not isinstance(mention, str):
            continue
        raw = mention.strip()
        if not raw:
            continue
        surface = _extract_candidate_name_from_mention(raw)
        context = raw
        if " (Context:" in raw:
            _, remainder = raw.split(" (Context:", 1)
            context = remainder.strip()
            if context.endswith(")"):
                context = context[:-1].strip()
        key = (surface.casefold(), context.casefold())
        if key in seen:
            continue
        seen.add(key)
        items.append({"mention": surface, "context": context})
        if len(items) >= limit:
            break
    return items


# %% [markdown]
# ## 3. Middle Component: Query Generation Node
# 
# This function loads the NER results and generates targeted questions for the down-stream agent. It acts as a node in the workflow without being a full "agent".

# %%

# --- MIDDLE NODE: QUERY GENERATOR --- #
def query_generation_node(state: UpperAgentState) -> dict:
    """
    Takes the output of the upper-stream agent, generates downstream queries,
    and prepares the initial states for the downstream batch process.
    """
    _vprint("\n----- Middle Component (Node): Generating Down-Stream Queries -----")
    
    ner_results_file = str(state.get("candidate_source_file") or "").strip()
    if not ner_results_file:
        output_data = extract_final_output(state['messages'])
        ner_results_file = str(output_data.get("results_file") or "").strip()

    if not ner_results_file or not Path(ner_results_file).exists():
        log.error(f"NER results file not found or invalid: {ner_results_file}")
        return {
            "downstream_states": [],
            "downstream_configs": [],
            "remaining_candidate_count": 0,
        }
        
    _vprint(f"✅ Upper-stream complete. NER results at: {ner_results_file}")

    original_query = state['original_query']
    refined_definition = state.get("refined_definition")
    verification_query_template = state.get("verification_query_template")
    session_dir = Path(state['search_session_dir'])
    if session_dir.name == "literature_searching":
        base_session_dir = session_dir.parent
    else:
        base_session_dir = session_dir
    batch_round = len(state.get("consumed_candidate_ids", []))
    batch_output_dir = base_session_dir / "middle_batches" / f"round_{batch_round:06d}"
    batch_output_dir.mkdir(parents=True, exist_ok=True)

    all_candidates = load_candidates_from_ner_results(ner_results_file)
    consumed = {str(value).strip() for value in state.get("consumed_candidate_ids", []) if str(value).strip()}
    remaining_candidates = [
        candidate for candidate in all_candidates
        if str(candidate.get("entity_id") or "").strip() not in consumed
    ]
    batch_size = max(int(state.get("middle_batch_size") or 100), 0)
    selected_candidates = rank_candidates_for_topic(
        remaining_candidates,
        original_query=original_query,
        refined_definition=refined_definition,
        verification_query_template=verification_query_template,
        top_k=batch_size,
    )
    selected_entity_ids = [
        str(candidate.get("entity_id") or "").strip()
        for candidate in selected_candidates
        if str(candidate.get("entity_id") or "").strip()
    ]
    selected_batch_path = batch_output_dir / "selected_batch.jsonl"
    selected_batch_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected_candidates),
        encoding="utf-8",
    )
    remaining_candidate_count = max(len(remaining_candidates) - len(selected_candidates), 0)

    entity_data = []
    for candidate in selected_candidates:
        if not isinstance(candidate, dict):
            continue
        names = []
        candidate_name = str(candidate.get("candidate_name") or "").strip()
        if candidate_name:
            names.append(candidate_name)
        names.extend(candidate.get("entity_synonyms") or [])
        normalized_names = _normalize_entity_synonyms(names, primary_name=None)
        entity_id = str(candidate.get("entity_id") or "").strip()
        if not entity_id or not normalized_names:
            continue
        entity_data.append({
            "id": entity_id,
            "names": normalized_names,
            "mention_contexts": _mention_context_items(candidate.get("mention_samples") or []),
        })

    if not entity_data:
        log.warning("No valid candidates available for middle-stage filtering in this batch.")
        return {
            "downstream_states": [],
            "downstream_configs": [],
            "candidate_source_file": ner_results_file,
            "selected_batch_file": str(selected_batch_path),
            "remaining_candidate_count": remaining_candidate_count,
            "consumed_candidate_ids": list(state.get("consumed_candidate_ids", [])) + selected_entity_ids,
        }

    _vprint("Selected candidate examples:")
    for entity in entity_data[:3]:
        _vprint(f"  - ID: {entity['id']}, Names: {entity['names']}")

    input_data = build_query_generator_input(
        original_query=original_query,
        entity_data=entity_data,
        refined_definition=refined_definition,
        verification_query_template=verification_query_template,
    )
    input_content = json.dumps(input_data)
    entity_names_by_id: dict[str, list[str]] = {
        str(entity.get("id")): _normalize_entity_synonyms(entity.get("names"), primary_name=None)
        for entity in entity_data
        if isinstance(entity, dict) and entity.get("id")
    }
    
    query_generator_model = ChatOpenRouter(model_name="google/gemini-2.5-flash", temperature=0.0)
    QUERY_GENERATOR_PROMPT_PATH = PROMPTS_DIR / "query_generator_agent.md"
    QUERY_GENERATOR_PROMPT = SystemMessage(content=QUERY_GENERATOR_PROMPT_PATH.read_text(encoding="utf-8"))
    
    message = HumanMessage(content=input_content)
    response = query_generator_model.invoke([QUERY_GENERATOR_PROMPT, message])
    
    try:
        match = re.search(r'\{[\s\S]*\}', response.content)
        if not match:
            raise json.JSONDecodeError("No JSON object found in LLM response for query generation.", response.content, 0)
        output_json = json.loads(match.group(0))
        score_threshold = float(state.get("score_threshold") or 0.7)

        def _has_passing_score(item: Any) -> bool:
            if not isinstance(item, dict):
                return False
            try:
                return float(item.get("relevance_score")) >= score_threshold
            except (TypeError, ValueError):
                return False

        def _materialize_verification_query(entity_name: str) -> str:
            template = str(verification_query_template or "").strip()
            if template and "{{CANDIDATE}}" in template:
                return template.replace("{{CANDIDATE}}", entity_name)
            return original_query

        if "accepted_candidates" in output_json:
            accepted_candidates = output_json["accepted_candidates"] or []
            accepted_candidates = sorted(
                accepted_candidates,
                key=lambda candidate: (
                    0 if isinstance(candidate, dict) and candidate.get("relevance_score") is not None else 1,
                    -float(candidate.get("relevance_score"))
                    if isinstance(candidate, dict) and candidate.get("relevance_score") is not None
                    else 0.0,
                ),
            )
            accepted_candidates = [candidate for candidate in accepted_candidates if _has_passing_score(candidate)]
            downstream_queries = []
            for candidate in accepted_candidates:
                if not isinstance(candidate, dict):
                    continue
                entity_name = str(candidate.get("entity_name") or "").strip()
                entity_id = str(candidate.get("entity_id") or "").strip()
                relevance_score = candidate.get("relevance_score")
                if not entity_name:
                    continue
                entity_synonyms = _normalize_entity_synonyms(candidate.get("entity_synonyms"), primary_name=entity_name)
                if not entity_synonyms and entity_id:
                    entity_synonyms = _normalize_entity_synonyms(entity_names_by_id.get(entity_id), primary_name=entity_name)
                downstream_queries.append(
                    build_verification_task_payload(
                        entity_name=entity_name,
                        original_query=_materialize_verification_query(entity_name),
                        refined_definition=refined_definition,
                        entity_id=entity_id or None,
                        entity_synonyms=entity_synonyms,
                        relevance_score=relevance_score,
                    )
                )
        elif "verification_tasks" in output_json:
            raw_tasks = output_json["verification_tasks"]
            raw_tasks = sorted(
                raw_tasks,
                key=lambda task: (
                    0 if isinstance(task, dict) and task.get("relevance_score") is not None else 1,
                    -float(task.get("relevance_score"))
                    if isinstance(task, dict) and task.get("relevance_score") is not None
                    else 0.0,
                ),
            )
            raw_tasks = [task for task in raw_tasks if _has_passing_score(task)]
            downstream_queries = []
            for task in raw_tasks:
                if not isinstance(task, dict):
                    continue
                entity_name = str(task.get("entity_name") or "").strip()
                entity_id = str(task.get("entity_id") or "").strip()
                relevance_score = task.get("relevance_score")
                entity_synonyms = _normalize_entity_synonyms(task.get("entity_synonyms"), primary_name=entity_name)
                if not entity_synonyms:
                    entity_synonyms = _normalize_entity_synonyms(entity_names_by_id.get(entity_id), primary_name=entity_name)
                if not entity_name:
                    continue
                downstream_queries.append(
                    build_verification_task_payload(
                        entity_name=entity_name,
                        original_query=_materialize_verification_query(entity_name),
                        refined_definition=refined_definition,
                        entity_id=entity_id or None,
                        entity_synonyms=entity_synonyms,
                        relevance_score=relevance_score,
                    )
                )
        elif "queries" in output_json:
            raw_queries = output_json["queries"]
            raw_queries = sorted(
                raw_queries,
                key=lambda q: (
                    0 if isinstance(q, dict) and q.get("relevance_score") is not None else 1,
                    -float(q.get("relevance_score"))
                    if isinstance(q, dict) and q.get("relevance_score") is not None
                    else 0.0,
                ),
            )
            raw_queries = [q for q in raw_queries if _has_passing_score(q)]
            downstream_queries = []
            for q in raw_queries:
                if isinstance(q, dict):
                    q.setdefault("task", "verify_candidate_entity")
                    q.setdefault("original_query", original_query)
                    if refined_definition and not q.get("refined_definition"):
                        q["refined_definition"] = refined_definition
                    entity_name = str(q.get("entity_name") or "").strip()
                    entity_synonyms = _normalize_entity_synonyms(q.get("entity_synonyms"), primary_name=entity_name)
                    if not entity_synonyms:
                        entity_id = str(q.get("entity_id") or "").strip()
                        entity_synonyms = _normalize_entity_synonyms(entity_names_by_id.get(entity_id), primary_name=entity_name)
                    if entity_synonyms:
                        q["entity_synonyms"] = entity_synonyms
                    if "relevance_score" in q:
                        try:
                            q["relevance_score"] = float(q["relevance_score"])
                        except (TypeError, ValueError):
                            q.pop("relevance_score", None)
                    downstream_queries.append(json.dumps(q))
                elif isinstance(q, str) and q.strip():
                    downstream_queries.append(q.strip())
        else:
            # Fallback: try candidates if queries missing (backward compat)
            candidates = output_json.get("candidates", [])
            downstream_queries = []
            for chemical in candidates:
                downstream_queries.append(
                    build_verification_task_payload(
                        entity_name=str(chemical),
                        original_query=original_query,
                        refined_definition=refined_definition,
                        entity_synonyms=[],
                    )
                )
            
    except (json.JSONDecodeError, AttributeError) as e:
        log.error(f"Failed to parse query generator LLM output: {e}")
        log.error(f"RAW LLM OUTPUT:\n{response.content}")
        return {
            "downstream_states": [],
            "downstream_configs": [],
            "candidate_source_file": ner_results_file,
            "selected_batch_file": str(selected_batch_path),
            "remaining_candidate_count": remaining_candidate_count,
            "consumed_candidate_ids": list(state.get("consumed_candidate_ids", [])) + selected_entity_ids,
        }

    if not downstream_queries:
        log.warning("Middle component generated no downstream queries for this batch.")
        return {
            "downstream_states": [],
            "downstream_configs": [],
            "candidate_source_file": ner_results_file,
            "selected_batch_file": str(selected_batch_path),
            "remaining_candidate_count": remaining_candidate_count,
            "consumed_candidate_ids": list(state.get("consumed_candidate_ids", [])) + selected_entity_ids,
        }

    _vprint(f"\n🔍 Generated {len(downstream_queries)} queries for downstream agents")

    all_init_states = []
    all_configs = []
    candidate_pool = list(state.get("candidate_pool", []))
    
    for i, query in enumerate(downstream_queries):
        init_state = _build_downstream_init_state(query, base_session_dir, i)
        all_init_states.append(init_state)
        all_configs.append({'recursion_limit': MAX_ITERATIONS_DOWN})
        candidate_name = _extract_target_entity_name(query)
        if candidate_name:
            candidate_pool.append(candidate_name)

    return {
        "downstream_states": all_init_states,
        "downstream_configs": all_configs,
        "candidate_pool": candidate_pool,
        "processed_report_count": len(state.get("final_reports", [])),
        "candidate_source_file": ner_results_file,
        "selected_batch_file": str(selected_batch_path),
        "remaining_candidate_count": remaining_candidate_count,
        "consumed_candidate_ids": list(state.get("consumed_candidate_ids", [])) + selected_entity_ids,
    }

print("✓ Middle Component (Query Generation Node) Defined")


# %% [markdown]
# ## 4. Down-Stream Agent Definition
# 
# This section defines the second agent, which takes specific chemical queries and verifies them.

# %%
# --- STATE --- #
class StateHistory(TypedDict):
    claim: str
    supporting_sources: List[str]
    tool_name: str | None
    stop_reason: str | None

class DownAgentState(TypedDict):
    # Optional caller-frozen packet, never populated from inferred solved flags.
    release_review_packet: dict | None
    messages: List[HumanMessage | AIMessage]
    original_query: str
    search_session_dir: str
    criteria_text: str | None
    prior_critique_json: str | None
    stop_history: List[StateHistory]
    consecutive_no_new_evidence: int
    consecutive_tool_unavailable: int
    last_researcher_json: str | None
    last_critique_json: str | None
    first_researcher_json: str | None
    claim_history: List[str]
    researcher_round_count: int
    critique_round_count: int


def _build_downstream_init_state(query: str, session_dir: Path, index: int) -> dict:
    payload = _parse_original_task_payload(query)
    safe_label = _extract_target_entity_name(query) or query
    if isinstance(payload, dict) and payload:
        entity_name = payload.get("entity_name") if isinstance(payload.get("entity_name"), str) else safe_label
        payload["entity_synonyms"] = _normalize_entity_synonyms(payload.get("entity_synonyms"), primary_name=entity_name)
        query = json.dumps(payload, ensure_ascii=True, indent=2)
    down_stream_session_dir = session_dir / f"downstream_{index}_{re.sub('[^A-Za-z0-9]+', '_', safe_label)[:50]}"
    down_stream_session_dir.mkdir(parents=True, exist_ok=True)
    return {
        'messages': [HumanMessage(content=query)],
        'original_query': query,
        'search_session_dir': str(down_stream_session_dir),
        'criteria_text': None,
        'prior_critique_json': None,
        'stop_history': [],
        'last_researcher_json': None,
        'last_critique_json': None,
        'first_researcher_json': None,
        'claim_history': [],
        'consecutive_no_new_evidence': 0,
        'consecutive_tool_unavailable': 0,
        'researcher_round_count': 0,
        'critique_round_count': 0,
    }


def _collect_discovered_compounds(report: dict) -> list[dict]:
    discovered: list[dict] = []
    raw_candidates = report.get("ambiguity_candidates")
    candidate_names: list[str] = []
    if isinstance(raw_candidates, list):
        for value in raw_candidates:
            if isinstance(value, str) and value.strip():
                candidate_names.extend(_split_compound_candidate_names(value) or [value.strip()])

    if not candidate_names:
        candidate_name = report.get("ambiguity_candidate")
        if isinstance(candidate_name, str) and candidate_name.strip():
            candidate_names = _split_compound_candidate_names(candidate_name) or [candidate_name.strip()]

    seen: set[str] = set()
    for candidate_name in candidate_names:
        normalized_candidate = _normalize_entity_name(candidate_name)
        if not normalized_candidate or normalized_candidate in seen:
            continue
        seen.add(normalized_candidate)
        candidate_synonyms = _normalize_entity_synonyms(list(_lookup_candidate_synonyms(candidate_name)), primary_name=candidate_name)
        discovered.append({
            "name": candidate_name.strip(),
            "synonyms": candidate_synonyms,
            "source": "verification_followup",
            "reason": report.get("ambiguity_status") or "related_compound",
            "researcher_claim": "",
            "final_adjudicated_claim": "",
            "accepted": None,
        })
    return discovered

# --- PROMPTS --- #
LITERATURE_PROMPT_PATH = PROMPTS_DIR / "literature_agent.md"
CRITIQUE_PROMPT_PATH = PROMPTS_DIR / "critique_agent.md"
LITERATURE_AGENT_PROMPT = SystemMessage(content=LITERATURE_PROMPT_PATH.read_text(encoding="utf-8"))
CRITIQUE_AGENT_PROMPT = SystemMessage(content=CRITIQUE_PROMPT_PATH.read_text(encoding="utf-8"))

# --- MODELS & TOOLS --- #
research_model = ChatOpenRouter(
    model_name=_model_name_from_env("RESEARCH_MODEL_NAME", "google/gemini-2.5-flash"),
    temperature=0.0,
)
evaluator_model = ChatOpenRouter(
    model_name=_model_name_from_env("CRITIQUE_MODEL_NAME", "openai/gpt-4o-mini"),
    temperature=0.0,
)
down_stream_tools = [
    CompoundDatabaseTool(),
    FullTextJournalSearchTool(
        results_base_dir=BASE_RESULTS_DIR,
        include_pubmed=os.environ.get("INCLUDE_ONLINE_SEARCH", "True") == "True",
        include_preprints=False,
        include_s2=os.environ.get("INCLUDE_ONLINE_SEARCH", "True") == "True",
        include_arxiv=os.environ.get("INCLUDE_ONLINE_SEARCH", "True") == "True",
        include_medrxiv=os.environ.get("INCLUDE_ONLINE_SEARCH", "True") == "True",
        include_eupmc=os.environ.get("INCLUDE_ONLINE_SEARCH", "True") == "True",
        use_pubmed_free_fulltext_bias=True,
        max_parallel_downloads=6,
        max_parallel_docling=6,
        min_date=MIN_DATE,  # Date range filter
        max_date=MAX_DATE,  # Date range filter
        # Enable offline DB for deduplication and local retrieval in downstream too
        include_offline_search=os.environ.get("INCLUDE_OFFLINE_SEARCH", "True") == "True",
        **default_offline_search_kwargs(),
        enable_ner_indexing=False, # Disable costly NER write-back for downstream verification
        enable_offline_keyword=True # Enabled per user request; instrumented for performance profiling
    ),
    FullTextIndexTool(results_base_dir=BASE_RESULTS_DIR),
    FullTextQueryTool(results_base_dir=BASE_RESULTS_DIR)
]

# --- AGENT EXECUTORS --- #
downstream_memory = MemorySaver()
researcher_agent_executor = create_react_agent(
    research_model, 
    down_stream_tools, 
    prompt=LITERATURE_AGENT_PROMPT,
    checkpointer=downstream_memory
)
critique_agent_executor = create_react_agent(
    evaluator_model, 
    down_stream_tools, 
    prompt=CRITIQUE_AGENT_PROMPT,
    checkpointer=downstream_memory
)

# -------------------- helpers --------------------
def _researcher_payload_score(obj: dict | None) -> tuple[int, int, int]:
    if not isinstance(obj, dict):
        return (0, 0, 0)
    evidence_count = 0
    evidence = obj.get("evidence")
    if isinstance(evidence, list):
        evidence_count += len([item for item in evidence if isinstance(item, dict)])
    supporting_sources = obj.get("supporting_sources")
    supporting_count = len(supporting_sources) if isinstance(supporting_sources, list) else 0
    structure_score = 0
    if isinstance(obj.get("synthesis"), dict):
        structure_score += 1
    if isinstance(obj.get("verdict_statement"), dict):
        structure_score += 1
    if isinstance(obj.get("traceability"), dict):
        structure_score += 1
    return (evidence_count, supporting_count, structure_score)


def _last_researcher_json(messages):
    # Select by chronology, not evidence count or the desirability of the label.
    for msg in reversed(messages or []):
        if getattr(msg, "type", None) != "ai":
            continue
        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            continue
        raw = _parse_json_object(content)
        if not isinstance(raw, dict) or "critique" in raw:
            continue
        if not any(key in raw for key in ("synthesis", "verdict_statement", "claim")):
            continue
        parsed = _coerce_researcher_payload(content)
        if isinstance(parsed, dict):
            return json.dumps(parsed, ensure_ascii=False)
    return ""

def determine_final_claim(messages):
    blob = _last_researcher_json(messages)
    if not blob:
        return "Insufficient Direct Evidence"
    try:
        obj = json.loads(blob)
        if isinstance(obj, dict):
            # 1. Check for "verdict_statement" -> "claim" (New Schema)
            vs = obj.get("verdict_statement")
            if isinstance(vs, dict):
                claim = vs.get("claim")
                if claim: return claim.strip()
            
            # 2. Check for top-level "claim" (Fallback)
            claim = obj.get("claim")
            if claim: return claim.strip()

            # 3. Check for "synthesis" -> "claim" (Old Schema)
            syn = obj.get("synthesis")
            if isinstance(syn, dict):
                claim = syn.get("claim")
                if claim: return claim.strip()
    except Exception:
        pass

    # Regex fallback: Look for "claim": "VALUE"
    # We use a pattern that matches nested or flat structures
    # It looks for "claim" followed by colon and a string in quotes
    m = re.search(r'"claim"\s*:\s*"([^"]+)"', blob)
    if m:
        return m.group(1).strip()
    
    return "Insufficient Direct Evidence"


def _parse_original_task_payload(original_query: str) -> dict:
    parsed = _parse_json_object(original_query)
    if isinstance(parsed, dict):
        return parsed
    return {}


def _extract_target_entity_name(original_query: str) -> str:
    payload = _parse_original_task_payload(original_query)
    for key in ("entity_name", "compound", "chemical_name", "candidate"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    source_text = original_query
    nested_original = payload.get("original_query")
    if isinstance(nested_original, str) and nested_original.strip():
        source_text = nested_original.strip()

    for pattern in (
        r"Determine whether\s+['\"]?([^'\"\n]+?)['\"]?\s+is\b",
        r"Decide whether ['\"]([^'\"]+)['\"]",
        r"whether ['\"]([^'\"]+)['\"]",
        r"Target:\s*([^\n]+)",
    ):
        match = re.search(pattern, source_text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _normalize_entity_name(value: str | None) -> str:
    if not value or not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _normalize_entity_synonyms(values: Any, primary_name: str | None = None) -> list[str]:
    normalized_primary = _normalize_entity_name(primary_name)
    if not isinstance(values, list):
        return []
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        normalized_item = _normalize_entity_name(item)
        if not item or not normalized_item:
            continue
        if normalized_item == normalized_primary or normalized_item in seen:
            continue
        seen.add(normalized_item)
        deduped.append(item)
    return deduped


def _is_search_safe_synonym(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) < 4 or len(text) > 120:
        return False
    if any(ch in text for ch in "[]{};"):
        return False
    lowered = text.lower()
    blocked_fragments = (
        "usp", "jp18", "jan", "who-dd", "hsdb", "mart.", "mi]", "hpus",
        "first grade", "purum", "puriss", "%",
    )
    if any(fragment in lowered for fragment in blocked_fragments):
        return False
    upper = text.upper()
    blocked_prefixes = (
        "CAS-", "CAS ", "CHEBI:", "CHEBI", "CHEMBL", "DTXSID", "DTXCID",
        "NCGC", "SCHEMBL", "UNII-", "UNII", "HSDB", "CCRIS", "MFCD",
        "EINECS", "REFCHEM", "TOX21_", "NCI-", "NSC ", "NSC", "WLN:",
    )
    if upper.startswith(blocked_prefixes):
        return False
    if re.fullmatch(r"[A-Z0-9._:-]{4,20}", text):
        return False
    if re.fullmatch(r"s\d{4,}", lowered):
        return False
    if re.fullmatch(r"\d{2,7}-\d{2}-\d", text):
        return False
    return True


def _extract_target_entity_synonyms(original_query: str) -> list[str]:
    payload = _parse_original_task_payload(original_query)
    target_name = _extract_target_entity_name(original_query)
    for key in ("entity_synonyms", "synonyms", "aliases", "names"):
        value = payload.get(key)
        if isinstance(value, list):
            return _normalize_entity_synonyms(value, primary_name=target_name)
    return []


def _build_seed_source_brief(
    entity_name: str,
    entity_synonyms: list[str] | None,
    seed_sources: Any,
) -> list[dict[str, str]]:
    if not isinstance(seed_sources, list) or not entity_name:
        return []
    try:
        from pdfminer.high_level import extract_text as pdf_extract_text
    except Exception:
        pdf_extract_text = None

    def _extract_windows(text: str, term: str, window: int = 450) -> list[str]:
        if not text or not term:
            return []
        snippets: list[str] = []
        pattern = re.compile(re.escape(term), flags=re.IGNORECASE)
        for match in pattern.finditer(text):
            start = max(0, match.start() - window)
            end = min(len(text), match.end() + window)
            snippet = re.sub(r"\s+", " ", text[start:end]).strip()
            if snippet:
                snippets.append(snippet)
            if len(snippets) >= 2:
                break
        return snippets

    terms = [entity_name.strip()]
    if isinstance(entity_synonyms, list):
        for syn in entity_synonyms[:2]:
            if isinstance(syn, str) and syn.strip():
                terms.append(syn.strip())

    brief: list[dict[str, str]] = []
    seen_quotes: set[str] = set()
    for source in seed_sources[:3]:
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or "").strip()
        doi = str(source.get("doi") or "").strip()
        local_pdf_path = str(source.get("local_pdf_path") or "").strip()
        if not local_pdf_path or pdf_extract_text is None:
            continue
        try:
            text = (pdf_extract_text(local_pdf_path) or "").strip()
        except Exception:
            text = ""
        if not text:
            continue
        source_snippets: list[str] = []
        for term in terms:
            source_snippets.extend(_extract_windows(text, term))
            if len(source_snippets) >= 2:
                break
        for quote in source_snippets[:2]:
            key = quote.casefold()
            if key in seen_quotes:
                continue
            seen_quotes.add(key)
            brief.append({
                "title": title,
                "doi": doi,
                "quote": quote,
                "why_relevant": f"Seeded local source mentioning {entity_name} directly.",
            })
            if len(brief) >= 4:
                return brief
    return brief


@lru_cache(maxsize=256)
def _lookup_candidate_synonyms(candidate_name: str) -> tuple[str, ...]:
    if not isinstance(candidate_name, str) or not candidate_name.strip():
        return ()
    try:
        raw_result = CompoundDatabaseTool()._run(compound_name=candidate_name.strip())
        parsed = _parse_json_object(raw_result)
        if not isinstance(parsed, dict):
            return ()
        synonym_candidates: list[str] = []
        primary = parsed.get("primary")
        if isinstance(primary, dict):
            primary_name = primary.get("name")
            if isinstance(primary_name, str) and primary_name.strip():
                synonym_candidates.append(primary_name.strip())
        synonym_candidates.extend(_normalize_entity_synonyms(parsed.get("synonyms"), primary_name=candidate_name.strip()))
        normalized = _normalize_entity_synonyms(synonym_candidates, primary_name=candidate_name.strip())
        safe = [item for item in normalized if _is_search_safe_synonym(item)]
        return tuple(safe)
    except Exception:
        return ()


@lru_cache(maxsize=256)
def _lookup_compound_record(candidate_name: str) -> dict[str, Any]:
    if not isinstance(candidate_name, str) or not candidate_name.strip():
        return {}
    try:
        raw_result = CompoundDatabaseTool()._run(compound_name=candidate_name.strip())
        parsed = _parse_json_object(raw_result)
        if isinstance(parsed, dict) and parsed.get("error") is not True:
            return parsed
    except Exception:
        pass
    return {}


def _stringify_mass(value: Any) -> str:
    try:
        numeric = float(value)
    except Exception:
        return ""
    if numeric <= 0:
        return ""
    return f"{numeric:.3f}".rstrip("0").rstrip(".")


def _extract_compound_search_fields(compound_record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(compound_record, dict):
        return {}
    primary = compound_record.get("primary")
    if not isinstance(primary, dict):
        primary = {}
    candidates = compound_record.get("candidates")
    if not isinstance(candidates, list):
        candidates = []

    aliases: list[str] = []
    primary_name = primary.get("name")
    if isinstance(primary_name, str) and primary_name.strip():
        aliases.append(primary_name.strip())
    aliases.extend(_normalize_entity_synonyms(compound_record.get("synonyms"), primary_name=primary_name))
    for candidate in candidates[:3]:
        if not isinstance(candidate, dict):
            continue
        cname = candidate.get("name")
        if isinstance(cname, str) and cname.strip():
            aliases.append(cname.strip())

    return {
        "primary_name": primary_name.strip() if isinstance(primary_name, str) and primary_name.strip() else "",
        "formula": str(primary.get("formula") or "").strip(),
        "exact_mass": _stringify_mass(primary.get("mass_da")),
        "smiles": str(primary.get("smiles") or "").strip(),
        "pubchem_cid": str(primary.get("pubchem_cid") or "").strip(),
        "aliases": [item for item in _normalize_entity_synonyms(aliases, primary_name=None) if _is_search_safe_synonym(item)],
    }


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _ensure_structured_verification_task(original_query: str) -> str:
    payload = _parse_original_task_payload(original_query)
    if isinstance(payload, dict) and payload:
        enriched_payload = dict(payload)
    else:
        entity_name = _extract_target_entity_name(original_query)
        if not entity_name:
            return original_query
        enriched_payload = {
            "task": "verify_candidate_entity",
            "entity_name": entity_name,
            "original_query": original_query,
        }
        refined_definition = extract_criteria_text(original_query)
        if isinstance(refined_definition, str) and refined_definition.strip() and refined_definition.strip() != original_query.strip():
            enriched_payload["refined_definition"] = refined_definition.strip()

    entity_name = str(enriched_payload.get("entity_name") or "").strip()
    if not entity_name:
        return json.dumps(enriched_payload, ensure_ascii=True, indent=2)

    merged_synonyms: list[str] = []
    merged_synonyms.extend(_normalize_entity_synonyms(enriched_payload.get("entity_synonyms"), primary_name=entity_name))

    normalized_synonyms = _normalize_entity_synonyms(merged_synonyms, primary_name=entity_name)
    if normalized_synonyms:
        enriched_payload["entity_synonyms"] = normalized_synonyms

    if isinstance(enriched_payload.get("seed_sources"), list) and not isinstance(enriched_payload.get("seed_source_brief"), list):
        seed_brief = _build_seed_source_brief(
            entity_name=entity_name,
            entity_synonyms=normalized_synonyms,
            seed_sources=enriched_payload.get("seed_sources"),
        )
        if seed_brief:
            enriched_payload["seed_source_brief"] = seed_brief

    if not isinstance(enriched_payload.get("search_budget"), dict):
        enriched_payload["search_budget"] = build_default_search_budget()

    return json.dumps(enriched_payload, ensure_ascii=True, indent=2)


def _run_required_followup_search(
    session_dir: str,
    critique_json: str | None,
    tool_config: RunnableConfig,
) -> list[str]:
    follow_up_queries = extract_next_queries_from_critique(critique_json)
    if not follow_up_queries:
        return []
    follow_up_queries = _dedupe_preserve_order(follow_up_queries)
    if not follow_up_queries:
        return []
    history = _FOLLOWUP_QUERY_HISTORY.setdefault(session_dir, set())
    new_queries: list[str] = []
    for query in follow_up_queries:
        key = query.strip().casefold()
        if key in history:
            continue
        history.add(key)
        new_queries.append(query)
    follow_up_queries = new_queries
    if not follow_up_queries:
        return []

    search_tool = next((tool for tool in down_stream_tools if getattr(tool, "name", "") == "fulltext_journal_search"), None)
    index_tool = next((tool for tool in down_stream_tools if getattr(tool, "name", "") == "fulltext_index"), None)
    if search_tool is None or index_tool is None:
        return []

    try:
        search_tool._run(query=follow_up_queries, max_results=V2_SEARCH_MAX_RESULTS, config=tool_config)
        index_tool._run(run_path=session_dir, config=tool_config)
    except Exception as exc:
        log.warning(f"Mandatory follow-up search failed for '{follow_up_queries[0]}': {exc}")
    return follow_up_queries


def _iter_text_values(obj: Any):
    if isinstance(obj, str):
        yield obj
        return
    if isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_text_values(value)
        return
    if isinstance(obj, list):
        for item in obj:
            yield from _iter_text_values(item)


def _looks_like_chemical_name(candidate: str) -> bool:
    if not isinstance(candidate, str):
        return False
    text = candidate.strip()
    if len(text) < 4 or len(text) > 140:
        return False
    lowered = text.lower()
    chemistry_markers = (
        "acid", "amine", "amide", "phenol", "quinone", "benz", "furan", "azole",
        "ketone", "aldehyde", "alcohol", "ester", "nitro", "chloro", "bromo",
        "iodo", "fluoro", "sulf", "carbazole", "dione", "trihalomethane"
    )
    return bool(re.search(r"\d", text) or "-" in text or any(marker in lowered for marker in chemistry_markers))


def _extract_quoted_compound_names(text: str) -> list[str]:
    candidates: list[str] = []
    if not isinstance(text, str) or not text.strip():
        return candidates
    for pattern in (r"'([^']{3,140})'", r'"([^"\\]{3,140})"'):
        for match in re.finditer(pattern, text):
            value = match.group(1).strip()
            if _looks_like_chemical_name(value):
                candidates.append(value)
    return candidates


def _split_compound_candidate_names(text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    if not isinstance(text, str) or not text.strip():
        return candidates

    parts = re.split(r"[;\n]+", text)
    for raw_part in parts:
        candidate = raw_part.strip(" \t,.:-")
        normalized_candidate = _normalize_entity_name(candidate)
        if not candidate or not normalized_candidate:
            continue
        if not _looks_like_chemical_name(candidate):
            continue
        if normalized_candidate in seen:
            continue
        seen.add(normalized_candidate)
        candidates.append(candidate)
    return candidates


def _extract_ambiguity_followup_candidate(target_entity: str, critique_obj: dict | None) -> tuple[str | None, str | None]:
    candidates, status = _extract_ambiguity_candidates(target_entity, critique_obj)
    if candidates:
        return candidates[0], status
    return None, None


def _extract_ambiguity_candidates(target_entity: str, critique_obj: dict | None) -> tuple[list[str], str | None]:
    if not isinstance(critique_obj, dict):
        return [], None

    critique_section = critique_obj.get("critique")
    if not isinstance(critique_section, dict):
        return [], None

    normalized_target = _normalize_entity_name(target_entity)
    entity_resolution = critique_section.get("entity_resolution")
    if isinstance(entity_resolution, dict):
        status = str(entity_resolution.get("status") or "").strip().lower()
        matched_name = str(entity_resolution.get("matched_name") or "").strip()
        candidate_names = _split_compound_candidate_names(matched_name)
        if status in {"mismatch", "ambiguous"} and candidate_names:
            filtered_candidates = [
                candidate for candidate in candidate_names
                if _normalize_entity_name(candidate) != normalized_target
            ]
            if filtered_candidates:
                return filtered_candidates, status
        if status in {"mismatch", "ambiguous"} and matched_name and _normalize_entity_name(matched_name) != normalized_target:
            return [matched_name], status

    joined_text = " ".join(_iter_text_values(critique_section)).lower()
    if not any(token in joined_text for token in ("mismatch", "different positional isomer", "identity / name match", "rather than", "exact named isomer", "close but different compound")):
        return [], None

    scored_candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for text in _iter_text_values(critique_section):
        lowered = text.lower()
        score = 0
        if "mismatch" in lowered or "isomer" in lowered:
            score += 2
        if "rather than" in lowered or "do you mean" in lowered:
            score += 2
        for candidate in _extract_quoted_compound_names(text):
            normalized_candidate = _normalize_entity_name(candidate)
            if not normalized_candidate or normalized_candidate == normalized_target or normalized_candidate in seen:
                continue
            seen.add(normalized_candidate)
            scored_candidates.append((score, candidate))

    if not scored_candidates:
        return [], None
    scored_candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    ordered_candidates = [candidate for _, candidate in scored_candidates]
    return ordered_candidates, "mismatch"


def _build_ambiguity_followup_query(original_query: str, candidate_name: str, criteria_text: str | None, entity_synonyms: list[str] | None = None) -> str:
    payload = _parse_original_task_payload(original_query)
    refined_definition = payload.get("refined_definition") if isinstance(payload.get("refined_definition"), str) else None
    refined_definition = refined_definition or criteria_text or extract_criteria_text(original_query)
    return build_verification_task_payload(
        entity_name=candidate_name,
        original_query=payload.get("original_query") if isinstance(payload.get("original_query"), str) and payload.get("original_query").strip() else original_query,
        refined_definition=refined_definition,
        entity_synonyms=_normalize_entity_synonyms(entity_synonyms, primary_name=candidate_name),
    )

def _safe_float(x):
    try:
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            return float(x.replace("–", "-").strip())
    except Exception:
        return None

def determine_explanation(messages):
    blob = _last_researcher_json(messages)
    if not blob:
        return ""
    try:
        obj = json.loads(blob)
        syn = obj.get("synthesis", {}) if isinstance(obj, dict) else {}
        explanation = syn.get("explanation")
        if isinstance(explanation, str) and explanation.strip():
            return explanation.strip()
    except Exception:
        pass
    m = re.search(r'"explanation"\s*:\s*"([^"]+)"', blob)
    if m:
        return m.group(1).strip()
    return ""

def _parse_json_object(raw: Any) -> dict | None:
    if isinstance(raw, dict):
        return raw
    if not raw or not isinstance(raw, str):
        return None
    def _extract_fenced_blocks(text: str) -> list[str]:
        blocks = []
        fence_re = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
        for match in fence_re.finditer(text):
            block = match.group(1).strip()
            if block:
                blocks.append(block)
        return blocks

    def _sanitize_json_text(text: str) -> str:
        chars = []
        in_string = False
        escape = False
        for ch in text:
            if escape:
                chars.append(ch)
                escape = False
                continue
            if ch == "\\":
                chars.append(ch)
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                chars.append(ch)
                continue
            if in_string and ch in ("\n", "\r"):
                chars.append(" ")
                continue
            chars.append(ch)
        return "".join(chars)

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        try:
            obj = json.loads(_sanitize_json_text(raw))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    fenced_blocks = _extract_fenced_blocks(raw)
    if fenced_blocks:
        fenced_blocks.sort(key=len, reverse=True)
        for candidate in fenced_blocks:
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict) and isinstance(obj.get("evidence"), list):
                    return obj
            except Exception:
                try:
                    obj = json.loads(_sanitize_json_text(candidate))
                    if isinstance(obj, dict) and isinstance(obj.get("evidence"), list):
                        return obj
                except Exception:
                    continue
        for candidate in fenced_blocks:
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                try:
                    obj = json.loads(_sanitize_json_text(candidate))
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    continue
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = raw[start:end + 1]
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            try:
                obj = json.loads(_sanitize_json_text(candidate))
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass
    matches = re.findall(r"\{[\s\S]*?\}", raw)
    if matches:
        # Prefer the largest JSON-like block to avoid truncation.
        matches.sort(key=len, reverse=True)
        for candidate in matches:
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict) and isinstance(obj.get("evidence"), list):
                    return obj
            except Exception:
                try:
                    obj = json.loads(_sanitize_json_text(candidate))
                    if isinstance(obj, dict) and isinstance(obj.get("evidence"), list):
                        return obj
                except Exception:
                    continue
        for candidate in matches:
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                try:
                    obj = json.loads(_sanitize_json_text(candidate))
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    continue
    return None

def _clean_doi(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"^https?://(dx\.)?doi\.org/", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^doi:\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

def _is_probable_doi(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return False
    cleaned = _clean_doi(value)
    if not cleaned.startswith("10."):
        return False
    return "/" in cleaned

def _split_doi_pmid(value: str | None) -> tuple[str, str]:
    if not value or not isinstance(value, str):
        return "", ""
    raw = value.strip()
    if not raw:
        return "", ""
    if _is_probable_doi(raw):
        return _clean_doi(raw), ""
    pmid_match = re.fullmatch(r"(?:PMID:)?\s*(\d{6,10})", raw, flags=re.IGNORECASE)
    if pmid_match:
        return "", pmid_match.group(1)
    return "", ""

_DOI_LOOKUP_CACHE: dict[str, dict] = {}

def _resolve_doi_via_eupmc(title: str | None) -> dict | None:
    if not title or not isinstance(title, str):
        return None
    key = _normalize_title(title)
    if not key:
        return None
    if key in _DOI_LOOKUP_CACHE:
        return _DOI_LOOKUP_CACHE[key]
    if os.environ.get("ENABLE_DOI_LOOKUP", "True").lower() not in ("true", "1", "yes"):
        return None
    try:
        query = f'TITLE:"{title}"'
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        resp = requests.get(url, params={"query": query, "format": "json", "pageSize": 1}, timeout=8)
        if resp.status_code != 200:
            return None
        payload = resp.json()
        results = (payload.get("resultList") or {}).get("result") or []
        if not results:
            return None
        top = results[0]
        doi_val = top.get("doi") or ""
        year_val = top.get("pubYear") or ""
        meta = {
            "doi": _clean_doi(doi_val) if doi_val else "",
            "year": str(year_val) if year_val else "",
        }
        _DOI_LOOKUP_CACHE[key] = meta
        return meta
    except Exception:
        return None

def _extract_researcher_evidence(research_obj: dict | None) -> list[dict]:
    if not isinstance(research_obj, dict):
        return []
    evidence = research_obj.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        traceability = research_obj.get("traceability")
        if isinstance(traceability, dict):
            trace_evidence = traceability.get("evidence")
            if isinstance(trace_evidence, list):
                evidence = trace_evidence
    if not isinstance(evidence, list):
        return []
    normalized = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        doi_or_pmid = item.get("doi_or_pmid")
        if not doi_or_pmid:
            doi_or_pmid = item.get("doi") or item.get("pmid") or ""
        doi, pmid = _split_doi_pmid(doi_or_pmid)
        quotes = item.get("quotes") if isinstance(item.get("quotes"), list) else None
        if quotes:
            for q in quotes:
                if not isinstance(q, dict):
                    continue
                entry = {
                    "id": item.get("id"),
                    "source_type": item.get("source_type") or "unknown",
                    "title": item.get("source_title") or item.get("title"),
                    "year": item.get("year"),
                    "doi": doi,
                    "retrieval_record_id": item.get("retrieval_record_id") or "",
                    "source_locator": item.get("source_locator") or "",
                    "snippet": q.get("quote") or q.get("snippet"),
                    "supports": q.get("supports") or item.get("supports") or item.get("why_relevant"),
                }
                if pmid:
                    entry["pmid"] = pmid
                normalized.append(entry)
            continue
        entry = {
            "id": item.get("id"),
            "source_type": item.get("source_type") or "unknown",
            "title": item.get("source_title") or item.get("title"),
            "year": item.get("year"),
            "doi": doi,
            "retrieval_record_id": item.get("retrieval_record_id") or "",
            "source_locator": item.get("source_locator") or "",
            "snippet": item.get("quote") or item.get("snippet"),
            "supports": item.get("supports") or item.get("why_relevant"),
        }
        if pmid:
            entry["pmid"] = pmid
        normalized.append(entry)
    return normalized


def _extract_ref_bullet_evidence(text: str | None) -> list[dict]:
    if not text or not isinstance(text, str):
        return []
    pattern = re.compile(
        r'(?:\*+\s*)?(?:\*\*)?(Ref\s+\d+)(?:\*\*)?:\s*'
        r'"(?P<title>[^"]+)"'
        r'(?:\s*\((?P<year>[^)]+)\))?'
        r'(?:,\s*doi:\s*(?P<doi>[^,]+))?'
        r',\s*quote:\s*"(?P<quote>.*?)"'
        r',\s*why_relevant:\s*(?P<why>.+?)(?=(?:\n\s*(?:\*+\s*)?(?:\*\*)?Ref\s+\d+)|\n\s*[}\]]|\Z)',
        flags=re.IGNORECASE | re.DOTALL,
    )
    evidence: list[dict] = []
    for match in pattern.finditer(text):
        ref_id = (match.group(1) or "").strip()
        title = (match.group("title") or "").strip()
        year = (match.group("year") or "").strip()
        doi = _clean_doi(match.group("doi") or "")
        quote = re.sub(r"\s+", " ", (match.group("quote") or "").strip())
        why = re.sub(r"\s+", " ", (match.group("why") or "").strip())
        if not ref_id or not quote:
            continue
        entry = {
            "id": ref_id,
            "title": title or None,
            "year": year or None,
            "doi": doi,
            "snippet": quote,
            "supports": why or None,
        }
        evidence.append(entry)
    return evidence


def _coerce_researcher_payload(raw: Any) -> dict | None:
    parsed = _parse_json_object(raw)
    if isinstance(parsed, dict):
        return parsed
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None

    claim = "Insufficient Direct Evidence"
    claim_match = re.search(r'"claim"\s*:\s*"([^"]+)"', text)
    if claim_match:
        claim = claim_match.group(1).strip() or claim
    else:
        prose_claim_match = re.search(
            r'(?:final claim|claim|decision)\s*[:=-]\s*(Confirmed|Suspected|Explicit Negative Evidence|Out of Scope Matrix or Context|Indirect or Class-Level Only|Missing Experimental Attribution|Insufficient Direct Evidence)',
            text,
            flags=re.IGNORECASE,
        )
        if prose_claim_match:
            claim = prose_claim_match.group(1).strip()

    evidence = _extract_ref_bullet_evidence(text)
    explanation = ""
    synthesis_match = re.search(r"SYNTHESIS:\s*(.+?)(?:\n[A-Z_ ]+:|\Z)", text, flags=re.DOTALL)
    if synthesis_match:
        explanation = re.sub(r"\s+", " ", synthesis_match.group(1)).strip()
    if not explanation:
        explanation = "Recovered from non-JSON researcher output."

    return {
        "verdict_statement": {
            "claim": claim,
            "brief_explanation": explanation[:240],
        },
        "synthesis": {
            "claim": claim,
            "explanation": explanation[:500],
            "confidence_score": "",
            "limitations": "Recovered from malformed researcher output.",
        },
        "coverage": {"notes": ""},
        "decision_basis": {},
        "criteria_assessment": {
            "criteria_source": "recovered_from_malformed_output",
            "claim_ceiling": claim,
            "items": [],
        },
        "solved_items": [],
        "unsolved_items": [],
        "traceability": {"evidence_sources": {}},
        "evidence": evidence,
        "limitations": "Malformed researcher output was coerced to JSON.",
        "next_actions": {"proposed_queries": []},
    }

def _extract_critique_payload(critique_obj: dict | None) -> dict:
    if not isinstance(critique_obj, dict):
        return {"decision": None, "rubric": None, "supporting_sources": [], "critique_claim": None, "researcher_claim_supported": None}
    critique_section = critique_obj.get("critique", {})
    if not isinstance(critique_section, dict):
        critique_section = {}
    supporting_sources = critique_obj.get("supporting_sources")
    if not isinstance(supporting_sources, list):
        supporting_sources = []
    rubric = critique_section.get("rubric")
    if not isinstance(rubric, dict):
        checklist = critique_section.get("checklist")
        if isinstance(checklist, list):
            criteria = []
            solved_count = 0
            for item in checklist:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "").strip().lower()
                name = str(item.get("item") or item.get("name") or "").strip()
                notes = str(item.get("notes") or "").strip()
                evidence_ids = item.get("evidence_ids")
                if not isinstance(evidence_ids, list):
                    evidence_ids = []
                criterion = {
                    "name": name,
                    "status": status or "",
                    "notes": notes,
                    "evidence_ids": evidence_ids,
                    "support_type": _infer_support_type(name, status, evidence_ids),
                    "priority": item.get("priority", "mandatory"),
                    "section": item.get("section", "criteria"),
                    "evidence_state": item.get("evidence_state", "unresolved"),
                    "supported_alternative": item.get("supported_alternative"),
                    "operator": item.get("operator"),
                    "alternatives": item.get("alternatives"),
                    "polarity": item.get("polarity"),
                }
                if status == "solved":
                    solved_count += 1
                    criterion["score"] = 1.0
                elif status in {"partial", "bridge_step1", "bridge_step2"}:
                    criterion["score"] = 0.5
                else:
                    criterion["score"] = 0.0
                criteria.append(criterion)
            if criteria:
                rubric = {
                    "overall_score": solved_count / len(criteria),
                    "criteria": criteria,
                }
    return {
        "decision": critique_section.get("decision"),
        "rubric": rubric,
        "supporting_sources": supporting_sources,
        "critique_claim": critique_section.get("critique_claim"),
        "researcher_claim_supported": critique_section.get("researcher_claim_supported"),
    }


def _criterion_tokens(text: str) -> set[str]:
    if not isinstance(text, str):
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in {
            "is", "the", "a", "an", "of", "in", "for", "and", "or", "to",
            "be", "was", "were", "are", "with", "from", "on", "by", "it",
            "this", "that", "as", "during", "does", "do",
        }
    }


def _infer_support_type(name: str, status: str, evidence_ids: list[str]) -> str:
    if evidence_ids:
        return "direct_evidence"
    lowered = str(name or "").strip().lower()
    if any(marker in lowered for marker in ("exclusion:", "scope:", "criteria:**", "evidence requirements:**", "exclusions:**", "scope:**")):
        return "rule_based"
    if status in {"solved", "partial"}:
        return "inferred"
    return "none"


def _align_critique_to_fixed_criteria(critique_obj: dict | None, criteria_text: str | None) -> dict | None:
    if not isinstance(critique_obj, dict):
        return critique_obj

    rubric_items = extract_rubric_items(criteria_text or "")
    if rubric_items:
        target_items = rubric_items
    else:
        fixed_criteria = extract_fixed_criteria_key_points(criteria_text or "")
        target_items = [{"name": name, "priority": "mandatory", "section": "criteria"} for name in fixed_criteria]
    if not target_items:
        return critique_obj

    critique_section = critique_obj.get("critique")
    if not isinstance(critique_section, dict):
        return critique_obj

    source_items: list[dict] = []
    rubric = critique_section.get("rubric")
    if isinstance(rubric, dict):
        criteria = rubric.get("criteria")
        if isinstance(criteria, list):
            for item in criteria:
                if isinstance(item, dict):
                    source_items.append(item)

    checklist = critique_section.get("checklist")
    if isinstance(checklist, list):
        for item in checklist:
            if isinstance(item, dict):
                source_items.append(item)

    if not source_items:
        return critique_obj

    used_indices: set[int] = set()
    aligned_checklist: list[dict] = []
    aligned_rubric_criteria: list[dict] = []

    def _source_name(item: dict) -> str:
        return str(item.get("name") or item.get("item") or "").strip()

    for pos, target_item in enumerate(target_items):
        fixed_name = str(target_item.get("name") or "").strip()
        best_idx = None
        for idx, item in enumerate(source_items):
            if idx in used_indices:
                continue
            if _source_name(item) == fixed_name:
                best_idx = idx
                break

        source = source_items[best_idx] if best_idx is not None else {}
        if best_idx is not None:
            used_indices.add(best_idx)

        status = str(source.get("status") or "").strip().lower() or "unsolved"
        notes = str(source.get("notes") or "").strip()
        evidence_ids = source.get("evidence_ids")
        if not isinstance(evidence_ids, list):
            evidence_ids = []
        follow_up_queries = source.get("follow_up_queries")
        if not isinstance(follow_up_queries, list):
            follow_up_queries = []

        if status == "solved":
            score = 1.0
        elif status in {"partial", "bridge_step1", "bridge_step2"}:
            score = 0.5
        else:
            score = 0.0

        aligned_checklist.append({
            "item": fixed_name,
            "priority": str(target_item.get("priority") or "mandatory"),
            "section": str(target_item.get("section") or "criteria"),
            "status": status,
            "notes": notes,
            "evidence_ids": evidence_ids,
            "support_type": _infer_support_type(fixed_name, status, evidence_ids),
            "follow_up_queries": follow_up_queries,
            "evidence_state": source.get("evidence_state", "unresolved"),
            "supported_alternative": source.get("supported_alternative"),
            "operator": target_item.get("operator"),
            "alternatives": target_item.get("alternatives"),
            "polarity": target_item.get("polarity"),
        })
        aligned_rubric_criteria.append({
            "name": fixed_name,
            "priority": str(target_item.get("priority") or "mandatory"),
            "section": str(target_item.get("section") or "criteria"),
            "status": status,
            "notes": notes,
            "evidence_ids": evidence_ids,
            "support_type": _infer_support_type(fixed_name, status, evidence_ids),
            "score": score,
            "evidence_state": source.get("evidence_state", "unresolved"),
            "supported_alternative": source.get("supported_alternative"),
            "operator": target_item.get("operator"),
            "alternatives": target_item.get("alternatives"),
            "polarity": target_item.get("polarity"),
        })

    extra_items = []
    for idx, item in enumerate(source_items):
        if idx in used_indices or not isinstance(item, dict):
            continue
        name = _source_name(item)
        notes = str(item.get("notes") or "").strip()
        if name or notes:
            extra_items.append({
                "item": name,
                "notes": notes,
                "status": str(item.get("status") or "").strip().lower(),
            })

    critique_section["checklist"] = aligned_checklist
    critique_section["rubric"] = {
        "overall_score": (
            sum(item.get("score", 0.0) for item in aligned_rubric_criteria) / len(aligned_rubric_criteria)
            if aligned_rubric_criteria else 0.0
        ),
        "criteria": aligned_rubric_criteria,
    }
    if extra_items:
        critique_section["additional_considerations"] = extra_items

    return critique_obj


def _normalize_claim_label(claim: str | None) -> str:
    from result_labels import normalize_claim_label

    return normalize_claim_label(claim)


def _derive_final_adjudicated_claim(
    researcher_claim: str,
    critique_decision: str | None,
    stop_reason: str | None,
    agreement_status: str | None = None,
    critique_claim: str | None = None,
    critique_payload: dict | None = None,
    expected_criteria: list | None = None,
) -> tuple[str, bool, str]:
    from decision_contract import adjudicate
    return adjudicate(
        _normalize_claim_label(researcher_claim), critique_decision, stop_reason,
        agreement_status, _normalize_claim_label(critique_claim) if critique_claim else None,
        critique_payload, expected_criteria)




def _all_rubric_items_solved(critique_payload: dict | None) -> bool:
    from decision_contract import assess_conditions
    return assess_conditions(critique_payload)[0]


def _is_valid_approved_stop(
    stop_reason: str | None,
    critique_decision: str | None,
    agreement_status: str | None,
    critique_payload: dict | None,
) -> bool:
    normalized_reason = (stop_reason or "").strip().upper()
    if normalized_reason != "APPROVED":
        return True

    normalized_decision = (critique_decision or "").strip().lower()
    normalized_agreement = (agreement_status or "").strip().lower()
    return (
        normalized_decision == "approve"
        and _all_rubric_items_solved(critique_payload)
        and (normalized_agreement in {"agree", "disagree", "unknown", ""})
    )


def _derive_specific_negative_claim(
    final_claim: str,
    critique_payload: dict | None,
    evidence: list[dict] | None,
) -> str:
    normalized_claim = _normalize_claim_label(final_claim)
    if normalized_claim != "Insufficient Direct Evidence":
        return normalized_claim

    evidence_list = evidence if isinstance(evidence, list) else []
    support_labels = {
        str(item.get("supports") or "").strip().lower()
        for item in evidence_list
        if isinstance(item, dict) and str(item.get("supports") or "").strip()
    }
    quotes = " ".join(
        str(item.get("quote") or item.get("snippet") or "")
        for item in evidence_list
        if isinstance(item, dict)
    ).lower()

    critique_payload = critique_payload if isinstance(critique_payload, dict) else {}
    notes_blob_parts: list[str] = []
    rubric = critique_payload.get("rubric")
    if isinstance(rubric, dict):
        criteria = rubric.get("criteria")
        if isinstance(criteria, list):
            for item in criteria:
                if isinstance(item, dict):
                    notes_blob_parts.append(str(item.get("notes") or ""))
                    notes_blob_parts.append(str(item.get("name") or ""))
    checklist = critique_payload.get("checklist")
    if isinstance(checklist, list):
        for item in checklist:
            if isinstance(item, dict):
                notes_blob_parts.append(str(item.get("notes") or ""))
                notes_blob_parts.append(str(item.get("item") or ""))
    notes_blob_parts.append(str(critique_payload.get("reasoning") or ""))
    notes_blob = " ".join(notes_blob_parts).lower()

    if (
        "explicit_negative" in support_labels
        or "not detected" in notes_blob
        or "not observed" in notes_blob
        or "negative finding" in notes_blob
        or "not detected" in quotes
        or "not observed" in quotes
    ):
        return "Explicit Negative Evidence"
    if (
        "produced waters" in notes_blob
        or "non-drinking" in notes_blob
        or "not drinking water" in notes_blob
        or "other biological matrices" in notes_blob
        or "not human blood" in notes_blob
    ):
        return "Out of Scope Matrix or Context"
    if (
        "near_miss" in support_labels
        or "near-miss" in notes_blob
        or "class-level" in notes_blob
        or "different-isomer" in notes_blob
        or "indirect" in notes_blob
    ):
        return "Indirect or Class-Level Only"
    if (
        "no controlled" in notes_blob
        or "no pre/post" in notes_blob
        or "no mechanistic attribution" in notes_blob
        or ("no study" in notes_blob and "formation" in notes_blob)
    ):
        return "Missing Experimental Attribution"
    if (
        "no direct evidence" in notes_blob
        or "no analytical detection" in notes_blob
        or "did not provide direct evidence" in notes_blob
        or "no direct analytical detection" in notes_blob
    ):
        return "Insufficient Direct Evidence"
    return "Insufficient Direct Evidence"

def _normalize_title(value: str | None) -> str:
    if not value or not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", value.strip().lower())
    cleaned = re.sub(r"[^a-z0-9 ]+", "", cleaned)
    return cleaned

def _is_unknown_year(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return True
    cleaned = value.strip().lower()
    return cleaned in ("", "unknown", "unknown year", "n/a", "na", "none")


def _normalize_snippet_text(value: str | None) -> str:
    if not value or not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _normalize_support_text(value: str | None) -> str:
    if not value or not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _infer_title_from_snippet(value: str | None) -> str:
    snippet = _normalize_snippet_text(value)
    if not snippet:
        return ""
    match = re.match(r"^Title:\s*(.+?)(?:\.\.\s+|\.\s+##\s+|\.?\s+The\s+|\.?\s+Dichloroacetonitrile\s+\(|$)", snippet)
    if not match:
        match = re.match(r"^Title:\s*(.+?)(?:\.\.|$)", snippet)
    if not match:
        return ""
    title = re.sub(r"\s+", " ", (match.group(1) or "").strip())
    title = re.sub(r"\.+$", "", title).strip()
    return title


def _evidence_paper_key(item: dict | None) -> str:
    if not isinstance(item, dict):
        return ""
    doi_val = _clean_doi(item.get("doi") or "")
    if doi_val:
        return f"doi:{doi_val}"
    pmid_val = str(item.get("pmid") or "").strip()
    if pmid_val:
        return f"pmid:{pmid_val}"
    title_key = _normalize_title(item.get("title") or "")
    if title_key:
        return f"title:{title_key}"
    snippet_key = _normalize_snippet_text(item.get("snippet") or "")
    if snippet_key:
        return f"snippet:{snippet_key[:200]}"
    return ""


def _merge_evidence_items(evidence: list[dict] | None) -> list[dict]:
    if not isinstance(evidence, list) or not evidence:
        return []

    merged_by_key: dict[str, dict] = {}
    ordered_keys: list[str] = []
    orphan_counter = 0

    for raw_item in evidence:
        if not isinstance(raw_item, dict):
            continue

        item = dict(raw_item)
        item["snippet"] = _normalize_snippet_text(item.get("snippet"))
        item["supports"] = _normalize_support_text(item.get("supports"))
        if not item.get("title"):
            inferred_title = _infer_title_from_snippet(item.get("snippet"))
            if inferred_title:
                item["title"] = inferred_title
        if item.get("doi"):
            item["doi"] = _clean_doi(item.get("doi") or "")
        if item.get("pmid"):
            item["pmid"] = str(item.get("pmid") or "").strip()

        paper_key = _evidence_paper_key(item)
        if not paper_key:
            orphan_counter += 1
            paper_key = f"orphan:{orphan_counter}"

        if paper_key not in merged_by_key:
            merged_by_key[paper_key] = {
                "id": item.get("id"),
                "source_type": item.get("source_type") or "primary_paper",
                "title": item.get("title") or None,
                "year": item.get("year") or None,
                "doi": item.get("doi") or "",
                "snippet": item.get("snippet") or None,
                "supports": item.get("supports") or None,
                "original_ids": [item.get("id")] if item.get("id") else [],
                "snippets": [item.get("snippet")] if item.get("snippet") else [],
                "support_notes": [item.get("supports")] if item.get("supports") else [],
            }
            if item.get("pmid"):
                merged_by_key[paper_key]["pmid"] = item.get("pmid")
            ordered_keys.append(paper_key)
            continue

        merged = merged_by_key[paper_key]

        if not merged.get("title") and item.get("title"):
            merged["title"] = item.get("title")
        if (
            merged.get("source_type") != "compound_database"
            and item.get("source_type") == "compound_database"
        ):
            merged["source_type"] = "compound_database"
        if _is_unknown_year(merged.get("year")) and not _is_unknown_year(item.get("year")):
            merged["year"] = item.get("year")
        if not merged.get("doi") and item.get("doi"):
            merged["doi"] = item.get("doi")
        if not merged.get("pmid") and item.get("pmid"):
            merged["pmid"] = item.get("pmid")

        if item.get("id") and item.get("id") not in merged["original_ids"]:
            merged["original_ids"].append(item.get("id"))
        if item.get("snippet") and item.get("snippet") not in merged["snippets"]:
            merged["snippets"].append(item.get("snippet"))
        if item.get("supports") and item.get("supports") not in merged["support_notes"]:
            merged["support_notes"].append(item.get("supports"))

    merged_evidence: list[dict] = []
    for idx, paper_key in enumerate(ordered_keys, start=1):
        item = merged_by_key[paper_key]
        snippets = [s for s in item.pop("snippets", []) if s]
        supports = [s for s in item.pop("support_notes", []) if s]
        item["id"] = f"Ref {idx}"
        quote_objs = []
        for pos, quote in enumerate(snippets):
            support_val = supports[pos] if pos < len(supports) else (supports[0] if supports else None)
            quote_obj = {"quote": quote}
            if support_val:
                quote_obj["supports"] = support_val
            quote_objs.append(quote_obj)
        item["quotes"] = quote_objs
        if not item.get("doi"):
            item.pop("doi", None)
        if not item.get("pmid"):
            item.pop("pmid", None)
        if not item.get("year"):
            item.pop("year", None)
        if not item.get("title"):
            item.pop("title", None)
        item.pop("snippet", None)
        item.pop("supports", None)
        merged_evidence.append(item)

    return merged_evidence

def _load_doc_metadata(results_dir: str | None) -> dict[str, dict]:
    if not results_dir:
        return {}
    index_path = Path(results_dir) / "index.ndjson"
    if not index_path.exists():
        return {}
    lookup: dict[str, dict] = {}
    by_title: dict[str, dict] = {}
    by_pmid: dict[str, dict] = {}
    by_pmcid: dict[str, dict] = {}
    by_doi: dict[str, dict] = {}
    try:
        with index_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                title = obj.get("title") or ""
                key = _normalize_title(title)
                if not key:
                    continue
                ids = obj.get("ids") or {}
                doi_val = obj.get("doi") or ids.get("doi") or ""
                pmid_val = ids.get("pmid") or obj.get("pmid") or ""
                pmcid_val = ids.get("pmcid") or obj.get("pmcid") or ""
                meta = {
                    "title": title,
                    "doi": doi_val,
                    "year": (obj.get("pubdate") or ""),
                    "pmid": pmid_val,
                    "pmcid": pmcid_val,
                }
                lookup[key] = meta
                by_title[key] = meta
                if pmid_val:
                    by_pmid[str(pmid_val)] = meta
                if pmcid_val:
                    by_pmcid[str(pmcid_val)] = meta
                if doi_val:
                    by_doi[_clean_doi(doi_val)] = meta
    except Exception:
        return {}
    return {
        "by_title": by_title,
        "by_pmid": by_pmid,
        "by_pmcid": by_pmcid,
        "by_doi": by_doi,
    }

def _extract_rubric_fields(rubric: dict | None) -> dict:
    if not isinstance(rubric, dict):
        return {
            "overall_score": "",
            "criteria_count": 0,
            "criteria_json": "[]",
            "criterion_1_name": "",
            "criterion_1_score": "",
            "criterion_1_notes": "",
            "criterion_2_name": "",
            "criterion_2_score": "",
            "criterion_2_notes": "",
        }
    criteria = rubric.get("criteria")
    if not isinstance(criteria, list):
        criteria = []
    def _criterion_payload(index: int) -> dict:
        if index >= len(criteria) or not isinstance(criteria[index], dict):
            return {"name": "", "score": "", "notes": ""}
        item = criteria[index]
        return {
            "name": item.get("name") or "",
            "score": item.get("score") if item.get("score") is not None else "",
            "notes": item.get("notes") or "",
        }
    crit_1 = _criterion_payload(0)
    crit_2 = _criterion_payload(1)
    return {
        "overall_score": rubric.get("overall_score") if rubric.get("overall_score") is not None else "",
        "criteria_count": len(criteria),
        "criteria_json": json.dumps(criteria, ensure_ascii=True),
        "criterion_1_name": crit_1["name"],
        "criterion_1_score": crit_1["score"],
        "criterion_1_notes": crit_1["notes"],
        "criterion_2_name": crit_2["name"],
        "criterion_2_score": crit_2["score"],
        "criterion_2_notes": crit_2["notes"],
    }


def _normalize_critique_progress_fields(payload: dict | None, has_previous_critique: bool) -> dict | None:
    if not isinstance(payload, dict) or has_previous_critique:
        return payload

    critique_section = payload.get("critique")
    if not isinstance(critique_section, dict):
        return payload

    rubric = critique_section.get("rubric")
    if isinstance(rubric, dict):
        criteria = rubric.get("criteria")
        if isinstance(criteria, list):
            for item in criteria:
                if isinstance(item, dict):
                    item.pop("resolved_since_last_round", None)

    checklist = critique_section.get("checklist")
    if isinstance(checklist, list):
        for item in checklist:
            if isinstance(item, dict):
                item.pop("resolved_since_last_round", None)

    return payload


def _extract_unsolved_criteria_signature(critique_obj: dict | None) -> tuple[str, ...]:
    if not isinstance(critique_obj, dict):
        return ()
    critique_section = critique_obj.get("critique")
    if not isinstance(critique_section, dict):
        return ()

    names: list[str] = []
    rubric = critique_section.get("rubric")
    if isinstance(rubric, dict):
        criteria = rubric.get("criteria")
        if isinstance(criteria, list):
            for item in criteria:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "").strip().lower()
                if status == "solved":
                    continue
                name = str(item.get("name") or "").strip()
                if name:
                    names.append(name)

    if not names:
        checklist = critique_section.get("checklist")
        if isinstance(checklist, list):
            for item in checklist:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "").strip().lower()
                if status == "solved":
                    continue
                name = str(item.get("item") or item.get("name") or "").strip()
                if name:
                    names.append(name)

    return tuple(sorted(set(names)))


def _extract_follow_up_query_signature(critique_obj: dict | None) -> tuple[str, ...]:
    if not isinstance(critique_obj, dict):
        return ()
    critique_section = critique_obj.get("critique")
    if not isinstance(critique_section, dict):
        return ()

    queries: list[str] = []
    next_query = critique_section.get("next_query")
    if isinstance(next_query, str) and next_query.strip():
        queries.append(next_query.strip())
    elif isinstance(next_query, list):
        queries.extend(str(item).strip() for item in next_query if str(item).strip())

    checklist = critique_section.get("checklist")
    if isinstance(checklist, list):
        for item in checklist:
            if not isinstance(item, dict):
                continue
            follow_up = item.get("follow_up_queries")
            if isinstance(follow_up, str) and follow_up.strip():
                queries.append(follow_up.strip())
            elif isinstance(follow_up, list):
                queries.extend(str(entry).strip() for entry in follow_up if str(entry).strip())

    return tuple(sorted(set(queries)))


def _detect_no_progress(previous_critique: dict | None, current_critique: dict | None) -> tuple[bool, bool]:
    prev_unsolved = _extract_unsolved_criteria_signature(previous_critique)
    curr_unsolved = _extract_unsolved_criteria_signature(current_critique)
    prev_queries = _extract_follow_up_query_signature(previous_critique)
    curr_queries = _extract_follow_up_query_signature(current_critique)

    unchanged_unsolved = bool(curr_unsolved) and curr_unsolved == prev_unsolved
    repeated_followups = bool(curr_queries) and curr_queries == prev_queries
    return unchanged_unsolved, repeated_followups

def _write_csv_outputs(report: dict, results_dir: str | None, output_dir: str) -> None:
    try:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    run_id = Path(results_dir).name if results_dir else ""
    summary_path = output_path / (f"summary_{run_id}.csv" if run_id else "summary.csv")
    evidence_path = output_path / (f"evidence_{run_id}.csv" if run_id else "evidence.csv")

    rubric_fields = _extract_rubric_fields(report.get("rubric"))
    summary_row = {
        "results_dir": report.get("results_dir") or "",
        "query": report.get("query") or "",
        "claim": report.get("claim") or "",
        "researcher_claim": report.get("researcher_claim") or "",
        "final_adjudicated_claim": report.get("final_adjudicated_claim") or "",
        "accepted": report.get("accepted") if report.get("accepted") is not None else "",
        "critique_decision": report.get("critique_decision") or "",
        "stop_reason": report.get("stop_reason") or "",
        "tokens_used": report.get("tokens_used") if report.get("tokens_used") is not None else "",
        "cost_usd": report.get("cost_usd") if report.get("cost_usd") is not None else "",
        **rubric_fields,
    }
    with summary_path.open("w", encoding="utf-8", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=list(summary_row.keys()))
        writer.writeheader()
        writer.writerow(summary_row)

    evidence_rows = []
    for item in report.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        evidence_rows.append({
            "results_dir": report.get("results_dir") or "",
            "evidence_id": item.get("id") or "",
            "title": item.get("title") or "",
            "year": item.get("year") or "",
            "doi": item.get("doi") or "",
            "snippet": item.get("snippet") or "",
            "supports": item.get("supports") or "",
        })
    with evidence_path.open("w", encoding="utf-8", newline="") as csvfile:
        fieldnames = ["results_dir", "evidence_id", "title", "year", "doi", "snippet", "supports"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in evidence_rows:
            writer.writerow(row)

# -------------------- nodes --------------------
def _researcher_ready_for_critique(last_researcher_json: str | None) -> bool:
    obj = _parse_json_object(last_researcher_json)
    if not isinstance(obj, dict):
        return False

    unsolved_items = obj.get("unsolved_items")
    if isinstance(unsolved_items, list) and any(str(item).strip() for item in unsolved_items):
        return False

    criteria = None
    criteria_assessment = obj.get("criteria_assessment")
    if isinstance(criteria_assessment, dict):
        criteria = criteria_assessment.get("items")
    if isinstance(criteria, list) and criteria:
        return all(
            isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "solved"
            for item in criteria
        )

    return False


def _critique_has_actionable_followup(critique_obj: dict | None) -> bool:
    return bool(_extract_follow_up_query_signature(critique_obj))


def researcher_should_continue(state: DownAgentState):
    round_count = int(state.get("researcher_round_count", 0) or 0)
    if _researcher_ready_for_critique(state.get("last_researcher_json")):
        return "critique"
    if round_count >= max(1, PRE_CRITIQUE_RESEARCHER_ROUNDS):
        return "critique"
    return "researcher"


def researcher_node(state: DownAgentState, config: RunnableConfig):
    _vprint("-----Researcher Node Invoked-----")

    current_task = _ensure_structured_verification_task(state.get("original_query", ""))
    if os.environ.get("STATIC_RESEARCHER_SINGLE_QUERY", "False") == "True":
        current_task = (
            current_task
            + "\n\nAblation constraint: perform a static, one-pass evidence search. "
            "Use at most one focused literature-search query for this candidate, then "
            "produce the best rubric-grounded researcher JSON from that evidence. "
            "Do not run iterative follow-up searches or broaden the query set."
        )
    crit_json = state.get("last_critique_json")
    prev_research_json = state.get("last_researcher_json") or _last_researcher_json(state.get("messages", []))

    if crit_json and prev_research_json:
        input_messages = [
            HumanMessage(
                content=build_researcher_followup_payload(
                    current_task=current_task,
                    previous_researcher_json=prev_research_json,
                    review_feedback_json=crit_json,
                )
            )
        ]
    else:
        input_messages = [HumanMessage(content=current_task)]

    session_dir = state.get("search_session_dir")
    if not session_dir:
        raise ValueError("search_session_dir not found in state.")

    tool_config = config.copy()
    tool_config["configurable"] = config.get("configurable", {}).copy()
    tool_config["configurable"]["search_session_dir"] = session_dir

    # (tags/metadata optional)
    tags = list(tool_config.get("tags") or [])
    tags.append(f"SSD::{session_dir}")
    tags.append(f"search_session_dir={session_dir}")
    tool_config["tags"] = tags

    metadata = dict(tool_config.get("metadata") or {})
    metadata["search_session_dir"] = session_dir
    tool_config["metadata"] = metadata

    tool_config.pop("recursion_limit", None)

    if crit_json:
        _run_required_followup_search(session_dir, crit_json, tool_config)

    # ---- Seed ContextVar for all tools (authoritative path propagation)
    try:
        FullTextJournalSearchTool.set_session_dir(session_dir)
        FullTextIndexTool.set_session_dir(session_dir)
        FullTextQueryTool.set_session_dir(session_dir)
    except Exception:
        pass

    # Seed exact target entity for compound tool guardrails so malformed LLM tool-call
    # variants do not drop positional descriptors (e.g., 2-(2,4-...)).
    target_entity = _extract_target_entity_name(current_task)
    try:
        CompoundDatabaseTool.set_target_compound(target_entity)
    except Exception:
        pass

    try:
        result = researcher_agent_executor.invoke({"messages": input_messages}, config=tool_config)
    finally:
        try:
            CompoundDatabaseTool.set_target_compound(None)
        except Exception:
            pass

    ai_content = ""
    if 'messages' in result and isinstance(result['messages'], list) and result['messages']:
        ai_content = result['messages'][-1].content
        _vprint(f"\n[Researcher Output]:\n{ai_content}\n")
    else:
        _vprint("[ERROR] Agent executor did not return expected messages list.")
        ai_content = build_researcher_fallback_payload()

    new_ai_message = AIMessage(content=ai_content)
    all_messages = state["messages"] + [new_ai_message]

    return {
        "messages": all_messages,
        "original_query": current_task,
        "last_researcher_json": _last_researcher_json(all_messages),
        "prior_critique_json": crit_json,
        "last_critique_json": None,
        "researcher_round_count": state.get("researcher_round_count", 0) + 1,
        "critique_round_count": state.get("critique_round_count", 0),
    }

def critique_node(state: DownAgentState, config: RunnableConfig):
    _vprint("-----Critique Node Invoked-----")

    last_researcher_json = _last_researcher_json(state.get("messages", [])) or ""
    if not last_researcher_json:
        last_researcher_json = (state["messages"][-1].content if state.get("messages") else "").strip()

    original_query = state.get("original_query", "")
    criteria_text = state.get("criteria_text")
    if not criteria_text:
        criteria_text = extract_criteria_text(original_query)

    # --- ABLATION: DISABLE CRITIQUE AGENT ---
    import os
    env_val = os.environ.get("ENABLE_CRITIQUE_AGENT", "True")
    _vprint(f"[DEBUG:CRITIQUE_NODE] ENABLE_CRITIQUE_AGENT={env_val}")
    
    if env_val == "False":
        _vprint("-----Critique Node Bypassed (Ablation: ENABLE_CRITIQUE_AGENT=False)-----")
        dummy_content = build_critique_auto_approval_payload()
        
        # Manually extract claims to support the history update
        msgs = state.get("messages", [])
        claim = determine_final_claim(msgs)
        
        history = copy.deepcopy(state.get("stop_history", []))
        history.append({
            "claim": claim,
            "supporting_sources": [],
            "tool_name": None,
            "stop_reason": "APPROVED",
        })
        
        return {
            "messages": state["messages"] + [AIMessage(content=dummy_content)],
            "criteria_text": criteria_text,
            "prior_critique_json": state.get("prior_critique_json"),
            "stop_history": history,
            "consecutive_no_new_evidence": state.get("consecutive_no_new_evidence", 0),
            "consecutive_tool_unavailable": state.get("consecutive_tool_unavailable", 0),
            "last_researcher_json": last_researcher_json,
            "first_researcher_json": state.get("first_researcher_json") or last_researcher_json,
            "last_critique_json": dummy_content,
            "claim_history": state.get("claim_history", []) + [claim],
        }

    critique_input = build_critique_request_payload(
        criteria_text=criteria_text,
        researcher_output_json=last_researcher_json,
        current_task=original_query,
        previous_critique_json=state.get("prior_critique_json"),
    )

    session_dir = state.get("search_session_dir")
    if not session_dir:
        raise ValueError("search_session_dir not found in state.")

    tool_config = config.copy()
    tool_config["configurable"] = config.get("configurable", {}).copy()
    tool_config["configurable"]["search_session_dir"] = session_dir

    tags = list(tool_config.get("tags") or [])
    tags.append(f"SSD::{session_dir}")
    tags.append(f"search_session_dir={session_dir}")
    tool_config["tags"] = tags

    metadata = dict(tool_config.get("metadata") or {})
    metadata["search_session_dir"] = session_dir
    tool_config["metadata"] = metadata

    tool_config.pop("recursion_limit", None)

    # Seed ContextVar for tools here as well
    try:
        FullTextJournalSearchTool.set_session_dir(session_dir)
        FullTextIndexTool.set_session_dir(session_dir)
        FullTextQueryTool.set_session_dir(session_dir)
    except Exception:
        pass

    critique_result = critique_agent_executor.invoke({"messages": [HumanMessage(content=critique_input)]}, config=tool_config)

    critique_content = critique_result['messages'][-1].content
    _vprint(f"\n[Critique Output]:\n{critique_content}\n")
    raw = (critique_content or "").strip()

    parsed = _parse_json_object(raw)
    if parsed:
        parsed = _align_critique_to_fixed_criteria(parsed, original_query or criteria_text)
        try:
            critique_content = json.dumps(parsed, ensure_ascii=True, indent=2)
        except Exception:
            pass

    stop_reason = None
    supporting_sources: List[str] = []
    tool_name: str | None = None
    critique_claim: str | None = None
    researcher_claim_supported: bool | None = None
    agreement_status = "unknown"

    if parsed:
        candidate_reason = parsed.get("stop_reason")
        if isinstance(candidate_reason, str) and candidate_reason.strip():
            normalized_reason = candidate_reason.strip().upper()
            if normalized_reason in {"APPROVED", "REJECTED", "TOOL_UNAVAILABLE"}:
                stop_reason = normalized_reason
        critique_section = parsed.get("critique", {})
        if isinstance(critique_section, dict):
            critique_claim_raw = critique_section.get("critique_claim")
            if isinstance(critique_claim_raw, str) and critique_claim_raw.strip():
                critique_claim = _normalize_claim_label(critique_claim_raw)
            supported_raw = critique_section.get("researcher_claim_supported")
            if isinstance(supported_raw, bool):
                researcher_claim_supported = supported_raw
            decision = critique_section.get("decision")
            if isinstance(decision, str) and not stop_reason:
                normalized_decision = decision.strip().lower()
                if normalized_decision == "approve":
                    stop_reason = "APPROVED"
                elif normalized_decision == "reject":
                    stop_reason = "REJECTED"
        sources = parsed.get("supporting_sources")
        if isinstance(sources, list):
            supporting_sources = sources
        candidate_tool = parsed.get("tool_name")
        if isinstance(candidate_tool, str) and candidate_tool.strip():
            tool_name = candidate_tool.strip()
    def _extract_claim(messages):
        blob = _last_researcher_json(messages)
        claim = "Insufficient Direct Evidence"
        if not blob:
            return claim
        try:
            obj = json.loads(blob)
            if isinstance(obj, dict):
                verdict_statement = obj.get("verdict_statement", {})
                if isinstance(verdict_statement, dict):
                    claim = (verdict_statement.get("claim") or "").strip()
                if not claim:
                    synthesis = obj.get("synthesis", {})
                    claim = (synthesis.get("claim") or "").strip() if isinstance(synthesis, dict) else ""
        except Exception:
            pass
        if not claim:
            match_claim = re.search(r'"claim"\s*:\s*"([^"]+)"', blob)
            if match_claim:
                claim = match_claim.group(1).strip()
        return _normalize_claim_label(claim or "Insufficient Direct Evidence")

    claim = _extract_claim(state.get("messages", []))

    if critique_claim is None and parsed:
        critique_payload = _extract_critique_payload(parsed)
        candidate_claim = critique_payload.get("critique_claim")
        if isinstance(candidate_claim, str) and candidate_claim.strip():
            critique_claim = _normalize_claim_label(candidate_claim)
        candidate_supported = critique_payload.get("researcher_claim_supported")
        if isinstance(candidate_supported, bool):
            researcher_claim_supported = candidate_supported

    if critique_claim and claim:
        agreement_status = "agree" if critique_claim == claim else "disagree"
    elif researcher_claim_supported is True:
        agreement_status = "agree"
    elif researcher_claim_supported is False:
        agreement_status = "disagree"

    critique_payload = _extract_critique_payload(parsed) if isinstance(parsed, dict) else {}
    if isinstance(critique_payload, dict):
        unsolved_items = critique_payload.get("unsolved_items") or []
    else:
        unsolved_items = []

    invalid_approved_stop = not _is_valid_approved_stop(
        stop_reason,
        (critique_payload.get("decision") if isinstance(critique_payload, dict) else None),
        agreement_status,
        critique_payload,
    )
    if invalid_approved_stop:
        stop_reason = None

    history = copy.deepcopy(state.get("stop_history", []))
    history.append({
        "claim": claim,
        "critique_claim": critique_claim or "",
        "agreement_status": agreement_status,
        "supporting_sources": supporting_sources,
        "tool_name": tool_name,
        "stop_reason": stop_reason,
    })

    prev_critique_obj = _parse_json_object(state.get("prior_critique_json"))
    prev_no_new = state.get("consecutive_no_new_evidence", 0)
    prev_tool_unavailable = state.get("consecutive_tool_unavailable", 0)
    unchanged_unsolved, repeated_followups = _detect_no_progress(prev_critique_obj, parsed)
    no_new = 0
    if stop_reason == "APPROVED":
        no_new = 0
    elif unchanged_unsolved or repeated_followups:
        no_new = prev_no_new + 1
    else:
        no_new = 0

    claim_hist = list(state.get("claim_history", []))
    claim_hist.append(claim if isinstance(claim, str) else "Insufficient Direct Evidence")

    critique_round_count = int(state.get("critique_round_count", 0) or 0)
    has_actionable_followup = _critique_has_actionable_followup(parsed)

    if no_new >= NO_PROGRESS_EXHAUSTION_THRESHOLD and not stop_reason:
        stop_reason = "EXHAUSTED_NO_PROGRESS"
        if history:
            history[-1]["stop_reason"] = stop_reason

    if (not stop_reason) and critique_round_count >= 1:
        stop_reason = "EXHAUSTED_NO_PROGRESS"
        if history:
            history[-1]["stop_reason"] = stop_reason

    if (not stop_reason) and critique_round_count == 0 and not has_actionable_followup:
        stop_reason = "EXHAUSTED_NO_PROGRESS"
        if history:
            history[-1]["stop_reason"] = stop_reason

    _vprint(f"[critique_node] stop_reason={stop_reason}")

    patched_content = critique_content
    if parsed is not None:
        parsed = _normalize_critique_progress_fields(
            parsed,
            has_previous_critique=bool(state.get("prior_critique_json")),
        )
        patched = dict(parsed)
        critique_section = patched.get("critique")
        if isinstance(critique_section, dict):
            critique_section["researcher_claim_supported"] = researcher_claim_supported
            if critique_claim:
                critique_section["critique_claim"] = critique_claim
            critique_section["agreement_status"] = agreement_status
        if stop_reason:
            patched["stop_reason"] = stop_reason
        else:
            patched["stop_reason"] = ""
        patched_content = json.dumps(patched, indent=2)

    return {
        "messages": state["messages"] + [AIMessage(content=patched_content)],
        "criteria_text": criteria_text,
        "prior_critique_json": state.get("prior_critique_json"),
        "stop_history": history,
        "consecutive_no_new_evidence": no_new,
        "consecutive_tool_unavailable": prev_tool_unavailable,
        "last_researcher_json": last_researcher_json,
        "first_researcher_json": state.get("first_researcher_json") or last_researcher_json,
        "last_critique_json": patched_content,
        "claim_history": claim_hist,
        "researcher_round_count": 0,
        "critique_round_count": critique_round_count + 1,
    }

def down_should_continue(state: DownAgentState):
    last_message_content = state["messages"][-1].content if state.get("messages") else ""
    raw = (last_message_content or "").strip()
    _vprint(f"[should_continue] raw critique output: ...")

    # Only terminal stop reasons should end the loop here.
    # NO_NEW_EVIDENCE is treated as advisory so the workflow can continue
    # until approval or the recursion/iteration budget is exhausted.
    STOP_REASONS = {"APPROVED","REJECTED","TOOL_UNAVAILABLE","EXHAUSTED_NO_PROGRESS"}

    def _normalized_reason(value) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
        return None

    history = state.get("stop_history") or []
    if history:
        latest_reason = _normalized_reason(history[-1].get("stop_reason"))
        if latest_reason in STOP_REASONS:
            _vprint(f"-----Agent Decided to Stop (history stop_reason={latest_reason})-----")
            return END

    def _should_stop_from_json(obj: dict) -> bool:
        stop_reason = _normalized_reason(obj.get("stop_reason"))
        if stop_reason == "APPROVED":
            critique_payload = _extract_critique_payload(obj) if isinstance(obj, dict) else {}
            critique_decision = critique_payload.get("decision") if isinstance(critique_payload, dict) else None
            agreement_status = None
            if isinstance(critique_payload, dict):
                agreement_status = critique_payload.get("agreement_status")
            if not agreement_status and history:
                agreement_status = history[-1].get("agreement_status")
            if not _is_valid_approved_stop(stop_reason, critique_decision, agreement_status, critique_payload):
                return False
        if stop_reason in STOP_REASONS:
            _vprint(f"-----Agent Decided to Stop (stop_reason={stop_reason})-----")
            return True
        return False

    critique_json = None
    try:
        critique_json = json.loads(raw)
        if isinstance(critique_json, dict) and _should_stop_from_json(critique_json):
            return END
    except Exception:
        critique_json = None

    if critique_json is None:
        match = re.search(r"\{[\s\S]*?\}", raw)
        if match:
            try:
                critique_json = json.loads(match.group(0))
                if isinstance(critique_json, dict) and _should_stop_from_json(critique_json):
                    _vprint("-----Agent Decided to Stop (extracted JSON)-----")
                    return END
            except Exception:
                critique_json = None

    critique_round_count = int(state.get("critique_round_count", 0) or 0)
    if os.environ.get("DISABLE_CRITIQUE_FOLLOWUP", "False") == "True":
        _vprint("-----Critique follow-up disabled by ablation setting-----")
        return END

    max_followup_rounds = int(os.environ.get("MAX_CRITIQUE_FOLLOWUP_ROUNDS", "2"))
    if critique_round_count < max_followup_rounds and _critique_has_actionable_followup(critique_json):
        _vprint("-----Critique requested one final targeted researcher round-----")
        return "researcher"

    return END

# %% [markdown]
# ## 5. Full Workflow Definition & Execution
# 
# This final section combines the upper-stream, middle node, and down-stream components into a single, executable graph.
# 

# %%
# --- DEFINE THE FULL WORKFLOW (SINGLE GRAPH WRAPPING BATCH) --- #
class FullWorkflowState(TypedDict):
    # State for the upper-stream agent
    messages: List[HumanMessage | AIMessage]
    original_query: str
    search_session_dir: str
    iteration_count: int
    last_output: str | None
    
    # State to hold the inputs for the downstream batch
    downstream_states: List[dict]
    downstream_configs: List[dict]
    candidate_pool: List[str]
    processed_report_count: int
    candidate_source_file: Optional[str]
    selected_batch_file: Optional[str]
    remaining_candidate_count: int
    consumed_candidate_ids: List[str]
    target_confirmed_count: int
    middle_batch_size: int
    score_threshold: float
    
    # HITL Definition
    refined_definition: Optional[str]
    verification_query_template: Optional[str]
    
    # Refinement State
    refinement_messages: List[HumanMessage | AIMessage | SystemMessage]
    is_satisfied: bool
    
    # Final Reports from Downstream
    final_reports: Annotated[List[dict], operator.add]

def _is_confirmed_report(report: dict[str, Any]) -> bool:
    from release_policy import counts_as_confirmed

    return counts_as_confirmed(report)


def should_continue_after_query_generation(state: FullWorkflowState):
    if state.get("downstream_states"):
        return "downstream_batch"
    if int(state.get("remaining_candidate_count") or 0) > 0:
        return "query_generation"
    return END


def should_continue_after_downstream(state: FullWorkflowState):
    final_reports = state.get("final_reports", [])
    confirmed_count = sum(1 for report in final_reports if _is_confirmed_report(report))
    target_confirmed_count = int(state.get("target_confirmed_count") or 0)
    if target_confirmed_count > 0 and confirmed_count >= target_confirmed_count:
        return END
    if int(state.get("remaining_candidate_count") or 0) > 0:
        return "query_generation"
    return END

# Prompt for the refinement agent
REFINEMENT_PROMPT_PATH = PROMPTS_DIR / "refinement_agent.md"
REFINEMENT_PROMPT = REFINEMENT_PROMPT_PATH.read_text(encoding="utf-8")

refinement_model = ChatOpenRouter(
    model_name=_model_name_from_env("REFINEMENT_MODEL_NAME", "google/gemini-2.5-flash"),
    temperature=0.0,
)

def refinement_agent_node(state: FullWorkflowState):
    _vprint("\n----- Refinement Agent Node -----")
    
    # If we already have a final definition, just pass through (shouldn't happen if graph logic is correct)
    if state.get("is_satisfied"):
        return {}

    # Invoke the model
    messages = state["refinement_messages"]
    response = refinement_model.invoke(messages)
    content = response.content
    
    # Check if the model produced a final definition JSON
    final_def = None
    final_payload_text = None
    verification_query_template = None
    try:
        # Look for JSON block
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            data = json.loads(match.group(0))
            if "final_definition" in data:
                final_def = data["final_definition"]
                final_payload_text = json.dumps(data, ensure_ascii=False)
            raw_template = data.get("verification_query_template")
            if isinstance(raw_template, str) and raw_template.strip():
                verification_query_template = raw_template.strip()
    except Exception:
        pass
        
    # Fallback: Check for plain text "final definition" marker
    if not final_def:
        lower_content = content.lower()
        if "final_definition" in lower_content or "final definition" in lower_content:
            final_def = content

    if final_def:
        _vprint(f"\nRefinement Agent finalized definition:\n{final_def}")
        
        # Construct the refined input for the upper stream agent
        refined_input = build_upper_stream_request(state['original_query'], final_payload_text or final_def)
        
        return {
            "refinement_messages": messages + [AIMessage(content=content)],
            "refined_definition": final_payload_text or final_def,
            "verification_query_template": verification_query_template,
            "is_satisfied": True,
            "messages": [HumanMessage(content=refined_input)]
        }
    else:
        _vprint(f"\nRefinement Agent proposes/asks:\n{content}")
        return {
            "refinement_messages": messages + [AIMessage(content=content)],
            "is_satisfied": False
        }

def human_feedback_node(state: FullWorkflowState):
    _vprint("\n----- Waiting for Human Feedback -----")
    
    # Check if we are interactive
    import sys
    is_interactive = sys.stdin.isatty()
    
    # Interrupt execution to get user input if interactive
    if is_interactive:
        print("\n[Human Feedback Required]")
        user_input = ""
        while not user_input.strip():
            try:
                user_input = input("Please provide your feedback or confirmation: ")
            except EOFError:
                _vprint("\n[End of Input detected]")
                user_input = "exit"
                break
    else:
        print("\n[Batch Mode Detected] Auto-approving refinement.")
        user_input = build_definition_confirmation_payload()
    
    _vprint(f"\nUser provided: {user_input}")
    
    return {
        "refinement_messages": state["refinement_messages"] + [HumanMessage(content=user_input)]
    }

def should_continue_refinement(state: FullWorkflowState):
    if state.get("is_satisfied"):
        return "end"
    return "continue"

# --- DOWNSTREAM SUBGRAPH DEFINITION --- #
# This subgraph is used for parallel execution of downstream agents
down_workflow = StateGraph(DownAgentState)
down_workflow.add_node("researcher", researcher_node)
down_workflow.add_node("critique", critique_node)
down_workflow.set_entry_point("researcher")
down_workflow.add_conditional_edges("researcher", researcher_should_continue)
down_workflow.add_conditional_edges("critique", down_should_continue)
down_app = down_workflow.compile(checkpointer=downstream_memory)

def downstream_driver(state: DownAgentState, allow_ambiguity_followup: bool = True):
    """
    Driver node that executes the downstream agent workflow for a single query.
    This node is intended to be called via Send() in parallel.
    """
    structured_query = _ensure_structured_verification_task(state["original_query"])
    if structured_query != state.get("original_query"):
        state = dict(state)
        state["original_query"] = structured_query
        state["messages"] = [HumanMessage(content=structured_query)]

    query = state["original_query"]
    _vprint(f"\n>>> Starting Downstream Agent for: {query[:5]}...")
    
    # Generate a unique thread_id for this run to avoid collisions in the shared checkpointer
    thread_id = f"down_{hash(query)}_{random.randint(0, 9999)}"
    config = {"configurable": {"thread_id": thread_id}}
    
    # Ensure correct session dir is set for this thread
    session_dir = state.get("search_session_dir")
    if session_dir:
        FullTextJournalSearchTool.set_session_dir(session_dir)

    # Invoke the downstream app (which is a compiled graph)
    # We use the global down_app defined earlier
    token_stats = {"tokens": 0, "cost": 0.0}
    cb = None
    try:
        from langchain_community.callbacks import get_openai_callback
        with get_openai_callback() as cb:
            final_state = down_app.invoke(state, config=config)
        token_stats["tokens"] = cb.total_tokens
        token_stats["cost"] = round(cb.total_cost, 6)
        
        # Fallback tracking if callbacks return 0 (e2e_agent on Gemini via Litellm uses kwargs)
        if token_stats["tokens"] == 0:
            for msg in final_state.get("messages", []):
                if hasattr(msg, "response_metadata") and "token_usage" in msg.response_metadata:
                    usage = msg.response_metadata["token_usage"]
                    token_stats["tokens"] += usage.get("total_tokens", 0)
            if token_stats["tokens"] > 0:
                # Estimate Gemini Flash pricing: flat $0.15 per 1M tokens average for prompt/completion
                token_stats["cost"] = round(token_stats["tokens"] * 0.00000015, 6)

    except Exception as e:
        if cb is not None:
            token_stats["tokens"] = cb.total_tokens
            token_stats["cost"] = round(cb.total_cost, 6)
        from langgraph.errors import GraphRecursionError
        if isinstance(e, GraphRecursionError):
            log.warning(f"Downstream agent hit recursion limit (Timeout) for query '{query}'")
            return {"final_reports": [{
                "query": query,
                "claim": "Max Iteration Timeout",
                "researcher_claim": "Max Iteration Timeout",
                "final_adjudicated_claim": "Max Iteration Timeout",
                "explanation": "Agent execution timed out (maximum iterations reached)",
                "stop_reason": "TIMEOUT",
                "agreement_status": "unknown",
                "final_status": "runtime_timeout",
                "results_dir": state.get("search_session_dir"),
                "tokens_used": token_stats["tokens"],
                "cost_usd": token_stats["cost"]
            }]}
            
        log.error(f"Downstream agent failed for query '{query}': {e}")
        return {"final_reports": [{
            "query": query,
            "claim": "Error",
            "researcher_claim": "Error",
            "final_adjudicated_claim": "Error",
            "explanation": f"Agent execution failed: {e}",
            "stop_reason": "ERROR",
            "agreement_status": "unknown",
            "final_status": "runtime_error",
            "results_dir": state.get("search_session_dir"),
            "tokens_used": 0,
            "cost_usd": 0.0
        }]}
    
    # Extract report
    claim = determine_final_claim(final_state["messages"])
    explanation = determine_explanation(final_state["messages"])
    stop_reason = None
    stop_history = final_state.get("stop_history") or []
    if stop_history and isinstance(stop_history[-1], dict):
        candidate_reason = stop_history[-1].get("stop_reason")
        if isinstance(candidate_reason, str) and candidate_reason.strip():
            stop_reason = candidate_reason.strip()
    if not stop_reason:
        parsed_final_critique = _parse_json_object(final_state.get("last_critique_json"))
        if isinstance(parsed_final_critique, dict):
            candidate_reason = parsed_final_critique.get("stop_reason")
            if isinstance(candidate_reason, str) and candidate_reason.strip():
                stop_reason = candidate_reason.strip()
    if not stop_reason:
        stop_reason = "COMPLETED"

    last_researcher_json = final_state.get("last_researcher_json") or _last_researcher_json(final_state.get("messages", []))
    research_obj = _parse_json_object(last_researcher_json)
    first_researcher_json = final_state.get("first_researcher_json") or last_researcher_json
    first_researcher_obj = _parse_json_object(first_researcher_json)
    first_researcher_claim = ""
    if isinstance(first_researcher_obj, dict):
        verdict_statement = first_researcher_obj.get("verdict_statement")
        if isinstance(verdict_statement, dict):
            first_researcher_claim = str(verdict_statement.get("claim") or "").strip()
        if not first_researcher_claim:
            synthesis_obj = first_researcher_obj.get("synthesis")
            if isinstance(synthesis_obj, dict):
                first_researcher_claim = str(synthesis_obj.get("claim") or "").strip()
    first_researcher_claim = _normalize_claim_label(first_researcher_claim or "Insufficient Direct Evidence")
    first_researcher_evidence = _extract_researcher_evidence(first_researcher_obj)
    first_researcher_evidence = [
        item
        for item in first_researcher_evidence
        if str(item.get("source_type") or "").casefold() != "compound_database"
    ]
    confidence_score = None
    if isinstance(research_obj, dict):
        synthesis_obj = research_obj.get("synthesis")
        if isinstance(synthesis_obj, dict):
            confidence_score = synthesis_obj.get("confidence_score")
    evidence = _extract_researcher_evidence(research_obj)
    if not evidence and isinstance(last_researcher_json, str):
        evidence = _extract_ref_bullet_evidence(last_researcher_json)
    for item in evidence:
        if isinstance(item, dict) and not item.get("title"):
            inferred_title = _infer_title_from_snippet(item.get("snippet"))
            if inferred_title:
                item["title"] = inferred_title
    identity_records = []
    if isinstance(research_obj, dict) and isinstance(
        research_obj.get("identity_records"),
        list,
    ):
        identity_records.extend(
            item
            for item in research_obj["identity_records"]
            if isinstance(item, dict)
        )
    identity_records.extend(
        item
        for item in evidence
        if str(item.get("source_type") or "").casefold() == "compound_database"
    )
    evidence = [
        item
        for item in evidence
        if str(item.get("source_type") or "").casefold() != "compound_database"
    ]
    metadata_lookup = _load_doc_metadata(session_dir)
    if metadata_lookup and evidence:
        by_title = metadata_lookup.get("by_title", {}) if isinstance(metadata_lookup, dict) else {}
        by_pmid = metadata_lookup.get("by_pmid", {}) if isinstance(metadata_lookup, dict) else {}
        by_doi = metadata_lookup.get("by_doi", {}) if isinstance(metadata_lookup, dict) else {}
        for item in evidence:
            meta = None
            doi_val = item.get("doi") or ""
            pmid_val = item.get("pmid") or ""
            if doi_val:
                meta = by_doi.get(_clean_doi(doi_val))
            if not meta and pmid_val:
                meta = by_pmid.get(str(pmid_val))
            if not meta:
                title = item.get("title") or ""
                key = _normalize_title(title)
                meta = by_title.get(key)
            if not meta:
                continue
            if not item.get("doi") and meta.get("doi"):
                item["doi"] = _clean_doi(meta.get("doi") or "")
            if not item.get("pmid") and meta.get("pmid"):
                item["pmid"] = str(meta.get("pmid") or "")
            if _is_unknown_year(item.get("year")) and meta.get("year"):
                item["year"] = meta.get("year") or ""
            if not item.get("title") and meta.get("title"):
                item["title"] = meta.get("title") or ""
            if not item.get("doi"):
                doi_meta = _resolve_doi_via_eupmc(item.get("title"))
                if doi_meta and doi_meta.get("doi"):
                    item["doi"] = doi_meta.get("doi") or ""
                if _is_unknown_year(item.get("year")) and doi_meta and doi_meta.get("year"):
                    item["year"] = doi_meta.get("year") or ""
        for item in evidence:
            if item.get("pmid") == "":
                item.pop("pmid", None)

    raw_evidence_count = len(evidence) if isinstance(evidence, list) else 0
    evidence = _merge_evidence_items(evidence)

    critique_obj = _parse_json_object(final_state.get("last_critique_json"))
    critique_payload = _extract_critique_payload(critique_obj)
    critique_decision = critique_payload.get("decision")
    critique_claim = critique_payload.get("critique_claim")
    researcher_claim_supported = critique_payload.get("researcher_claim_supported")
    rubric = critique_payload.get("rubric")
    latest_agreement_status = "unknown"
    if stop_history and isinstance(stop_history[-1], dict):
        candidate_agreement = stop_history[-1].get("agreement_status")
        if isinstance(candidate_agreement, str) and candidate_agreement.strip():
            latest_agreement_status = candidate_agreement.strip().lower()
    if latest_agreement_status == "unknown":
        latest_agreement_status = (
            "agree"
            if critique_claim and _normalize_claim_label(critique_claim) == _normalize_claim_label(claim)
            else ("disagree" if critique_claim else "unknown")
        )

    final_adjudicated_claim, accepted, final_status = _derive_final_adjudicated_claim(
        claim,
        critique_decision,
        stop_reason,
        latest_agreement_status,
        critique_claim,
        critique_payload,
        extract_rubric_items(query),
    )
    final_adjudicated_claim = _derive_specific_negative_claim(final_adjudicated_claim, critique_payload, evidence)
    claim = _derive_specific_negative_claim(claim, critique_payload, evidence)
    key_points = []
    if isinstance(rubric, dict):
        criteria = rubric.get("criteria")
        if isinstance(criteria, list):
            # Preserve evidence_ids for downstream release review.
            key_points = [str(item.get("name") or "").strip() for item in criteria if isinstance(item, dict) and str(item.get("name") or "").strip()]
    
    report = {
        "query": query,
        "claim": final_adjudicated_claim,
        "researcher_claim": claim,
        "first_researcher_claim": first_researcher_claim,
        "first_researcher_json": first_researcher_json or "",
        "first_researcher_evidence": first_researcher_evidence,
        "final_adjudicated_claim": final_adjudicated_claim,
        "accepted": accepted,
        "explanation": explanation,
        "stop_reason": stop_reason,
        "critique_decision": critique_decision,
        "critique_claim": critique_claim,
        "researcher_claim_supported": researcher_claim_supported,
        "agreement_status": latest_agreement_status,
        "final_status": final_status,
        "key_points": key_points,
        "rubric": rubric,
        "criterion_assessment": critique_payload,
        "evidence": evidence,
        "identity_records": identity_records,
        "results_dir": state.get("search_session_dir"),
        "papers_analyzed": len(evidence) if isinstance(evidence, list) else 0,
        "raw_evidence_items": raw_evidence_count,
        "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
        "evidence_depth": len(evidence) if isinstance(evidence, list) else 0,
        "supporting_source_count": len({str(item.get("id") or "").strip() for item in evidence if isinstance(item, dict) and str(item.get("id") or "").strip()}) if isinstance(evidence, list) else 0,
        "stop_history": stop_history,
        "claim_history": final_state.get("claim_history") or [],
        "iteration_count": len(stop_history),
        "confidence_score": confidence_score,
        "tokens_used": token_stats["tokens"],
        "cost_usd": token_stats["cost"],
        "discovered_compounds": []
    }

    if final_adjudicated_claim in {"Insufficient Direct Evidence", "Indirect or Class-Level Only"}:
        target_entity = _extract_target_entity_name(query)
        ambiguity_candidates, ambiguity_status = _extract_ambiguity_candidates(target_entity, critique_obj)
        if ambiguity_candidates:
            report["ambiguity_candidate"] = ambiguity_candidates[0]
            report["ambiguity_candidates"] = ambiguity_candidates
            report["ambiguity_status"] = ambiguity_status

    from decision_contract import finalize, registry_from_session
    report = finalize(report, extract_rubric_items(query),
                      registry_from_session(session_dir, report["evidence"]))
    report["discovered_compounds"] = _collect_discovered_compounds(report)

    if os.environ.get("DISABLE_DOWNSTREAM_CSV", "").lower() not in ("1", "true", "yes"):
        base_dir = Path(__file__).resolve().parents[1]
        _write_csv_outputs(report, state.get("search_session_dir"), str(base_dir / "results"))
    if session_dir:
        try:
            rubric_path = Path(session_dir) / "rubric_eval.json"
            with rubric_path.open("w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
        except Exception as e:
            _vprint(f"[WARN] Failed to write rubric_eval.json: {e}")
    return {"final_reports": [report]}


# -------------------- helper for multiprocessing --------------------
def safe_downstream_invoke(state_input):
    """
    Wrapper to invoke downstream_driver safely in a subprocess.
    Must be top-level to be picklable.
    """
    try:
        # We call downstream_driver directly to avoid pickling RunnableLambda closures if any.
        # downstream_driver is defined in this module.
        return downstream_driver(state_input)
    except Exception as e:
        # We can't use _vprint here effectively if it's not set up for MP logging,
        # but print usually works in spawn.
        print(f"Error in downstream agent subprocess: {e}")
        return {"final_reports": []}

def downstream_batch_node(state: FullWorkflowState, config: RunnableConfig) -> dict:
    """
    Executes all downstream queries in parallel using model.batch().
    This replaces the Send() API for a cleaner, high-throughput implementation.
    """
    inputs = state.get("downstream_states", [])
    if not inputs:
        _vprint("No downstream states to process.")
        return {"final_reports": []}

    _vprint(f"\n----- Batch Executing {len(inputs)} Downstream Agents -----")
    
    # Get concurrency from config, default to 4
    # Note: Config comes from the graph invoker
    max_concurrency = config.get("configurable", {}).get("max_concurrency", 4)
    # Also check top-level keys just in case
    if "max_concurrency" in config:
        max_concurrency = config["max_concurrency"]

    _vprint(f"Parallelism: {max_concurrency}")

    # Create a runnable from the driver (Optional for ProcessPool, we use safe wrapper)
    # driver_runnable = RunnableLambda(downstream_driver)
    
    # Execute batch with dynamic queue using ProcessPoolExecutor (Bypasses Global Lock)
    # We pass the inputs (list of states) and the config for parallelism
    
    all_reports = []
    total = len(inputs)
    processed = 0
    
    # Try to set start method for PyTorch safety
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass

    # Use ProcessPoolExecutor
    # Note: We submit the TOP-LEVEL function 'safe_downstream_invoke'
    with ProcessPoolExecutor(max_workers=max_concurrency) as executor:
        future_to_input = {executor.submit(safe_downstream_invoke, inp): inp for inp in inputs}
        
        for future in as_completed(future_to_input):
            try:
                res = future.result()
                processed += 1
                if res and "final_reports" in res:
                    all_reports.extend(res["final_reports"])
                    # Optional: Print progress
                    _vprint(f"Downstream Progress: {processed}/{total} completed.")
            except Exception as e:
                _vprint(f"CRITICAL: Downstream task failed without capture: {e}")

    return {"final_reports": all_reports}

def route_to_downstream(state: FullWorkflowState):
    """
    Conditional edge function to map downstream states to the downstream driver.
    """
    downstream_states = state.get("downstream_states", [])
    if not downstream_states:
        return []
    
    return [Send("downstream_driver", s) for s in downstream_states]

# Combine the upper and middle nodes into a single graph
full_workflow = StateGraph(FullWorkflowState)

# Add nodes
full_workflow.add_node("refinement_agent", refinement_agent_node)
full_workflow.add_node("human_feedback", human_feedback_node)
full_workflow.add_node("upper_stream_agent", upper_stream_agent_node)
full_workflow.add_node("query_generation", query_generation_node)
full_workflow.add_node("downstream_batch", downstream_batch_node) # NEW BATCH NODE

# Set entry point
full_workflow.set_entry_point("refinement_agent")

# Edges for refinement
full_workflow.add_conditional_edges(
    "refinement_agent",
    should_continue_refinement,
    {
        "continue": "human_feedback",
        "end": "upper_stream_agent"
    }
)
full_workflow.add_edge("human_feedback", "refinement_agent")

# Edges for upper stream
full_workflow.add_conditional_edges(
    "upper_stream_agent",
    upper_should_continue,
    {
        "agent": "upper_stream_agent",
        END: "query_generation",
    },
)

# Edge for query generation -> downstream
full_workflow.add_conditional_edges(
    "query_generation",
    should_continue_after_query_generation,
    {
        "downstream_batch": "downstream_batch",
        "query_generation": "query_generation",
        END: END,
    },
)
full_workflow.add_conditional_edges(
    "downstream_batch",
    should_continue_after_downstream,
    {
        "query_generation": "query_generation",
        END: END,
    },
)

# Compile the combined app with the upper-stream's checkpointer
full_app = full_workflow.compile(checkpointer=upper_stream_memory)

# --- RUN THE PIPELINE --- #
def run_full_pipeline(
    original_query: str,
    max_concurrency: int = 4,
    target_confirmed_count: int = 100,
    middle_batch_size: int = 100,
    score_threshold: float = 0.7,
):
    """Orchestrates the entire agent pipeline: Upper -> Middle -> Downstream.

    Now executed as a single LangGraph workflow using Send() for parallel downstream execution.
    """
    
    # === 1. SETUP AND RUN THE COMBINED WORKFLOW ===
    _vprint(f"\n{'='*60}\n🚀 STARTING FULL WORKFLOW\n{'='*60}")
    
    run_timestamp = time.strftime("%Y%m%d_%H%M%S")
    os.environ["LANGCHAIN_PROJECT"] = f"e2e Agent Run - {run_timestamp}"
    session_dir = Path(BASE_RESULTS_DIR) / f"e2e_run_{run_timestamp}"
    session_dir.mkdir(exist_ok=True, parents=True)
    
    # Create literature_searching subfolder for upper stream
    literature_dir = session_dir / "literature_searching"
    literature_dir.mkdir(exist_ok=True)
    
    _vprint(f"📁 Full session directory: {session_dir}")
    _vprint(f"📁 Literature searching directory: {literature_dir}")

    # Each run needs a unique thread_id for the checkpointer
    thread_id = f"e2e_run_{run_timestamp}"
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "search_session_dir": str(literature_dir)},
        "recursion_limit": MAX_ITERATIONS_E2E,
        "max_concurrency": max_concurrency, # Explicitly enable parallel execution
    }

    initial_state: FullWorkflowState = {
        "messages": [HumanMessage(content=original_query)],
        "original_query": original_query,
        "search_session_dir": str(literature_dir),
        "iteration_count": 0,
        "last_output": None,
        "downstream_states": [],
        "downstream_configs": [],
        "candidate_pool": [],
        "processed_report_count": 0,
        "candidate_source_file": None,
        "selected_batch_file": None,
        "remaining_candidate_count": 0,
        "consumed_candidate_ids": [],
        "target_confirmed_count": target_confirmed_count,
        "middle_batch_size": middle_batch_size,
        "score_threshold": score_threshold,
        "refined_definition": None,
        "verification_query_template": None,
        "refinement_messages": [
            SystemMessage(content=REFINEMENT_PROMPT),
            HumanMessage(content=build_refinement_request(original_query))
        ],
        "is_satisfied": False,
        "final_reports": []
    }
    
    _vprint("\n--- Executing Unified Workflow ---")
    # This invocation runs everything: Refinement -> Upper -> Query Gen -> Downstream (Parallel)
    final_state = full_app.invoke(initial_state, config=config)
    
    # === 2. PROCESS AND DISPLAY FINAL RESULTS ===
    _vprint(f"\n{'='*60}\n🏁 END-TO-END WORKFLOW COMPLETE 🏁\n{'='*60}")
    
    all_results_data = final_state.get("final_reports", [])
    
    # If no reports, check if we halted early
    if not all_results_data:
        log.warning("Workflow completed but no final reports were produced.")
        # Check if downstream states were generated
        if not final_state.get("downstream_states"):
             log.warning("No downstream queries were generated.")

    print("\n--- Final Verified Claims ---")
    print(json.dumps(all_results_data, indent=2))
    
    summary_path = session_dir / "end_to_end_summary.json"
    with open(summary_path, "w") as f:
        json.dump(all_results_data, f, indent=2)
    print(f"\n📄 Full summary saved to: {summary_path}")
    
    return {
        "session_directory": str(session_dir),
        "queries_generated": len(final_state.get("candidate_pool", [])),
        "results": all_results_data,
    }

print("✓ Full Workflow Defined (Upper → Query Generator → Downstream, batch downstream)")

# %%
# === RUN THE COMPLETE END-TO-END PIPELINE ===
# This cell executes the full workflow: Upper-Stream → Query Generation → Down-Stream

# initial_user_query = "form a database of hair-related chemicals"

# try:
#     # You can control the number of parallel downstream agents by changing the max_concurrency value
#     pipeline_result = run_full_pipeline(initial_user_query)
#     print("\n" + "="*60)
#     print("PIPELINE SUMMARY")
#     print("="*60)
#     print(f"Session Directory: {pipeline_result.get('session_directory')}")
#     print(f"Queries Generated: {pipeline_result.get('queries_generated')}")
#     print(f"Results: {len(pipeline_result.get('results', []))} compounds verified")
# finally:
#     wait_for_all_tracers()
#     print("\n✓ All traces flushed to LangSmith")

# %%
# === RUN THE COMPLETE END-TO-END PIPELINE ===
# This cell executes the full workflow: Upper-Stream → Query Generation → Down-Stream

if __name__ == "__main__":
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass
        
    initial_user_query = "Form a database of all experimentally confirmed disinfection byproducts (DBPs)"

    try:
        # You can control the number of parallel downstream agents by changing the max_concurrency value
        pipeline_result = run_full_pipeline(initial_user_query)
        print("\n" + "="*60)
        print("PIPELINE SUMMARY")
        print("="*60)
        print(f"Session Directory: {pipeline_result.get('session_directory')}")
        print(f"Queries Generated: {pipeline_result.get('queries_generated')}")
        print(f"Results: {len(pipeline_result.get('results', []))} compounds verified")
    finally:
        wait_for_all_tracers()
        print("\n✓ All traces flushed to LangSmith")
