"""
Shared recommendation post-processing utilities.
Ensures both heuristic and agentic engines always return valid top-3 actions.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from src.models.schemas import ActionType, CRMRecord, NextBestAction


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, value))


def _sanitize_action(rec: NextBestAction) -> NextBestAction:
    evidence = rec.evidence or [
        "Derived from current deal stage, engagement, and recent activity signals."
    ]
    risks = rec.risks_or_caveats or [
        "Recommendation confidence may change as new CRM signals are added."
    ]
    return rec.model_copy(
        update={
            "confidence": _clamp_confidence(rec.confidence),
            "evidence": evidence,
            "risks_or_caveats": risks,
        }
    )


def _fallback_library(record: CRMRecord) -> list[NextBestAction]:
    consent = record.contact.consent_to_contact
    has_email = bool(record.contact.email)
    has_phone = bool(record.contact.phone)
    high_intent = record.signals.is_high_intent
    decision_maker = record.signals.is_decision_maker
    low_engagement = record.signals.engagement_score < 25 or record.signals.is_unresponsive
    low_completeness = record.data_quality.profile_completeness_score < 0.6
    missing_fields = record.data_quality.missing_fields

    return [
        NextBestAction(
            action_type=ActionType.REQUEST_MORE_DATA,
            title="Enrich Missing CRM Fields",
            reasoning=(
                "Important qualification data is missing or incomplete, so data enrichment "
                "should happen before aggressive outreach."
            ),
            confidence=0.86 if low_completeness or missing_fields else 0.62,
            evidence=[
                f"Profile completeness score: {record.data_quality.profile_completeness_score:.2f}",
                f"Missing fields: {', '.join(missing_fields) if missing_fields else 'None explicitly listed'}",
            ],
            risks_or_caveats=[
                "Enrichment may delay immediate outreach but improves recommendation quality.",
            ],
        ),
        NextBestAction(
            action_type=ActionType.PAUSE_OUTREACH,
            title="Pause Direct Outreach Temporarily",
            reasoning=(
                "Signals indicate outreach pressure should be reduced until intent improves "
                "or contactability constraints are resolved."
            ),
            confidence=0.9 if (not consent or low_engagement) else 0.58,
            evidence=[
                f"Consent to contact: {consent}",
                f"Engagement score: {record.signals.engagement_score:.1f}",
                f"Unresponsive flag: {record.signals.is_unresponsive}",
            ],
            risks_or_caveats=[
                "Pipeline velocity may slow while direct outreach is paused.",
            ],
        ),
        NextBestAction(
            action_type=ActionType.MARK_LOW_PRIORITY,
            title="Temporarily Mark as Low Priority",
            reasoning=(
                "Current buying signals and responsiveness suggest this record should be "
                "de-prioritized relative to hotter opportunities."
            ),
            confidence=0.78 if low_engagement else 0.55,
            evidence=[
                f"Engagement score: {record.signals.engagement_score:.1f}",
                f"Last contact days ago: {record.activity.last_contact_days_ago}",
            ],
            risks_or_caveats=[
                "May miss a sudden reactivation signal if monitoring is weak.",
            ],
        ),
        NextBestAction(
            action_type=ActionType.SCHEDULE_MEETING,
            title="Schedule Decision Alignment Meeting",
            reasoning=(
                "Strong intent and decision-making access support a high-touch meeting to "
                "accelerate deal progression."
            ),
            confidence=0.82 if (consent and high_intent and decision_maker) else 0.56,
            evidence=[
                f"High intent: {high_intent}",
                f"Decision maker: {decision_maker}",
                f"Deal stage: {record.deal.stage.value}",
            ],
            risks_or_caveats=[
                "May feel premature if procurement stakeholders are not yet aligned.",
            ],
        ),
        NextBestAction(
            action_type=ActionType.CREATE_CALL_TASK,
            title="Create Discovery/Follow-up Call Task",
            reasoning=(
                "A call can clarify objections and unlock next steps faster than asynchronous channels."
            ),
            confidence=0.77 if (consent and has_phone) else 0.5,
            evidence=[
                f"Has phone: {has_phone}",
                f"Consent to contact: {consent}",
                f"Calls count: {record.activity.calls_count}",
            ],
            risks_or_caveats=[
                "Cold calls can reduce sentiment if timing/context is poor.",
            ],
        ),
        NextBestAction(
            action_type=ActionType.SEND_FOLLOW_UP_EMAIL,
            title="Send Contextual Follow-up Email",
            reasoning=(
                "A concise follow-up email maintains momentum and documents next steps."
            ),
            confidence=0.76 if (consent and has_email) else 0.5,
            evidence=[
                f"Has email: {has_email}",
                f"Last activity type: {record.activity.last_activity_type.value}",
                f"Last contact days ago: {record.activity.last_contact_days_ago}",
            ],
            risks_or_caveats=[
                "Low personalization may reduce response rate.",
            ],
        ),
        NextBestAction(
            action_type=ActionType.ESCALATE_TO_AE,
            title="Escalate to Account Executive",
            reasoning=(
                "Deal value and stage complexity warrant senior seller involvement to reduce friction."
            ),
            confidence=0.79 if (record.deal.deal_value >= 75000) else 0.53,
            evidence=[
                f"Deal value: {record.deal.deal_value}",
                f"Deal stage: {record.deal.stage.value}",
                f"Expected close days: {record.deal.expected_close_days}",
            ],
            risks_or_caveats=[
                "Premature escalation can create internal handoff overhead.",
            ],
        ),
    ]


def ensure_top_recommendations(
    *,
    record: CRMRecord,
    recommendations: Sequence[NextBestAction],
    blocked_action_values: Iterable[str],
    target_count: int = 3,
) -> tuple[list[NextBestAction], bool]:
    """
    Return a de-duplicated, compliance-safe top-N recommendation list.

    If the upstream engine returns fewer than target_count actions, deterministic
    fallbacks are appended to guarantee a stable top-N output contract.
    """
    blocked = set(blocked_action_values)
    selected: list[NextBestAction] = []
    seen_action_types: set[ActionType] = set()

    def _try_add(rec: NextBestAction) -> bool:
        action_value = rec.action_type.value
        if action_value in blocked:
            return False
        if rec.action_type in seen_action_types:
            return False

        selected.append(_sanitize_action(rec))
        seen_action_types.add(rec.action_type)
        return True

    for rec in recommendations:
        _try_add(rec)
        if len(selected) == target_count:
            return selected, False

    fallback_used = False
    for fallback in _fallback_library(record):
        added = _try_add(fallback)
        if added:
            fallback_used = True
        if len(selected) == target_count:
            break

    return selected[:target_count], fallback_used
