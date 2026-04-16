"""
LangGraph Workflow — NBA Agentic Pipeline.

Assembles the four agent nodes into a directed state graph:

  [START] → analyst → compliance → strategy → ranker → [END]

The graph is compiled once at import time and reused across requests.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from langgraph.graph import StateGraph, START, END

from src.core.config import settings
from src.core.heuristics import get_heuristic_recommendations
from src.core.recommendation_utils import ensure_top_recommendations
from src.graph.state import AgentState
from src.graph.nodes.compliance import compliance_node
from src.graph.nodes.recommender import recommender_node
from src.models.schemas import CRMRecord, NBARResponse, NextBestAction


# ── Build the graph ──────────────────────────────────────────────────────────
def _build_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    # Register nodes
    builder.add_node("compliance", compliance_node)
    builder.add_node("recommender", recommender_node)

    # Define the sequential pipeline
    builder.add_edge(START, "compliance")
    builder.add_edge("compliance", "recommender")
    builder.add_edge("recommender", END)

    return builder.compile()


# Singleton compiled graph — import and use this in the API layer
nba_graph = _build_graph()


# ── Public entry point ───────────────────────────────────────────────────────
def run_nba_pipeline(record: CRMRecord) -> NBARResponse:
    """
    Run the full multi-agent NBA pipeline for a given CRM record.

    Args:
        record: A validated CRMRecord Pydantic object.

    Returns:
        NBARResponse with top-3 recommendations and an optional uncertainty note.
    """
    initial_state: AgentState = {
        "crm_record": record,
        "signal_summary": None,
        "blocked_actions": None,
        "compliance_notes": None,
        "candidate_recommendations": None,
        "final_recommendations": None,
        "uncertainty_note": None,
        "messages": [],
    }

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(nba_graph.invoke, initial_state)
    try:
        final_state = future.result(timeout=settings.AGENTIC_MAX_RUNTIME_SECONDS)
    except FuturesTimeoutError:
        future.cancel()
        fallback = get_heuristic_recommendations(record)
        timeout_note = (
            f"Agentic pipeline exceeded {settings.AGENTIC_MAX_RUNTIME_SECONDS}s runtime guardrail; "
            "returned fast heuristic fallback."
        )
        combined_note = (
            f"{fallback.uncertainty_note} | {timeout_note}"
            if fallback.uncertainty_note
            else timeout_note
        )
        return NBARResponse(
            record_id=fallback.record_id,
            recommendations=fallback.recommendations,
            uncertainty_note=combined_note,
        )
    except Exception as exc:  # noqa: BLE001
        future.cancel()
        fallback = get_heuristic_recommendations(record)
        error_note = (
            "Agentic pipeline failed and automatically switched to fast heuristic fallback "
            f"({exc.__class__.__name__})."
        )
        combined_note = (
            f"{fallback.uncertainty_note} | {error_note}"
            if fallback.uncertainty_note
            else error_note
        )
        return NBARResponse(
            record_id=fallback.record_id,
            recommendations=fallback.recommendations,
            uncertainty_note=combined_note,
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    recommendations: list[NextBestAction] = final_state.get("final_recommendations") or []
    blocked_actions = final_state.get("blocked_actions") or []

    normalized_recommendations, used_fallback = ensure_top_recommendations(
        record=record,
        recommendations=recommendations,
        blocked_action_values=blocked_actions,
        target_count=3,
    )

    uncertainty_note = final_state.get("uncertainty_note")
    if used_fallback:
        fallback_note = (
            "Agentic ranker returned fewer than 3 valid recommendations after compliance "
            "filtering; deterministic fallback actions were added."
        )
        uncertainty_note = f"{uncertainty_note} | {fallback_note}" if uncertainty_note else fallback_note

    return NBARResponse(
        record_id=record.person.id,
        recommendations=normalized_recommendations,
        uncertainty_note=uncertainty_note,
    )
