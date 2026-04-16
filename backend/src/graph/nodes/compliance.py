"""
Compliance Officer Agent Node.
Internal LangGraph node that wraps the core compliance utility.
"""
from __future__ import annotations
from src.graph.state import AgentState
from src.core.compliance import check_compliance

def compliance_node(state: AgentState) -> AgentState:
    """
    Deterministic guardrail layer for the LangGraph workflow.
    """
    record = state["crm_record"]
    blocked, notes = check_compliance(record)

    return {
        **state,
        "blocked_actions": [a.value for a in blocked],
        "compliance_notes": notes,
    }
