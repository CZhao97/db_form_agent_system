# -------------------- stdlib --------------------
from pathlib import Path
import re, logging, warnings, sqlite3, os, time, random, pickle, requests
import json
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
# --- GLOBAL GPU DISTRIBUTION (Must happen before tool imports) ---
import torch
import multiprocessing as mp
try:
    # Only restrict GPU for Worker processes, NOT the MainProcess
    # The MainProcess must see all GPUs to spawn children on them.
    # Spawned workers will have names like "SpawnPoolWorker-1"
    cur_proc = mp.current_process().name
    if cur_proc != 'MainProcess' and torch.cuda.is_available():
        n_gpus = torch.cuda.device_count()
        if n_gpus > 1:
            # Simple round-robin using PID
            pid = os.getpid()
            gpu_idx = pid % n_gpus
            # We must use set_device because is_available() already initialized the context
            torch.cuda.set_device(gpu_idx)
            # We also set env var for good measure (though likely too late for this process, helpful for subprocesses)
            os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_idx)
            print(f"[Multi-GPU] Worker {cur_proc} (PID {pid}) assigned to Physical GPU {gpu_idx}")
except Exception as e:
    print(f"[Multi-GPU] Failed to set device: {e}")
# ---------------------------------------------------------------

import sys
import os
# Add the code directory to the path relative to this script
sys.path.append(os.path.join(os.path.dirname(__file__), '../code'))
from chemical_ner_tool import ChemicalNerTool
from searching_tool import FullTextJournalSearchTool
from compound_tool import CompoundDatabaseTool
from fulltext_vector_tools import FullTextIndexTool, FullTextQueryTool
from ner_results_viewer import load_ner_results, ner_results_to_dataframe

