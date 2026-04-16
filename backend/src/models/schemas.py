"""
Pydantic schemas for the CRM Next Best Action Engine.
Covers the CRM input record and the structured recommendation output.
"""

from __future__ import annotations
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DealStage(str, Enum):
    LEAD = "lead"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"


class DealPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LastActivityType(str, Enum):
    EMAIL_SENT = "email_sent"
    EMAIL_OPEN = "email_open"
    EMAIL_REPLY = "email_reply"
    CALL = "call"
    MEETING = "meeting"
    NONE = "none"


class ActionType(str, Enum):
    SEND_FOLLOW_UP_EMAIL = "send_follow_up_email"
    CREATE_CALL_TASK = "create_call_task"
    SCHEDULE_MEETING = "schedule_meeting"
    PAUSE_OUTREACH = "pause_outreach"
    REQUEST_MORE_DATA = "request_more_data"
    ESCALATE_TO_AE = "escalate_to_account_executive"
    MARK_LOW_PRIORITY = "mark_as_low_priority"


# ---------------------------------------------------------------------------
# CRM Input Schema
# ---------------------------------------------------------------------------

class Person(BaseModel):
    id: str
    name: str
    role: Optional[str] = None
    company: Optional[str] = None
    industry: Optional[str] = None


class Deal(BaseModel):
    stage: DealStage
    deal_value: float = Field(ge=0)
    priority: DealPriority
    expected_close_days: int = Field(ge=0)


class Activity(BaseModel):
    last_contact_days_ago: int = Field(ge=0)
    last_activity_type: LastActivityType
    email_open_rate: float = Field(ge=0.0, le=1.0)
    email_reply_rate: float = Field(ge=0.0, le=1.0)
    calls_count: int = Field(ge=0)
    meetings_count: int = Field(ge=0)


class Contact(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    has_email: bool
    has_phone: bool
    consent_to_contact: bool


class DataQuality(BaseModel):
    missing_fields: List[str] = Field(default_factory=list)
    profile_completeness_score: float = Field(ge=0.0, le=1.0)


class Signals(BaseModel):
    is_high_intent: bool
    is_unresponsive: bool
    is_decision_maker: bool
    engagement_score: float = Field(ge=0.0, le=100.0)


class History(BaseModel):
    total_interactions: int = Field(ge=0)
    days_in_pipeline: int = Field(ge=0)


class CRMRecord(BaseModel):
    """Full CRM input record that the engine accepts."""
    person: Person
    deal: Deal
    activity: Activity
    contact: Contact
    data_quality: DataQuality
    signals: Signals
    history: History


# ---------------------------------------------------------------------------
# NBA Output Schema (exact fields required by the homework)
# ---------------------------------------------------------------------------

class NextBestAction(BaseModel):
    """A single recommended action with full justification."""
    action_type: ActionType
    title: str = Field(description="Short, human-readable action label")
    reasoning: str = Field(description="Why this action is recommended")
    confidence: float = Field(ge=0.0, le=1.0, description="0.0–1.0 confidence score")
    evidence: List[str] = Field(description="Specific signals from the CRM record that support this recommendation")
    risks_or_caveats: List[str] = Field(description="Potential risks, blockers, or caveats for this action")


class NBARResponse(BaseModel):
    """Top-3 recommendations returned by the engine."""
    record_id: str
    recommendations: List[NextBestAction] = Field(min_length=3, max_length=3)
    uncertainty_note: Optional[str] = Field(
        default=None,
        description="Explicit note if the engine had to work with incomplete or contradictory signals"
    )


class PaginatedCRMRecordResponse(BaseModel):
    """Paginated CRM records loaded from fixture data for UI browsing/testing."""
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    has_next: bool
    has_prev: bool
    invalid_items_skipped: int = Field(ge=0)
    items: List[CRMRecord] = Field(default_factory=list)
