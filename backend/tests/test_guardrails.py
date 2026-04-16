import pytest
from copy import deepcopy

from src.graph.nodes.compliance import compliance_node
from src.models.schemas import CRMRecord, ActionType

import json


def get_base_record() -> dict:
    with open("fixtures/sample_lead.json") as f:
        return json.load(f)


def test_compliance_no_consent():
    """Test that all outreach is blocked when consent is missing."""
    data = get_base_record()
    data["contact"]["consent_to_contact"] = False
    
    state = {
        "crm_record": CRMRecord(**data),
        "signal_summary": "",
        "blocked_actions": [],
        "compliance_notes": "",
        "candidate_recommendations": [],
        "final_recommendations": [],
        "uncertainty_note": "",
        "messages": []
    }
    
    result = compliance_node(state)
    blocked = result["blocked_actions"]
    
    assert ActionType.SEND_FOLLOW_UP_EMAIL.value in blocked
    assert ActionType.CREATE_CALL_TASK.value in blocked
    assert ActionType.SCHEDULE_MEETING.value in blocked


def test_compliance_no_email():
    """Test that email action is blocked when email is missing."""
    data = get_base_record()
    data["contact"]["has_email"] = False
    data["contact"]["email"] = None
    
    state = {
        "crm_record": CRMRecord(**data),
        "signal_summary": "",
        "blocked_actions": [],
        "compliance_notes": "",
        "candidate_recommendations": [],
        "final_recommendations": [],
        "uncertainty_note": "",
        "messages": []
    }
    
    result = compliance_node(state)
    blocked = result["blocked_actions"]
    
    assert ActionType.SEND_FOLLOW_UP_EMAIL.value in blocked
    assert ActionType.CREATE_CALL_TASK.value not in blocked


def test_compliance_recent_contact():
    """Test that immediate follow-up is blocked if contacted today."""
    data = get_base_record()
    data["activity"]["last_contact_days_ago"] = 0
    
    state = {
        "crm_record": CRMRecord(**data),
        "signal_summary": "",
        "blocked_actions": [],
        "compliance_notes": "",
        "candidate_recommendations": [],
        "final_recommendations": [],
        "uncertainty_note": "",
        "messages": []
    }
    
    result = compliance_node(state)
    blocked = result["blocked_actions"]
    
    assert ActionType.SEND_FOLLOW_UP_EMAIL.value in blocked
    assert ActionType.CREATE_CALL_TASK.value in blocked
