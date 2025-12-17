import os
import re
import json
import copy
import logging
from typing import List, TypedDict, Optional, Dict
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent
from pydantic import Field, SecretStr
from langchain_core.utils.utils import secret_from_env

# Local imports
# Assuming this file is in code/ and other tools are also in code/
from chemical_ner_tool import ChemicalNerTool
from searching_tool import FullTextJournalSearchTool
from compound_tool import CompoundDatabaseTool
from fulltext_vector_tools import FullTextIndexTool, FullTextQueryTool

load_dotenv()

# -------------------- logging --------------------
logging.basicConfig(level=logging.WARNING, format='%(levelname)s | %(name)s | %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)
log = logging.getLogger("agent_graph")

def _vprint(*args, **kwargs):
    if os.getenv("NODE_LOGS", "1") in ("1", "true", "TRUE", "yes", "YES"):
        print(*args, **kwargs)

# -------------------- models --------------------
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

def _init_models():
    research_model = ChatOpenRouter(model_name="google/gemini-2.5-flash", temperature=0.0)
    evaluator_model = ChatOpenRouter(model_name="openai/gpt-4o-mini", temperature=0.0)
    return research_model, evaluator_model

# -------------------- prompts --------------------
# Adjust path to be relative to this file or absolute
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
LITERATURE_PROMPT_PATH = PROMPTS_DIR / "literature_agent.md"
CRITIQUE_PROMPT_PATH   = PROMPTS_DIR / "critique_agent.md"

def _load_prompt(path: Path, fallback: str) -> SystemMessage:
    try:
        return SystemMessage(content=path.read_text(encoding="utf-8"))
    except Exception:
        return SystemMessage(content=fallback.strip())

LITERATURE_AGENT_PROMPT = _load_prompt(
    LITERATURE_PROMPT_PATH,
    fallback="""
You are a meticulous research agent. Use tools when needed. Return JSON with a top-level "synthesis" object
including keys: claim (string), confidence_score (0..1), explanation (string), limitations (string), supporting_items (list).
""",
)

CRITIQUE_AGENT_PROMPT = _load_prompt(
    CRITIQUE_PROMPT_PATH,
    fallback="""
You are a critical evaluator. Read the researcher's output and decide if we should stop. Return JSON with keys:
decision ("approve" | "clarify" | "reject"), stop_reason (APPROVED | NO_NEW_EVIDENCE | STAGNANT_CLAIM | TOOL_UNAVAILABLE | FUTILITY_DETECTED | ""), 
supporting_sources (list), tool_name (string), agreement_score (0..1).
""",
)

# -------------------- state definitions --------------------
class StateHistory(TypedDict):
    claim: str
    confidence_score: float
    supporting_sources: List[str]
    tool_name: str | None
    stop_reason: str | None

class AgentState(TypedDict):
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

# -------------------- tool factory --------------------
def _build_tools(results_base_dir: str, min_date: str = None, max_date: str = None) -> List:
    ftjs = FullTextJournalSearchTool(
        results_base_dir=results_base_dir,
        include_pubmed=True,
        include_preprints=True,
        include_arxiv=False,
        include_chemrxiv=False,
        include_eupmc=True,
        use_pubmed_free_fulltext_bias=False,
        max_parallel_downloads=2,
        min_date=min_date,
        max_date=max_date,
    )
    tool_list = [ftjs, FullTextIndexTool(results_base_dir=results_base_dir), FullTextQueryTool(results_base_dir=results_base_dir)]
    # Assuming CompoundDatabaseTool is available
    tool_list.insert(0, CompoundDatabaseTool())
    return tool_list

# -------------------- graph builder --------------------
def build_agent(results_base_dir: str):
    memory = MemorySaver()
    research_model, evaluator_model = _init_models()
    tools = _build_tools(results_base_dir)

    agent_executor = create_react_agent(
        research_model, tools, prompt=LITERATURE_AGENT_PROMPT, checkpointer=memory
    )
    critique_agent_executor = create_react_agent(
        evaluator_model, tools, prompt=CRITIQUE_AGENT_PROMPT, checkpointer=memory
    )

    def researcher_node(state: AgentState, config: RunnableConfig):
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

        tags = list(tool_config.get("tags") or [])
        tags.append(f"SSD::{session_dir}")
        tags.append(f"search_session_dir={session_dir}")
        tool_config["tags"] = tags

        metadata = dict(tool_config.get("metadata") or {})
        metadata["search_session_dir"] = session_dir
        tool_config["metadata"] = metadata
        tool_config.pop("recursion_limit", None)

        try:
            FullTextJournalSearchTool.set_session_dir(session_dir)
            FullTextIndexTool.set_session_dir(session_dir)
            FullTextQueryTool.set_session_dir(session_dir)
        except Exception:
            pass

        result = agent_executor.invoke({"messages": input_messages}, config=tool_config)

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

    def critique_node(state: AgentState, config: RunnableConfig):
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

    def should_continue(state: AgentState):
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

    workflow = StateGraph(AgentState)
    workflow.add_node("researcher", researcher_node)
    workflow.add_node("critique", critique_node)
    workflow.set_entry_point("researcher")
    workflow.add_edge("researcher", "critique")
    workflow.add_conditional_edges("critique", should_continue)

    return workflow.compile(checkpointer=memory)
