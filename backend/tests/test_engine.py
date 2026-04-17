import json
from pathlib import Path
from uuid import uuid4

import src.api.routes as routes_module
import src.graph.workflow as workflow_module
from src.core.heuristics import get_heuristic_recommendations
from src.models.schemas import ActionType, CRMRecord, NBARResponse, NextBestAction
from src.graph.workflow import run_nba_pipeline


SAMPLE_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "sample_lead.json"
EXPECTED_TOP_LEVEL_KEYS = {"record_id", "recommendations", "uncertainty_note"}
EXPECTED_RECOMMENDATION_KEYS = {
	"action_type",
	"title",
	"reasoning",
	"confidence",
	"evidence",
	"risks_or_caveats",
}


def _load_sample_record() -> CRMRecord:
	payload = json.loads(SAMPLE_FIXTURE_PATH.read_text(encoding="utf-8"))
	return CRMRecord.model_validate(payload)


def _assert_homework_contract(body: dict):
	assert set(body.keys()) == EXPECTED_TOP_LEVEL_KEYS
	assert isinstance(body["record_id"], str) and body["record_id"]

	recommendations = body["recommendations"]
	assert isinstance(recommendations, list)
	assert len(recommendations) == 3

	for rec in recommendations:
		assert set(rec.keys()) == EXPECTED_RECOMMENDATION_KEYS
		assert isinstance(rec["action_type"], str) and rec["action_type"]
		assert isinstance(rec["title"], str) and rec["title"]
		assert isinstance(rec["reasoning"], str) and rec["reasoning"]
		assert isinstance(rec["confidence"], (float, int))
		assert 0.0 <= float(rec["confidence"]) <= 1.0
		assert isinstance(rec["evidence"], list) and len(rec["evidence"]) >= 1
		assert isinstance(rec["risks_or_caveats"], list) and len(rec["risks_or_caveats"]) >= 1


def test_fixture_records_endpoint_supports_pagination(client):
	response = client.get("/api/v1/records?page=1&page_size=5")
	assert response.status_code == 200

	body = response.json()
	assert body["page"] == 1
	assert body["page_size"] == 5
	assert body["total_items"] >= 0
	assert body["total_pages"] >= 0
	assert isinstance(body["has_next"], bool)
	assert isinstance(body["has_prev"], bool)
	assert isinstance(body["invalid_items_skipped"], int)
	assert isinstance(body["items"], list)
	assert len(body["items"]) <= 5


def test_fixture_records_invalid_page_is_rejected(client):
	first_page = client.get("/api/v1/records?page=1&page_size=5")
	assert first_page.status_code == 200

	total_pages = first_page.json()["total_pages"]
	if total_pages == 0:
		return

	response = client.get(f"/api/v1/records?page={total_pages + 1}&page_size=5")
	assert response.status_code == 422


def test_create_or_update_record_endpoint_accepts_valid_payload(client):
	payload = _load_sample_record().model_dump()
	payload["person"]["id"] = f"test-{uuid4().hex[:12]}"
	payload["person"]["name"] = "Created From Frontend Flow"

	response = client.post("/api/v1/records", json=payload)
	assert response.status_code == 201

	body = response.json()
	assert body["person"]["id"] == payload["person"]["id"]
	assert body["person"]["name"] == payload["person"]["name"]


def test_heuristic_engine_always_returns_top_three_structured_actions():
	record = _load_sample_record()

	result = get_heuristic_recommendations(record)

	assert len(result.recommendations) == 3
	assert len({rec.action_type for rec in result.recommendations}) == 3

	for rec in result.recommendations:
		assert 0.0 <= rec.confidence <= 1.0
		assert rec.title
		assert rec.reasoning
		assert rec.evidence
		assert rec.risks_or_caveats


def test_recommend_endpoint_with_heuristic_engine_returns_top_three(client):
	record = _load_sample_record().model_dump()

	response = client.post("/api/v1/recommend?engine=heuristic", json=record)
	assert response.status_code == 200

	body = response.json()
	_assert_homework_contract(body)


def test_recommend_heuristic_endpoint_contract_alignment(client):
	record = _load_sample_record().model_dump()

	response = client.post("/api/v1/recommend/heuristic", json=record)
	assert response.status_code == 200

	_assert_homework_contract(response.json())


def test_recommend_agentic_endpoint_contract_alignment_with_stub(client, monkeypatch):
	record = _load_sample_record()

	stub_response = NBARResponse(
		record_id=record.person.id,
		recommendations=[
			NextBestAction(
				action_type=ActionType.SCHEDULE_MEETING,
				title="Schedule Stakeholder Meeting",
				reasoning="High intent and decision-maker access justify a scheduling action.",
				confidence=0.91,
				evidence=["is_high_intent=True", "is_decision_maker=True"],
				risks_or_caveats=["Could be premature if procurement process is not ready."],
			),
			NextBestAction(
				action_type=ActionType.CREATE_CALL_TASK,
				title="Create Follow-up Call Task",
				reasoning="Recent engagement indicates a direct call can reduce cycle time.",
				confidence=0.83,
				evidence=["engagement_score>70", "last_contact_days_ago=4"],
				risks_or_caveats=["Call timing may not match stakeholder availability."],
			),
			NextBestAction(
				action_type=ActionType.SEND_FOLLOW_UP_EMAIL,
				title="Send Contextual Follow-up Email",
				reasoning="Email provides documented next steps after recent activity.",
				confidence=0.79,
				evidence=["has_email=True", "email_open_rate=0.85"],
				risks_or_caveats=["Could underperform if message is generic."],
			),
		],
		uncertainty_note="Stubbed response for API contract validation.",
	)

	monkeypatch.setattr(routes_module, "run_nba_pipeline", lambda _record: (stub_response, False))

	response = client.post("/api/v1/recommend", json=record.model_dump())
	assert response.status_code == 200

	_assert_homework_contract(response.json())


def test_agentic_pipeline_fallback_backfills_to_top_three(monkeypatch):
	record = _load_sample_record()

	blocked_action = ActionType.SEND_FOLLOW_UP_EMAIL.value
	candidate = NextBestAction(
		action_type=ActionType.SEND_FOLLOW_UP_EMAIL,
		title="Blocked Email Action",
		reasoning="Synthetic recommendation for fallback testing.",
		confidence=0.8,
		evidence=["Synthetic evidence"],
		risks_or_caveats=["Synthetic risk"],
	)

	class _StubGraph:
		@staticmethod
		def invoke(_state):
			return {
				"final_recommendations": [candidate],
				"blocked_actions": [blocked_action],
				"uncertainty_note": "Synthetic uncertainty",
			}

	monkeypatch.setattr(workflow_module, "nba_graph", _StubGraph())

	result, used_heuristic_fallback = run_nba_pipeline(record)

	assert used_heuristic_fallback is False
	assert len(result.recommendations) == 3
	assert all(rec.action_type.value != blocked_action for rec in result.recommendations)
	assert result.uncertainty_note is not None
	assert "deterministic fallback" in result.uncertainty_note.lower()
