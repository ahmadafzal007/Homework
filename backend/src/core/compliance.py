"""
Core compliance and guardrail logic for the NBA Engine.
Shared by both Agentic and Heuristic implementations.
"""
from __future__ import annotations
from typing import List, Tuple
from src.models.schemas import ActionType, DealStage, CRMRecord

def check_compliance(record: CRMRecord) -> Tuple[List[ActionType], str]:
    """
    Evaluate deterministic guardrails for a CRM record.
    Returns:
        (blocked_actions: List[ActionType], compliance_notes: str)
    """
    contact = record.contact
    activity = record.activity
    deal = record.deal
    signals = record.signals

    blocked: List[ActionType] = []
    notes: List[str] = []

    # ── Rule 1: No consent to contact ───────────────────────────────────────
    if not contact.consent_to_contact:
        blocked += [
            ActionType.SEND_FOLLOW_UP_EMAIL,
            ActionType.CREATE_CALL_TASK,
            ActionType.SCHEDULE_MEETING,
            ActionType.ESCALATE_TO_AE,
        ]
        notes.append("Consent to contact is FALSE , all direct outreach is BLOCKED.")

    # ── Rule 2: No email address ────────────────────────────────────────────
    if not contact.has_email or not contact.email:
        if ActionType.SEND_FOLLOW_UP_EMAIL not in blocked:
            blocked.append(ActionType.SEND_FOLLOW_UP_EMAIL)
        notes.append("No email address on record, send_follow_up_email is BLOCKED.")

    # ── Rule 3: No phone number ─────────────────────────────────────────────
    if not contact.has_phone or not contact.phone:
        if ActionType.CREATE_CALL_TASK not in blocked:
            blocked.append(ActionType.CREATE_CALL_TASK)
        notes.append("No phone number on record,  create_call_task is BLOCKED.")

    # ── Rule 4: Deal already closed ─────────────────────────────────────────
    if deal.stage in (DealStage.CLOSED_WON, DealStage.CLOSED_LOST):
        for action in [
            ActionType.SEND_FOLLOW_UP_EMAIL,
            ActionType.CREATE_CALL_TASK,
            ActionType.SCHEDULE_MEETING,
            ActionType.ESCALATE_TO_AE,
        ]:
            if action not in blocked:
                blocked.append(action)
        notes.append(f"Deal stage is '{deal.stage.value}', active sales actions are BLOCKED.")

    # ── Rule 5: Contact too recent ──────────────────────────────────────────
    if activity.last_contact_days_ago == 0:
        for action in [
            ActionType.SEND_FOLLOW_UP_EMAIL,
            ActionType.CREATE_CALL_TASK,
        ]:
            if action not in blocked:
                blocked.append(action)
        notes.append("Last contact was today , immediate follow-up is BLOCKED.")

    # ── Rule 6: Unresponsive + Low engagement ───────────────────────────────
    # Note: engagement_score is now 0-100 in the real data, so we check for < 20
    if (
        signals.is_unresponsive
        and signals.engagement_score < 20
        and activity.last_contact_days_ago < 30
    ):
        for action in [
            ActionType.SEND_FOLLOW_UP_EMAIL,
            ActionType.CREATE_CALL_TASK,
        ]:
            if action not in blocked:
                blocked.append(action)
        notes.append("Contact is persistently unresponsive , direct outreach is BLOCKED.")

    compliance_notes = " | ".join(notes) if notes else "No compliance blockers identified."
    return blocked, compliance_notes
