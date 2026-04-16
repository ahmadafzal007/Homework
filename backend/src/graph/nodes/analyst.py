"""
Context Analyst Agent Node.

Responsibility:
  - Receive the raw CRM record.
  - Extract and summarise the most important behavioural signals.
  - Produce a concise, structured 'signal_summary' string that all
    downstream agents can reason from.

Uses Gemini via LangChain to produce a short analytical paragraph.
"""
from __future__ import annotations

import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from src.core.config import settings
from src.graph.state import AgentState


_SYSTEM_PROMPT = """You are the Context Analyst for a CRM Next Best Action engine.

Your job is to read the raw CRM record provided and produce a concise signal summary.
The summary must cover:
1. The deal stage and its urgency (expected close days, priority, deal value)
2. Recent engagement patterns (last contact, open rate, reply rate, calls, meetings)
3. Data quality concerns (missing fields, completeness score)
4. Behavioural flags (high intent, unresponsive, decision maker, engagement score)
5. Communication & consent status

Be factual. Do NOT recommend any actions yet. Output only the summary as plain text (2-4 sentences max per bullet point area).
"""


def analyst_node(state: AgentState) -> AgentState:
    """Extracts key signals from the CRM record and writes a signal_summary."""

    record = state["crm_record"]
    record_dict = record.model_dump()

    llm = ChatGoogleGenerativeAI(
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES,
        google_api_key=settings.GEMINI_API_KEY,
    )

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Analyse this CRM record and produce a signal summary:\n\n"
            f"```json\n{json.dumps(record_dict, indent=2)}\n```"
        )),
    ]

    response = llm.invoke(messages)
    res_content = response.content
    if isinstance(res_content, list):
        # Handle cases where content is a list of blocks (e.g. from some versions of Gemini/LangChain)
        summary = " ".join([block.get("text", "") if isinstance(block, dict) else str(block) for block in res_content]).strip()
    else:
        summary = res_content.strip()

    return {
        **state,
        "signal_summary": summary,
        "messages": state.get("messages", []) + messages + [response],
    }
