"""
Ranking & Reviewer Agent Node.

Responsibility:
  - Receive the candidate list from the Strategy node.
  - Score each candidate holistically using Gemini as a critic.
  - Select the Top 3 by final confidence score.
  - Write an uncertainty_note if data quality was poor or signals were contradictory.

This is the final gate before the API response is returned.
"""
from __future__ import annotations

import json
from typing import List, Optional
from pydantic import BaseModel

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from src.core.config import settings
from src.graph.state import AgentState
from src.models.schemas import NextBestAction


# ── Wrapper for the ranker's structured output ───────────────────────────────
class RankedOutput(BaseModel):
    top_recommendations: List[NextBestAction]
    uncertainty_note: Optional[str] = None


_SYSTEM_PROMPT = """You are the Final Reviewer for a CRM Next Best Action engine.

Your inputs:
1. The original CRM record (JSON).
2. A signal summary from the analyst.
3. Compliance notes explaining what is blocked.
4. A list of candidate recommendations from the strategy agent.

Your task:
- Review each candidate recommendation critically.
- Select and return EXACTLY the top 3 most impactful, well-evidenced recommendations.
- Re-score confidence if necessary (e.g., lower it if evidence is thin).
- Improve reasoning clarity if needed — it must be specific, not generic.
- If the CRM record has poor data quality (completeness < 0.6) or contradictory signals,
  include an uncertainty_note explaining this.
- Do NOT add any action type that was blocked by compliance.
- Output must be in the exact structured format required.

Ranking criteria (in order of priority):
1. Consent and data completeness — only recommend what is feasible.
2. Deal urgency — expected close date + deal value + stage.
3. Engagement signal strength — high intent, decision maker, engagement score.
4. Evidence quality — how much specific data supports this action.
5. Risk level — prefer lower-risk actions when signals are weak.
"""


def ranker_node(state: AgentState) -> AgentState:
    """
    Uses Gemini to critically review and select the final top-3 recommendations.
    """
    record = state["crm_record"]
    signal_summary = state.get("signal_summary", "")
    compliance_notes = state.get("compliance_notes", "")
    blocked_actions = state.get("blocked_actions", [])
    candidates = state.get("candidate_recommendations", [])

    # Fallback: if strategy returned nothing, return empty and flag uncertainty
    if not candidates:
        return {
            **state,
            "final_recommendations": [],
            "uncertainty_note": (
                "No valid candidate actions could be generated. "
                "This is likely due to extensive compliance blocks or missing data."
            ),
        }

    llm = ChatGoogleGenerativeAI(
        model=settings.LLM_MODEL,
        temperature=0.1,  # Lower temperature for the reviewer — we want determinism
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES,
        google_api_key=settings.GEMINI_API_KEY,
    )

    structured_llm = llm.with_structured_output(RankedOutput)

    candidates_json = json.dumps(
        [c.model_dump() for c in candidates], indent=2
    )

    user_prompt = f"""CRM Record:
```json
{json.dumps(record.model_dump(), indent=2)}
```

Signal Summary:
{signal_summary}

Compliance Notes:
{compliance_notes}
Blocked actions: {blocked_actions}

Candidate Recommendations to review and rank:
```json
{candidates_json}
```

Select the top 3 recommendations. Adjust confidence scores and reasoning as needed.
Include an uncertainty_note if data quality is low or signals are contradictory."""

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    result: RankedOutput = structured_llm.invoke(messages)

    # Final safety filter — ensure blocked actions never appear in the output
    safe_top3 = [
        r for r in result.top_recommendations
        if r.action_type.value not in blocked_actions
    ][:3]

    # Determine uncertainty note
    uncertainty_note = result.uncertainty_note
    dq = record.data_quality
    if dq.profile_completeness_score < 0.5 and not uncertainty_note:
        uncertainty_note = (
            f"Profile completeness is only {dq.profile_completeness_score:.0%}. "
            f"Missing fields: {', '.join(dq.missing_fields)}. "
            "Recommendations may change significantly once data is enriched."
        )

    return {
        **state,
        "final_recommendations": safe_top3,
        "uncertainty_note": uncertainty_note,
        "messages": state.get("messages", []) + messages,
    }
