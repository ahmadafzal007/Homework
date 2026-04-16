# Candidate Homework: Next Best Action Engine

## Problem framing

This project builds a simple **Next Best Action (NBA)** engine for a generic CRM.

You send a structured CRM record (stage, last contact timing, consent/contact info, and a few engagement + data-quality signals). The engine returns **exactly 3** recommended next steps, ranked from best to worst.

Each recommendation includes:

- `action_type`
- `title`
- `reasoning`
- `confidence` (0.0–1.0)
- `evidence`
- `risks_or_caveats`

The response format is enforced by Pydantic and validated by tests.

## Assumptions about CRM behavior

These assumptions are meant to be **generic** (not tied to a specific CRM vendor):

- We assume a typical sales pipeline: `lead → contacted → qualified → proposal → negotiation → closed_(won|lost)`.
- We only do direct outreach if there is consent (`consent_to_contact=true`).
- The channel must exist:
  - email actions need an email address
  - call actions need a phone number
- If the person was contacted today (`last_contact_days_ago=0`), we avoid another follow-up email/call the same day.
- Engagement is treated as a simple set of signals:
  - `engagement_score` is a rough 0–100 score
  - `is_high_intent`, `is_unresponsive`, and `is_decision_maker` help decide what to do next
- If the record is missing important info or has low quality, confidence should drop and the next action often becomes “request more data”.

## Architecture and approach

- **FastAPI** exposes a small API:
  - `POST /api/v1/recommend` (defaults to agentic; supports `?engine=heuristic`)
  - `POST /api/v1/recommend/heuristic` (always deterministic)
- The **data contract** is defined in [backend/src/models/schemas.py](backend/src/models/schemas.py):
  - `CRMRecord` (input)
  - `NBARResponse` (output; recommendations list length is always exactly 3)
- There are two ways to generate recommendations, both using the same guardrails:

  1) **Heuristic engine** ([backend/src/core/heuristics.py](backend/src/core/heuristics.py))
     - rule-based, fast, predictable

  2) **Agentic engine** ([backend/src/graph/workflow.py](backend/src/graph/workflow.py))
     - LangGraph flow: `START → compliance → recommender → END`
     - the `recommender` node makes **one** structured Gemini call
     - a runtime limit (`AGENTIC_MAX_RUNTIME_SECONDS`) is enforced; on timeout/error it falls back to the heuristic engine

- **Compliance/guardrails** live in [backend/src/core/compliance.py](backend/src/core/compliance.py) and run before recommendations.
- The “always return 3” rule is enforced in [backend/src/core/recommendation_utils.py](backend/src/core/recommendation_utils.py) by adding compliant fallback actions if needed.
- Storage is optional:
  - MongoDB if `MongoDB_URI` is set
  - otherwise the app uses fixture + in-memory fallback (`backend/fixtures/customer-data.json`)

## Ranking / recommendation logic

1) **Compliance blocking (shared)**

First, the system determines which action types are not allowed for the record. Common blockers include:

- missing consent
- missing email / missing phone
- “contacted today” (no immediate follow-up)
- closed stages (no active sales actions)

2) **Heuristic ranking**

- Scores candidate actions based on stage, recency, engagement, and a few other signals.
- Converts score → `confidence` (scaled into 0–1).
- Sorts best-to-worst, removes duplicate `action_type`s, and drops blocked actions.
- If fewer than 3 actions are left, it appends deterministic, compliant fallback actions to keep the output stable.
- Sets `uncertainty_note` when data quality is low or when fallbacks were needed.

3) **Agentic ranking**

- Sends the CRM record to the LLM along with:
  - the blocked actions list
  - an explicit list of allowed action types
- Gemini returns a structured list of 3 ranked actions (each with evidence + risks).
- Final post-processing still enforces:
  - compliance filtering
  - deduplication
  - “exactly 3” output (add fallbacks if needed)
- If the agentic path times out or fails, the system returns the heuristic result and annotates `uncertainty_note`.

Implemented action taxonomy (see `ActionType`):

- `send_follow_up_email`
- `create_call_task`
- `schedule_meeting`
- `pause_outreach`
- `request_more_data`
- `escalate_to_account_executive`
- `mark_as_low_priority`

## Tradeoffs

- **Heuristic vs agentic**:
  - heuristic is easy to audit and behaves consistently
  - agentic can combine weaker signals better, but it costs more and depends on an external API
- A strict schema makes the output reliable and easy to grade, but it limits free-form nuance.
- Fallbacks keep the contract stable (always 3 actions), but they can be more generic when signals are thin.
- Caching avoids repeated work, but without TTL/invalidations it can return stale results.

## What you would improve next with more time

- Build a small offline evaluation set (golden records + expected actions) to measure ranking quality over time.
- Improve confidence scoring (especially for the agentic path) using observed outcomes instead of simple scaling.
- Add more realistic CRM constraints: frequency caps beyond “today”, channel preferences, and region-specific compliance.
- Make heuristic weights and thresholds configurable.
- Add TTL-based caching and clearer cache invalidation rules.
- Tighten production concerns (CORS, auth hardening, request limits, better logs/metrics).
