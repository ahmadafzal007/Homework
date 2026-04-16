"""
Recommender Agent Node.

Replaces Analyst, Strategy, and Ranker by directly generating the Top 3
recommendations in a single structured Gemini call saving time and API budget.
"""
import json
from typing import List
from pydantic import BaseModel

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from src.core.config import settings
from src.graph.state import AgentState
from src.models.schemas import NextBestAction, ActionType

class RankedOutput(BaseModel):
    recommendations: List[NextBestAction]

_SYSTEM_PROMPT = """You are an expert CRM Strategy Agent.

Your inputs are:
1. A CRM record (JSON).
2. A compliance note listing BLOCKED action types.

Your task:
- Analyze the record and deduce behavioral signals.
- Propose exactly the top 3 best next-action recommendations ranked from best to worst.
- Each action MUST follow the required schema exactly.
- Do NOT suggest any action whose action_type appears in the BLOCKED list.
- Confidence scores must reflect genuine signal strength (0.0-1.0).
- Evidence must be direct references to specific fields from the CRM record.
- risks_or_caveats must list at least one risk per action.
- Handle uncertainty explicitly - if signals are weak, say so in reasoning and lower confidence.

Important CRM domain knowledge:
- Lead/Contacted stages need qualification.
- Qualified/Proposal stages need momentum.
- Negotiation needs high-touch personal engagement.
"""

def recommender_node(state: AgentState) -> AgentState:
    record = state["crm_record"]
    blocked_actions = state.get("blocked_actions", [])
    compliance_notes = state.get("compliance_notes", "")

    llm = ChatGoogleGenerativeAI(
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES,
        google_api_key=settings.GEMINI_API_KEY,
    )

    structured_llm = llm.with_structured_output(RankedOutput)

    allowed_action_types = [
        a.value for a in ActionType if a.value not in blocked_actions
    ]

    user_prompt = f"""CRM Record:
```json
{json.dumps(record.model_dump(), indent=2)}
```

Compliance Notes (BLOCKED actions — do NOT recommend these):
{compliance_notes}
Blocked action_type values: {blocked_actions}

Allowed action_type values you may use:
{allowed_action_types}

Analyze the record and generate exactly the top 3 best next-action recommendations ranked in order of priority."""

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    result: RankedOutput = structured_llm.invoke(messages)

    return {
        **state,
        "final_recommendations": result.recommendations,
        "messages": state.get("messages", []) + messages,
    }