# -------------------- logging & environment --------------------
logging.basicConfig(level=logging.WARNING, format='%(levelname)s | %(name)s | %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)
log = logging.getLogger("end_to_end_workflow")
load_dotenv()

os.environ["LANGCHAIN_TRACING_V2"] = os.getenv("LANGCHAIN_TRACING_V2", "true")
os.environ["LANGCHAIN_CALLBACKS_BACKGROUND"] = "false"

# -------------------- constants --------------------
MAX_ITERATIONS_UPPER = 50
MAX_ITERATIONS_DOWN = 30
MAX_ITERATIONS_E2E = 100
BASE_RESULTS_DIR = "/home/chen/GNPS_SIM/agent/db_form_agent_system/searching_results"
MIN_DATE = "1970"
MAX_DATE = "2025"
SEARCH_LIMIT = 2000
TARGET_PAPERS = 2000

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

# --- TOOLS & MODEL --- #
upper_stream_model = ChatOpenRouter(model_name="google/gemini-2.5-flash", temperature=0.0)
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
        # Enable offline DB for deduplication and local retrieval
        offline_index_path="/data/chen/GNPS_SIM/pmc_lancedb_index",
        offline_doc_dir="/home/chen/pubmed_corpus/pmc_extracted_text"
    ), ChemicalNerTool()]

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
    
    # 1. Get the NER results file from the upper-stream agent's final message
    # 1. Get the NER results file from the upper-stream agent's final message
    # Use the robust extraction helper (which handles regex fallback)
    output_data = extract_final_output(state['messages'])
    ner_results_file = output_data.get("results_file")

    if not ner_results_file or not Path(ner_results_file).exists():
        log.error(f"NER results file not found or invalid: {ner_results_file}")
        # Only error out if we truly can't find it. 
        # Sometimes the agent output might just be text confirmation without JSON if something went wrong upstream.
        return {"downstream_states": [], "downstream_configs": []}
        
    _vprint(f"✅ Upper-stream complete. NER results at: {ner_results_file}")

    # 2. Load NER results and extract chemical name clusters (list of lists)
    ner_data = load_ner_results(ner_results_file)

    # If merged_output is empty (due to offline optimization) but per_file_results exists,
    # aggregate them on-the-fly so the agent can see the chemicals.
    if not ner_data.get("merged_output") and ner_data.get("per_file_results"):
        _vprint("Merged output missing. Aggregating per-file results for query generation...")
        aggregated_output = {}
        for file_entry in ner_data["per_file_results"]:
            entities = file_entry.get("entities", {})
            for kb_id, details in entities.items():
                if kb_id not in aggregated_output:
                    aggregated_output[kb_id] = {"mentions": [], "synonyms": details.get("synonyms", [])}
                
                # Extract mentions from the per-file structure
                # In per_file_results, mentions are typically a list of strings: ["Mention (Context...)", ...]
                mentions = details.get("mentions", [])
                aggregated_output[kb_id]["mentions"].extend(mentions)
        
        # Reformat to match ner_results_to_dataframe expectation:
        # { kb_id: { "mentions": [{"text": ["m1", "m2"]}] } }
        final_aggregated = {}
        for kb_id, data in aggregated_output.items():
            unique_mentions = sorted(list(set(data["mentions"])))
            final_aggregated[kb_id] = {
                "synonyms": data["synonyms"],
                "mentions": [{"text": unique_mentions}]
            }
        ner_data["merged_output"] = final_aggregated

    df = ner_results_to_dataframe(ner_data, include_synonyms=False)
    if df.empty:
        log.warning("No chemical entities found in NER results.")
        return {"downstream_states": [], "downstream_configs": []}

    # Randomly choose chemicals instead of top ranked
    sample_size = min(1000, len(df))
    top_chemicals = df.sample(n=sample_size)
    chemical_names = []
    for entry in top_chemicals['unique_mentions']:
        if isinstance(entry, list):
            chemical_names.append(entry)
        elif isinstance(entry, str):
            chemical_names.append([name.strip() for name in entry.split(' ||| ') if name.strip()])

    if not chemical_names:
        log.warning("No chemical name clusters to generate queries for.")
        return {"downstream_states": [], "downstream_configs": []}

    _vprint("Selected chemical clusters:")
    for cluster in chemical_names:
        if cluster:
            _vprint(f"  - {cluster}")

    # 3. Use LLM to generate queries based on the clusters
    original_query = state['original_query']
    refined_definition = state.get("refined_definition")
    
    input_data = {
        "original_query": original_query,
        "chemical_names": chemical_names
    }
    
    if refined_definition:
        input_data["refined_definition"] = refined_definition
        input_data["instruction"] = (
            "For each chemical, generate a detailed query that explicitly includes the 'refined_definition'. "
            "The query MUST follow this format:\n"
            "\"According to the following definition, decide whether [Chemical Name] is a [Target Entity]:\n"
            f"{refined_definition}\n\n"
            "Based on the peer-reviewed literature, is [Chemical Name] a [Target Entity] under this definition?\""
        )

    input_content = json.dumps(input_data)
    
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
        downstream_queries = output_json.get("queries", [])
    except (json.JSONDecodeError, AttributeError) as e:
        log.error(f"Failed to parse query generator LLM output: {e}")
        return {"downstream_states": [], "downstream_configs": []}

    if not downstream_queries:
        log.warning("Middle component generated no queries. Halting workflow.")
        return {"downstream_states": [], "downstream_configs": []}

    _vprint(f"\n🔍 Generated {len(downstream_queries)} queries for downstream agents")

    # 4. Prepare the initial states for the downstream batch
    all_init_states = []
    all_configs = []
    session_dir = Path(state['search_session_dir'])
    
    # If the session dir is the literature_searching subfolder, go up one level for downstream folders
    if session_dir.name == "literature_searching":
        session_dir = session_dir.parent
    
    for i, query in enumerate(downstream_queries):
        down_stream_session_dir = session_dir / f"downstream_{i}_{re.sub('[^A-Za-z0-9]+', '_', query)[:50]}"
        down_stream_session_dir.mkdir(exist_ok=True)
        
        init_state = {
            'messages': [HumanMessage(content=query)],
            'original_query': query,
            'search_session_dir': str(down_stream_session_dir),
            'stop_history': [],
            'last_researcher_json': None,
            'last_critique_json': None,
            'claim_history': [],
            'confidence_history': [],
            'consecutive_no_new_evidence': 0,
            'consecutive_tool_unavailable': 0,
        }
        all_init_states.append(init_state)
        all_configs.append({'recursion_limit': MAX_ITERATIONS_DOWN})

    return {"downstream_states": all_init_states, "downstream_configs": all_configs}

