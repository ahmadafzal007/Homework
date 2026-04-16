"""
Strategy Brainstormer Agent Node.

Responsibility:
  - Use the signal_summary and compliance context to propose 5-7 candidate
    next best actions via Gemini.
  - Each candidate must already follow the exact output schema (NextBestAction).
  - Blocked actions are injected into the prompt so the LLM avoids them.
  - Uses LangChain structured output (with_structured_output) to guarantee
    the response always maps to our Pydantic schema.
"""
from __future__ import annotations

import json
from typing import List
from pydantic import BaseModel

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from src.core.config import settings
from src.graph.state import AgentState
from src.models.schemas import NextBestAction, ActionType


# ── Wrapper so we can request a LIST of recommendations from the LLM ────────
class CandidateList(BaseModel):
    candidates: List[NextBestAction]


_SYSTEM_PROMPT = """You are a CRM Sales Strategy Agent specialising in next-best-action recommendations.

Your inputs are:
1. A CRM record (JSON) — person, deal, activity, contact, data quality, signals, history.
2. A signal summary written by an analyst agent.
3. A compliance note listing which action types are BLOCKED and must NOT appear in your output.

Your task:
- Propose between 5 and 7 candidate next-best actions that a sales rep should take.
- Each action MUST follow the required schema exactly.
- Do NOT suggest any action whose action_type appears in the BLOCKED list.
- Confidence scores must reflect genuine signal strength (0.0–1.0).
- Evidence must be direct quotes or references to specific fields from the CRM record.
- risks_or_caveats must list at least one risk per action.
- Handle uncertainty explicitly — if signals are weak, say so in reasoning and lower confidence.

Important CRM domain knowledge:
- Lead/Contacted stages need qualification — focus on discovery calls or enrichment.
- Qualified/Proposal stages need momentum — proposals, demos, follow-up.
- Negotiation needs high-touch personal engagement — AE escalation, meeting scheduling.
- Stale deals (no contact > 14 days) need re-engagement but with care.
- High intent + decision maker = prioritise meeting or proposal.
- Low engagement + unresponsive = pause or nurture, not push.
"""


def strategy_node(state: AgentState) -> AgentState:
    """
    Calls Gemini to generate candidate recommendations.
    Uses structured output to return a validated list of NextBestAction objects.
    """
    record = state["crm_record"]
    signal_summary = state.get("signal_summary", "No summary available.")
    blocked_actions = state.get("blocked_actions", [])
    compliance_notes = state.get("compliance_notes", "")

    llm = ChatGoogleGenerativeAI(
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES,
        google_api_key=settings.GEMINI_API_KEY,
    )

    structured_llm = llm.with_structured_output(CandidateList)

    allowed_action_types = [
        a.value for a in ActionType if a.value not in blocked_actions
    ]

    user_prompt = f"""CRM Record:
```json
{json.dumps(record.model_dump(), indent=2)}
```

Signal Summary from Analyst:
{signal_summary}

Compliance Notes (BLOCKED actions — do NOT recommend these):
{compliance_notes}
Blocked action_type values: {blocked_actions}

Allowed action_type values you may use:
{allowed_action_types}

Generate 5–7 candidate next-best-action recommendations."""

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    result: CandidateList = structured_llm.invoke(messages)

    # Secondary safety filter — remove any that slipped through with a blocked type
    safe_candidates = [
        c for c in result.candidates
        if c.action_type.value not in blocked_actions
    ]

    return {
        **state,
        "candidate_recommendations": safe_candidates,
        "messages": state.get("messages", []) + messages,
    }
