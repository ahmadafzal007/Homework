# AI_USAGE

## Which AI tools you used

- GitHub Copilot (VS Code): Copilot Chat and inline completions.

## What you used them for

- Turning the homework prompt into clear schemas (`CRMRecord` → `NBARResponse`) and API shapes.
- Drafting guardrails (consent/contactability/recency) and heuristic scoring rules.
- Drafting and tightening the agent prompt so the LLM returns structured output.
- Generating test scaffolding to check the “top 3 + required fields” contract.
- Rewriting docs so they match what the backend actually does.

## Where they were helpful

- Speeding up boilerplate and repetitive edits.
- Suggesting edge cases that turned into guardrails.
- Helping with frontend work (API integration, UI design, and implementation details).
- Helping design agents and write agent prompts.
- Helping think through how to orchestrate the agents/workflow.

## Where they were wrong or incomplete

- Didn’t always follow the homework response format unless I made the constraints very explicit (missing fields, or not returning exactly 3).
- Sometimes suggested inefficient designs (for example, multiple LLM/API calls per record).
- Occasionally hallucinated and changed code I didn’t ask it to change.

## What you changed or rejected

- Optimized the API-calling approach (kept it to one structured LLM call per record in the agentic path).
- Adjusted the system prompts to better enforce the exact response structure.
- Verified and corrected responses to match the schema and the homework requirements.
- Rejected vendor-specific CRM assumptions and kept the logic generic.
- Corrected AI-generated documentation details that didn’t match the implementation.