print("✓ Middle Component (Query Generation Node) Defined")


# %% [markdown]
# ## 4. Down-Stream Agent Definition
# 
# This section defines the second agent, which takes specific chemical queries and verifies them.

# %%
# --- STATE --- #
class StateHistory(TypedDict):
    claim: str
    confidence_score: float
    supporting_sources: List[str]
    tool_name: str | None
    stop_reason: str | None

class DownAgentState(TypedDict):
    messages: List[HumanMessage | AIMessage]
    original_query: str
    search_session_dir: str
    stop_history: List[StateHistory]
    consecutive_no_new_evidence: int
    consecutive_tool_unavailable: int
    last_researcher_json: str | None
    last_critique_json: str | None
    claim_history: List[str]
    confidence_history: List[float]

# --- PROMPTS --- #
LITERATURE_PROMPT_PATH = PROMPTS_DIR / "literature_agent.md"
CRITIQUE_PROMPT_PATH = PROMPTS_DIR / "critique_agent.md"
LITERATURE_AGENT_PROMPT = SystemMessage(content=LITERATURE_PROMPT_PATH.read_text(encoding="utf-8"))
CRITIQUE_AGENT_PROMPT = SystemMessage(content=CRITIQUE_PROMPT_PATH.read_text(encoding="utf-8"))

