"""
Deterministic, rule-based Next Best Action engine.
Uses a scoring matrix based on lifecycle stage, deal value, and engagement signals.
"""
from __future__ import annotations
from typing import List, Tuple
from src.core.compliance import check_compliance
from src.core.recommendation_utils import ensure_top_recommendations
from src.models.schemas import (
    CRMRecord, 
    NextBestAction, 
    ActionType, 
    DealStage, 
    NBARResponse
)

def get_heuristic_recommendations(record: CRMRecord) -> NBARResponse:
    """
    Generate the top 3 recommendations based on deterministic rules.
    Respects compliance blockers.
    """
    blocked_actions, compliance_notes = check_compliance(record)
    blocked_values = [a.value for a in blocked_actions]
    
    candidates: List[Tuple[float, NextBestAction]] = []
    
    # ── Helpers ──────────────────────────────────────────────────────────────
    def add_recommendation(
        score: float, 
        action_type: ActionType, 
        title: str, 
        reasoning: str,
        evidence: List[str],
        risks: List[str]
    ):
        if action_type.value in blocked_values:
            return
            
        # Scale score to 0.0 - 1.0 confidence
        confidence = min(max(score / 10.0, 0.1), 0.99)
        candidates.append((score, NextBestAction(
            action_type=action_type,
            title=title,
            reasoning=reasoning,
            confidence=confidence,
            evidence=evidence,
            risks_or_caveats=risks
        )))

    # ── Rule 1: Urgent Negotiation ───────────────────────────────────────────
    if record.deal.stage == DealStage.NEGOTIATION and record.deal.expected_close_days < 10:
        add_recommendation(
            score=9.5,
            action_type=ActionType.SCHEDULE_MEETING,
            title="Urgent Negotiation Review",
            reasoning="Deal is in negotiation with a very short closing window. Face-to-face alignment is required to finalize terms.",
            evidence=[f"Deal Stage: {record.deal.stage}", f"Expected Close: {record.deal.expected_close_days} days"],
            risks=["Risk of appearing too aggressive if multiple meetings were held recently."]
        )

    # ── Rule 2: Stale High-Value Proposal ────────────────────────────────────
    if record.deal.stage == DealStage.PROPOSAL and record.activity.last_contact_days_ago > 5:
        add_recommendation(
            score=8.5,
            action_type=ActionType.SEND_FOLLOW_UP_EMAIL,
            title="Proposal Follow-up",
            reasoning="Proposal was sent but no activity has been recorded for over 5 days. Momentum is at risk.",
            evidence=[f"Last activity: {record.activity.last_contact_days_ago} days ago"],
            risks=["Potential for 'deal fatigue' if the prospect is busy with internal reviews."]
        )

    # ── Rule 3: High Intent Signal ───────────────────────────────────────────
    if record.signals.is_high_intent and record.signals.engagement_score > 70:
        add_recommendation(
            score=9.0,
            action_type=ActionType.CREATE_CALL_TASK,
            title="Capitalise on High Intent",
            reasoning="The prospect is showing significant engagement signals. A direct call should be made to accelerate the cycle.",
            evidence=[f"Engagement Score: {record.signals.engagement_score}", "High Intent: True"],
            risks=["May be seen as intrusive if the specific intent source isn't clarified."]
        )

    # ── Rule 4: Missing Decision Maker ───────────────────────────────────────
    if not record.signals.is_decision_maker and record.deal.deal_value > 50000:
        add_recommendation(
            score=7.5,
            action_type=ActionType.REQUEST_MORE_DATA,
            title="Identify EB/Decision Maker",
            reasoning="This is a high-value deal, but we are not yet speaking with a confirmed decision maker.",
            evidence=[f"Deal Value: ${record.deal.deal_value}", "Is Decision Maker: False"],
            risks=["Risk of offending the current contact by going around them."]
        )

    # ── Rule 5: Low Engagement Nurture ───────────────────────────────────────
    if record.signals.engagement_score < 20 or record.signals.is_unresponsive:
        add_recommendation(
            score=6.0,
            action_type=ActionType.PAUSE_OUTREACH,
            title="Pause Outreach for Unresponsive Contact",
            reasoning="Engagement is dropping. Switch to pausing outreach to stay top-of-mind without wasting sales time.",
            evidence=[f"Engagement Score: {record.signals.engagement_score}", "Unresponsive: True"],
            risks=["Loss of direct personal connection if done too early."]
        )

    # ── Rule 6: Fresh Lead Outreach ──────────────────────────────────────────
    if record.deal.stage == DealStage.LEAD and record.activity.last_contact_days_ago > 2:
        add_recommendation(
            score=8.0,
            action_type=ActionType.SEND_FOLLOW_UP_EMAIL,
            title="Initial Discovery Follow-up",
            reasoning="New lead requires qualification. Standard discovery outreach is needed.",
            evidence=[f"Deal Stage: {record.deal.stage}"],
            risks=["May be lost in inbox if not personalized."]
        )

    # Sort by score descending
    candidates.sort(key=lambda x: x[0], reverse=True)
    
    # Simple deduplication by action_type
    seen_types = set()
    final_recs = []
    for score, rec in candidates:
        if rec.action_type not in seen_types:
            final_recs.append(rec)
            seen_types.add(rec.action_type)
        if len(final_recs) == 3:
            break

    final_recs, used_fallback = ensure_top_recommendations(
        record=record,
        recommendations=final_recs,
        blocked_action_values=blocked_values,
        target_count=3,
    )

    uncertainty_parts: list[str] = []
    if record.data_quality.profile_completeness_score < 0.6:
        uncertainty_parts.append(
            "Low profile completeness may reduce recommendation precision."
        )
    if used_fallback:
        uncertainty_parts.append(
            "Heuristic candidate pool was thin after compliance filtering; "
            "deterministic fallback actions were added to maintain top-3 output."
        )
    if compliance_notes and compliance_notes != "No compliance blockers identified.":
        uncertainty_parts.append(compliance_notes)

    return NBARResponse(
        record_id=record.person.id,
        recommendations=final_recs,
        uncertainty_note=(
            " | ".join(uncertainty_parts)
            if uncertainty_parts
            else "Deterministic heuristic applied based on standard sales logic."
        ),
    )
