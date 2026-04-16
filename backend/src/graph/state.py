"""
LangGraph State definition for the NBA multi-agent workflow.
Each agent reads from and writes back to this shared state object.
"""
from __future__ import annotations
from typing import Annotated, List, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from src.models.schemas import CRMRecord, NextBestAction


class AgentState(TypedDict):
    """
    Shared state passed between every node in the NBA LangGraph workflow.

    Flow:
      Input  ->  Analyst  ->  Compliance  ->  Strategy  ->  Ranker  ->  Output
    """

    # The raw CRM record provided by the API caller
    crm_record: CRMRecord

    # ---- Outputs produced by each node ----

    # Analyst: a plain-English summary of key CRM signals extracted from the record
    signal_summary: Optional[str]

    # Compliance: a list of action_type strings that are BLOCKED (e.g. "send_follow_up_email")
    blocked_actions: Optional[List[str]]

    # Compliance: a human-readable explanation of why certain actions are blocked
    compliance_notes: Optional[str]

    # Strategy: draft list of candidate recommendations (may include blocked ones before filtering)
    candidate_recommendations: Optional[List[NextBestAction]]

    # Ranker: final top-3 ranked and validated recommendations
    final_recommendations: Optional[List[NextBestAction]]

    # Ranker/any node: explicit uncertainty note if signals were incomplete or contradictory
    uncertainty_note: Optional[str]

    # Internal LangGraph message bus (not exposed in the API response)
    messages: Annotated[list, add_messages]
