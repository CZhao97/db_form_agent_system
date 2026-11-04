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
from offline_retrieval_config import default_offline_search_kwargs
from compound_tool import CompoundDatabaseTool
from fulltext_vector_tools import FullTextIndexTool, FullTextQueryTool
from prompt_payloads import build_critique_request_payload, build_researcher_followup_payload

load_dotenv()
NO_PROGRESS_EXHAUSTION_THRESHOLD = int(os.environ.get("NO_PROGRESS_EXHAUSTION_THRESHOLD", "2"))
MIN_ITERATIONS_BEFORE_EXHAUSTION = int(os.environ.get("MIN_ITERATIONS_BEFORE_EXHAUSTION", "3"))

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
    evaluator_model = ChatOpenRouter(model_name="openai/gpt-5-mini", temperature=0.0)
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
including keys: claim (string), explanation (string), limitations (string), supporting_items (list).
""",
)

CRITIQUE_AGENT_PROMPT = _load_prompt(
    CRITIQUE_PROMPT_PATH,
    fallback="""
You are a critical evaluator. Read the researcher's output and decide if we should stop. Return JSON with keys:
decision ("approve" | "clarify" | "reject"), stop_reason (APPROVED | ""), 
supporting_sources (list), tool_name (string), agreement_score (0..1).
""",
)

# -------------------- state definitions --------------------
class StateHistory(TypedDict):
    claim: str
    supporting_sources: List[str]
    tool_name: str | None
    stop_reason: str | None

class AgentState(TypedDict):
    messages: List[HumanMessage | AIMessage]
    original_query: str
    search_session_dir: str
    prior_critique_json: str | None
    stop_history: List[StateHistory]
    consecutive_no_new_evidence: int
    consecutive_tool_unavailable: int
    last_researcher_json: str | None
    last_critique_json: str | None
    claim_history: List[str]

# -------------------- helpers --------------------
def _last_researcher_json(messages):
    if not messages:
        return ""
    for msg in reversed(messages):
        content = getattr(msg, "content", "") or ""
        if '"synthesis"' in content:
            return content
    return ""


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


def _signature(values: List[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not values:
        return ()
    return tuple(sorted(str(value).strip() for value in values if str(value).strip()))

def determine_final_claim(messages):
    blob = _last_researcher_json(messages)
    if not blob:
        return "Insufficient Direct Evidence"
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
    return "Insufficient Direct Evidence"

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
        **default_offline_search_kwargs(),
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
            input_messages = [
                HumanMessage(
                    content=build_researcher_followup_payload(
                        current_task=state.get("original_query", ""),
                        previous_researcher_json=prev_research_json,
                        review_feedback_json=crit_json,
                    )
                )
            ]
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
                '{"synthesis": {"claim": "Insufficient Direct Evidence", "explanation": "Agent execution failed internally. '
                'No message was returned.", "limitations": "Agent internal error."}, '
                '"traceability": {}, "next_actions": {}}'
            )

        new_ai_message = AIMessage(content=ai_content)
        all_messages = state["messages"] + [new_ai_message]

        return {
            "messages": all_messages,
            "last_researcher_json": _last_researcher_json(all_messages),
            "prior_critique_json": crit_json,
            "last_critique_json": None,
        }

    def critique_node(state: AgentState, config: RunnableConfig):
        _vprint("-----Critique Node Invoked-----")

        last_researcher_json = _last_researcher_json(state.get("messages", [])) or ""
        if not last_researcher_json:
            last_researcher_json = (state["messages"][-1].content if state.get("messages") else "").strip()

        critique_input = build_critique_request_payload(
            criteria_text=state.get("original_query", ""),
            researcher_output_json=last_researcher_json,
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
            parsed = _normalize_critique_progress_fields(
                parsed,
                has_previous_critique=bool(state.get("prior_critique_json")),
            )
            candidate_reason = parsed.get("stop_reason")
            if isinstance(candidate_reason, str) and candidate_reason.strip():
                normalized_reason = candidate_reason.strip().upper()
                if normalized_reason in {"APPROVED", "REJECTED", "TOOL_UNAVAILABLE"}:
                    stop_reason = normalized_reason
            critique_section = parsed.get("critique", {})
            if isinstance(critique_section, dict) and not stop_reason:
                decision = critique_section.get("decision")
                if isinstance(decision, str):
                    normalized_decision = decision.strip().lower()
                    if normalized_decision == "approve":
                        stop_reason = "APPROVED"
                    elif normalized_decision == "reject":
                        stop_reason = "REJECTED"
            sources = parsed.get("supporting_sources")
            if isinstance(sources, list):
                supporting_sources = [str(item) for item in sources]
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
                synthesis = obj.get("synthesis", {}) if isinstance(obj, dict) else {}
                claim = (synthesis.get("claim") or "").strip() if isinstance(synthesis, dict) else ""
            except Exception:
                pass
            if not claim:
                match_claim = re.search(r'"claim"\s*:\s*"([^"]+)"', blob)
                if match_claim:
                    claim = match_claim.group(1).strip()
            return claim or "Insufficient Direct Evidence"

        claim = _extract_claim(state.get("messages", []))

        history = copy.deepcopy(state.get("stop_history", []))
        history.append({
            "claim": claim,
            "supporting_sources": supporting_sources,
            "tool_name": tool_name,
            "stop_reason": stop_reason,
        })

        prev_critique_obj = None
        try:
            prev_critique_obj = json.loads(state.get("prior_critique_json") or "") if state.get("prior_critique_json") else None
        except Exception:
            prev_critique_obj = None
        prev_no_new = state.get("consecutive_no_new_evidence", 0)
        prev_tool_unavailable = state.get("consecutive_tool_unavailable", 0)
        unchanged_unsolved, repeated_followups = _detect_no_progress(prev_critique_obj, parsed)
        current_followups = _extract_follow_up_query_signature(parsed)
        has_actionable_followups = bool(current_followups)

        previous_sources_sig = _signature(history[-2]["supporting_sources"]) if len(history) >= 2 else ()
        current_sources_sig = _signature(supporting_sources)
        supporting_sources_changed = current_sources_sig != previous_sources_sig

        if stop_reason == "APPROVED":
            no_new = 0
        elif (
            unchanged_unsolved
            and repeated_followups
            and not has_actionable_followups
            and not supporting_sources_changed
        ):
            no_new = prev_no_new + 1
        else:
            no_new = 0

        claim_hist = list(state.get("claim_history", []))
        claim_hist.append(claim if isinstance(claim, str) else "Insufficient Direct Evidence")

        if (
            no_new >= NO_PROGRESS_EXHAUSTION_THRESHOLD
            and len(history) >= MIN_ITERATIONS_BEFORE_EXHAUSTION
            and not stop_reason
        ):
            stop_reason = "EXHAUSTED_NO_PROGRESS"
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
            "prior_critique_json": state.get("prior_critique_json"),
            "last_researcher_json": last_researcher_json,
            "last_critique_json": patched_content,
            "claim_history": claim_hist,
        }

    def should_continue(state: AgentState):
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
            if stop_reason in STOP_REASONS:
                _vprint(f"-----Agent Decided to Stop (stop_reason={stop_reason})-----")
                return True
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

        return "researcher"

    workflow = StateGraph(AgentState)
    workflow.add_node("researcher", researcher_node)
    workflow.add_node("critique", critique_node)
    workflow.set_entry_point("researcher")
    workflow.add_edge("researcher", "critique")
    workflow.add_conditional_edges("critique", should_continue)

    return workflow.compile(checkpointer=memory)