# --- MODELS & TOOLS --- #
research_model = ChatOpenRouter(model_name="google/gemini-2.5-flash", temperature=0.0)
evaluator_model = ChatOpenRouter(model_name="openai/gpt-4o-mini", temperature=0.0)
down_stream_tools = [
    CompoundDatabaseTool(),
    FullTextJournalSearchTool(
        results_base_dir=BASE_RESULTS_DIR,
        include_pubmed=True,
        include_preprints=False,
        include_s2=True,
        include_arxiv=True,
        include_medrxiv=True,
        include_eupmc=True,
        use_pubmed_free_fulltext_bias=True,
        max_parallel_downloads=6,
        max_parallel_docling=6,
        min_date=MIN_DATE,  # Date range filter
        max_date=MAX_DATE,  # Date range filter
        # Enable offline DB for deduplication and local retrieval in downstream too
        offline_index_path="/data/chen/GNPS_SIM/pmc_lancedb_index",
        offline_doc_dir="/home/chen/pubmed_corpus/pmc_extracted_text",
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
def _last_researcher_json(messages):
    if not messages:
        return ""
    for msg in reversed(messages):
        content = getattr(msg, "content", "") or ""
        if '"synthesis"' in content:
            return content
    return ""

def determine_final_claim(messages):
    blob = _last_researcher_json(messages)
    if not blob:
        return "Unclear"
    try:
        obj = json.loads(blob)
        syn = obj.get("synthesis", {}) if isinstance(obj, dict) else {}
        claim_raw = syn.get("claim")
        if isinstance(claim_raw, str) and claim_raw.strip():
            return claim_raw.strip()
    except Exception:
        pass
    m = re.search(r'"claim"\s*:\s*"([^"]+)"', blob)
    if m:
        candidate = m.group(1).strip()
        if candidate:
            return candidate
    return "Unclear"

def _safe_float(x):
    try:
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            return float(x.replace("–", "-").strip())
    except Exception:
        return None

def determine_confidence_score(messages):
    blob = _last_researcher_json(messages)
    if not blob:
        return 0.0
    try:
        obj = json.loads(blob)
        syn = obj.get("synthesis", {}) if isinstance(obj, dict) else {}
        score = syn.get("confidence_score")
        return _safe_float(score) or 0.0
    except Exception:
        pass
    m = re.search(r'"confidence_score"\s*:\s*([0-9.]+)', blob)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    return 0.0

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

# -------------------- nodes --------------------
def researcher_node(state: DownAgentState, config: RunnableConfig):
    _vprint("-----Researcher Node Invoked-----")

    crit_json = state.get("last_critique_json")
    prev_research_json = state.get("last_researcher_json") or _last_researcher_json(state.get("messages", []))

    if crit_json and prev_research_json:
        next_query_val = None
        follow_up_str = ""
        try:
            crit_obj = json.loads(crit_json) if isinstance(crit_json, str) else (crit_json or {})
            critique_section = crit_obj.get("critique", {})
            if not isinstance(critique_section, dict):
                critique_section = {}
            decision = critique_section.get("decision", "")
            if isinstance(decision, str) and decision.lower() == "clarify":
                next_query_val = critique_section.get("next_query")
            if next_query_val:
                if isinstance(next_query_val, list):
                    query_str = "\n".join(str(item) for item in next_query_val if item)
                elif isinstance(next_query_val, str):
                    query_str = next_query_val.strip()
                else:
                    query_str = ""
                if query_str:
                    follow_up_str = f"\nReviewer follow-up request:\n{query_str}\n\n"
        except Exception as e:
            _vprint(f"[WARN] Error parsing critique JSON: {e}")

        merged = (
            "Previous researcher output:\n"
            f"{prev_research_json}\n\n"
            "Reviewer critique JSON:\n"
            f"{crit_json}\n\n"
            + follow_up_str
        )
        input_messages = [HumanMessage(content=merged)]
    else:
        input_messages = state["messages"]

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

    # ---- Seed ContextVar for all tools (authoritative path propagation)
    try:
        FullTextJournalSearchTool.set_session_dir(session_dir)
        FullTextIndexTool.set_session_dir(session_dir)
        FullTextQueryTool.set_session_dir(session_dir)
    except Exception:
        pass

    result = researcher_agent_executor.invoke({"messages": input_messages}, config=tool_config)

    ai_content = ""
    if 'messages' in result and isinstance(result['messages'], list) and result['messages']:
        ai_content = result['messages'][-1].content
    else:
        _vprint("[ERROR] Agent executor did not return expected messages list.")
        ai_content = (
            '{"synthesis": {"claim": "Unclear", "explanation": "Agent execution failed internally. '
            'No message was returned.", "confidence_score": 0.0, "limitations": "Agent internal error."}, '
            '"traceability": {}, "next_actions": {}}'
        )

    new_ai_message = AIMessage(content=ai_content)
    all_messages = state["messages"] + [new_ai_message]

    return {
        "messages": all_messages,
        "last_researcher_json": _last_researcher_json(all_messages),
        "last_critique_json": None,
    }

def critique_node(state: DownAgentState, config: RunnableConfig):
    _vprint("-----Critique Node Invoked-----")

    last_researcher_json = _last_researcher_json(state.get("messages", [])) or ""
    if not last_researcher_json:
        last_researcher_json = (state["messages"][-1].content if state.get("messages") else "").strip()

    critique_input = f"Researcher output JSON:\n{last_researcher_json}"

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
    raw = (critique_content or "").strip()

    parsed: dict | None = None
    try:
        candidate = json.loads(raw)
        if isinstance(candidate, dict):
            parsed = candidate
    except Exception:
        pass
    if parsed is None:
        match = re.search(r"\{[\s\S]*?\}", raw)
        if match:
            try:
                candidate = json.loads(match.group(0))
                if isinstance(candidate, dict):
                    parsed = candidate
            except Exception:
                parsed = None

    stop_reason = None
    supporting_sources: List[str] = []
    tool_name: str | None = None

    if parsed:
        candidate_reason = parsed.get("stop_reason")
        if isinstance(candidate_reason, str) and candidate_reason.strip():
            stop_reason = candidate_reason.strip().upper()
        sources = parsed.get("supporting_sources")
        if isinstance(sources, list):
            supporting_sources = [str(item) for item in sources]
        candidate_tool = parsed.get("tool_name")
        if isinstance(candidate_tool, str) and candidate_tool.strip():
            tool_name = candidate_tool.strip()

    def _extract_claim_and_confidence(messages):
        blob = _last_researcher_json(messages)
        claim = "Unclear"
        confidence = 0.0
        if not blob:
            return claim, confidence
        try:
            obj = json.loads(blob)
            synthesis = obj.get("synthesis", {}) if isinstance(obj, dict) else {}
            claim = (synthesis.get("claim") or "").strip() if isinstance(synthesis, dict) else ""
            candidate_conf = _safe_float(synthesis.get("confidence_score")) if isinstance(synthesis, dict) else None
            if candidate_conf is not None:
                confidence = max(0.0, min(1.0, candidate_conf))
        except Exception:
            pass
        if not claim:
            match_claim = re.search(r'"claim"\s*:\s*"([^"]+)"', blob)
            if match_claim:
                claim = match_claim.group(1).strip()
        if confidence == 0.0:
            match_conf = re.search(r'"confidence_score"\s*:\s*("?)([0-9]*\.?[0-9]+)\1', blob)
            if match_conf:
                try:
                    cand = float(match_conf.group(2))
                    confidence = max(0.0, min(1.0, cand))
                except Exception:
                    pass
        return claim or "Unclear", confidence

    claim, confidence = _extract_claim_and_confidence(state.get("messages", []))

    history = copy.deepcopy(state.get("stop_history", []))
    history.append({
        "claim": claim,
        "confidence_score": confidence,
        "supporting_sources": supporting_sources,
        "tool_name": tool_name,
        "stop_reason": stop_reason,
    })

    prev_no_new = state.get("consecutive_no_new_evidence", 0)
    prev_tool_unavailable = state.get("consecutive_tool_unavailable", 0)
    no_new = prev_no_new

    claim_hist = list(state.get("claim_history", []))
    conf_hist = list(state.get("confidence_history", []))
    claim_hist.append(claim if isinstance(claim, str) else "Unclear")
    conf_hist.append(float(confidence) if confidence is not None else 0.0)

    STABLE_THRESHOLD = 3
    CONFIDENCE_EPSILON = 0.001
    if len(claim_hist) >= STABLE_THRESHOLD and len(conf_hist) >= STABLE_THRESHOLD:
        last_n_claims = claim_hist[-STABLE_THRESHOLD:]
        last_n_confs = conf_hist[-STABLE_THRESHOLD:]
        normalized_claims = [c.strip().lower() if isinstance(c, str) else "" for c in last_n_claims]
        all_same_claim = len(set(normalized_claims)) == 1
        conf_range = max(last_n_confs) - min(last_n_confs)
        all_same_conf = conf_range <= CONFIDENCE_EPSILON
        if all_same_claim and all_same_conf and not stop_reason:
            stop_reason = "CONSECUTIVE_SAME_RESULT"
            _vprint(f"[critique_node] Detected {STABLE_THRESHOLD} consecutive identical results: {last_n_claims[-1]} @ {last_n_confs[-1]:.3f}")
            if history:
                history[-1]["stop_reason"] = stop_reason

    _vprint(f"[critique_node] stop_reason={stop_reason}")

    patched_content = critique_content
    if parsed is not None:
        patched = dict(parsed)
        if stop_reason:
            patched["stop_reason"] = stop_reason
        patched_content = json.dumps(patched, indent=2)

    return {
        "messages": state["messages"] + [AIMessage(content=patched_content)],
        "stop_history": history,
        "consecutive_no_new_evidence": no_new,
        "consecutive_tool_unavailable": prev_tool_unavailable,
        "last_researcher_json": last_researcher_json,
        "last_critique_json": patched_content,
        "claim_history": claim_hist,
        "confidence_history": conf_hist,
    }

def down_should_continue(state: DownAgentState):
    last_message_content = state["messages"][-1].content if state.get("messages") else ""
    raw = (last_message_content or "").strip()
    _vprint(f"[should_continue] raw critique output: ...")

    STOP_REASONS = {"APPROVED","NO_NEW_EVIDENCE","TOOL_UNAVAILABLE","CONSECUTIVE_SAME_RESULT"}

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
        if stop_reason in STOP_REASONS:
            _vprint(f"-----Agent Decided to Stop (stop_reason={stop_reason})-----")
            return True
        decision = obj.get("decision")
        if isinstance(decision, str) and decision.lower() == "approve":
            _vprint("-----Agent Decided to Stop (legacy decision=approve)-----")
            return True
        try:
            score = float(obj.get("agreement_score", 0.0))
            if score > 0.75:
                _vprint(f"-----Agent Decided to Stop (legacy agreement_score={score:.2f} > 0.75)-----")
                return True
        except Exception:
            pass
        return False

    try:
        critique_json = json.loads(raw)
        if isinstance(critique_json, dict) and _should_stop_from_json(critique_json):
            return END
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*?\}", raw)
    if match:
        try:
            critique_json = json.loads(match.group(0))
            if isinstance(critique_json, dict) and _should_stop_from_json(critique_json):
                _vprint("-----Agent Decided to Stop (extracted JSON)-----")
                return END
        except Exception:
            pass

    low = raw.lower()
    if any(token in low for token in ["approve", "approved"]):
        _vprint("-----Agent Decided to Stop (text match)-----")
        return END

    return "researcher"

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
    
    # HITL Definition
    refined_definition: Optional[str]
    
    # Refinement State
    refinement_messages: List[HumanMessage | AIMessage | SystemMessage]
    is_satisfied: bool
    
    # Final Reports from Downstream
    final_reports: Annotated[List[dict], operator.add]

# Prompt for the refinement agent
REFINEMENT_PROMPT_PATH = PROMPTS_DIR / "refinement_agent.md"
REFINEMENT_PROMPT = REFINEMENT_PROMPT_PATH.read_text(encoding="utf-8")

refinement_model = ChatOpenRouter(model_name="google/gemini-2.5-flash", temperature=0.0)

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
    try:
        # Look for JSON block
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            data = json.loads(match.group(0))
            if "final_definition" in data:
                final_def = data["final_definition"]
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
        refined_input = f"{state['original_query']}\n\nRefined Definition/Criteria:\n{final_def}"
        
        return {
            "refinement_messages": messages + [AIMessage(content=content)],
            "refined_definition": final_def,
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
        user_input = "The proposed definition looks correct. Please proceed."
    
    _vprint(f"\nUser provided: {user_input}")
    
    return {
        "refinement_messages": state["refinement_messages"] + [HumanMessage(content=user_input)]
    }

def should_continue_refinement(state: FullWorkflowState):
    if state.get("is_satisfied"):
        return "upper_stream_agent"
    return "human_feedback"

# --- DOWNSTREAM SUBGRAPH DEFINITION --- #
# This subgraph is used for parallel execution of downstream agents
down_workflow = StateGraph(DownAgentState)
down_workflow.add_node("researcher", researcher_node)
down_workflow.add_node("critique", critique_node)
down_workflow.set_entry_point("researcher")
down_workflow.add_edge("researcher", "critique")
down_workflow.add_conditional_edges("critique", down_should_continue)
down_app = down_workflow.compile(checkpointer=downstream_memory)

def downstream_driver(state: DownAgentState):
    """
    Driver node that executes the downstream agent workflow for a single query.
    This node is intended to be called via Send() in parallel.
    """
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
    try:
        final_state = down_app.invoke(state, config=config)
    except Exception as e:
        log.error(f"Downstream agent failed for query '{query}': {e}")
        return {"final_reports": [{
            "query": query,
            "claim": "Error",
            "confidence_score": 0.0,
            "explanation": f"Agent execution failed: {e}",
            "stop_reason": "ERROR",
            "results_dir": state.get("search_session_dir")
        }]}
    
    # Extract report
    claim = determine_final_claim(final_state["messages"])
    score = determine_confidence_score(final_state["messages"])
    explanation = determine_explanation(final_state["messages"])
    stop_reason = (final_state.get("stop_history") or [{}])[-1].get("stop_reason", "COMPLETED")
    
    report = {
        "query": query,
        "claim": claim,
        "confidence_score": score,
        "explanation": explanation,
        "stop_reason": stop_reason,
        "results_dir": state.get("search_session_dir")
    }
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
full_workflow.add_edge("query_generation", "downstream_batch") # Direct edge to batch

# Downstream driver ends the flow (results are aggregated in state)
full_workflow.add_edge("downstream_batch", END) # Batch ends the workflow

# Compile the combined app with the upper-stream's checkpointer
full_app = full_workflow.compile(checkpointer=upper_stream_memory)

# --- RUN THE PIPELINE --- #
def run_full_pipeline(original_query: str, max_concurrency: int = 4):
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
        "refined_definition": None,
        "refinement_messages": [
            SystemMessage(content=REFINEMENT_PROMPT),
            HumanMessage(content=f"User Query: {original_query}")
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
        "queries_generated": len(final_state.get("downstream_states", [])),
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



