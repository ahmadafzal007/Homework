"""
MongoDB integration utilities for CRM records.

- Connects using MongoDB URI from environment.
- Seeds records from fixtures/customer-data.json (same structure as CRMRecord).
- Provides paginated record reads and upsert/create operations.
- Falls back to in-memory fixture records if Mongo is unavailable.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection

from src.core.config import settings
from src.models.schemas import CRMRecord, NBARResponse

logger = logging.getLogger(__name__)

_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "customer-data.json"

_client: MongoClient | None = None
_collection: Collection | None = None
_rec_collection: Collection | None = None
_is_connected: bool = False
_seed_invalid_count: int = 0
_fallback_records: list[CRMRecord] = []
_fallback_recommendations: dict[str, NBARResponse] = {}


def _load_valid_fixture_records() -> tuple[list[CRMRecord], int]:
    raw = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))

    if not isinstance(raw, list):
        raise ValueError("customer-data.json must contain a top-level JSON array")

    valid: list[CRMRecord] = []
    invalid = 0

    for item in raw:
        try:
            valid.append(CRMRecord.model_validate(item))
        except ValidationError:
            invalid += 1
        except Exception:
            invalid += 1

    return valid, invalid


def initialize_data_store() -> dict[str, Any]:
    """
    Initialize MongoDB connection and seed fixture records.

    Returns a status dict with diagnostics used for startup logs.
    """
    global _client, _collection, _rec_collection, _is_connected, _seed_invalid_count, _fallback_records

    records, invalid = _load_valid_fixture_records()
    _fallback_records = records.copy()
    _seed_invalid_count = invalid

    mongo_uri = settings.MongoDB_URI
    if not mongo_uri:
        _is_connected = False
        logger.warning("MongoDB URI not configured. Using fixture fallback mode.")
        return {
            "connected": False,
            "mode": "fixture-fallback",
            "seeded_records": len(records),
            "invalid_fixture_rows": invalid,
            "reason": "MongoDB_URI not set",
        }

    try:
        _client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=settings.MONGODB_CONNECT_TIMEOUT_MS,       
        )
        _client.admin.command("ping")

        db = _client[settings.MONGODB_DB_NAME]
        _collection = db[settings.MONGODB_COLLECTION_NAME]
        _collection.create_index([("person.id", ASCENDING)], unique=True, sparse=True)
        
        _rec_collection = db["recommendations"]
        _rec_collection.create_index([("record_id", ASCENDING)], unique=True, sparse=True)
        upserted = 0
        for record in records:
            result = _collection.replace_one(
                {"person.id": record.person.id},
                record.model_dump(),                upsert=True,
            )
            if result.upserted_id is not None or result.modified_count > 0:
                upserted += 1

        _is_connected = True
        return {
            "connected": True,
            "mode": "mongodb",
            "seeded_records": len(records),
            "invalid_fixture_rows": invalid,
            "upserted_records": upserted,
            "db_name": settings.MONGODB_DB_NAME,
            "collection_name": settings.MONGODB_COLLECTION_NAME,
        }
    except Exception as exc:  # noqa: BLE001
        _is_connected = False
        _collection = None
        _rec_collection = None
        if _client is not None:
            _client.close()
            _client = None

        logger.exception("MongoDB initialization failed. Falling back to fixture mode.")
        return {
            "connected": False,
            "mode": "fixture-fallback",
            "seeded_records": len(records),
            "invalid_fixture_rows": invalid,
            "reason": str(exc),
        }


def shutdown_data_store() -> None:
    """Close MongoDB connections on app shutdown."""
    global _client, _collection, _rec_collection, _is_connected

    if _client is not None:
        _client.close()

    _client = None
    _collection = None
    _rec_collection = None
    _is_connected = False


def data_store_mode() -> str:
    return "mongodb" if _is_connected and _collection is not None else "fixture-fallback"


def _normalized_search(search: str | None) -> str | None:
    if search is None:
        return None
    t = search.strip()
    return t if t else None


def _mongo_search_filter(q: str) -> dict[str, Any]:
    safe = re.escape(q)
    reg: dict[str, str] = {"$regex": safe, "$options": "i"}
    return {
        "$or": [
            {"person.id": reg},
            {"person.name": reg},
            {"person.company": reg},
            {"person.role": reg},
            {"person.industry": reg},
            {"deal.stage": reg},
            {"contact.email": reg},
            {"contact.phone": reg},
        ]
    }


def _record_matches_search(record: CRMRecord, q: str) -> bool:
    ql = q.lower()
    parts = [
        record.person.id,
        record.person.name,
        record.person.role or "",
        record.person.company or "",
        record.person.industry or "",
        record.deal.stage,
        record.contact.email or "",
        record.contact.phone or "",
    ]
    return ql in " ".join(parts).lower()


def get_records_page(
    page: int, page_size: int, search: str | None = None
) -> tuple[list[CRMRecord], int, int, int]:
    """
    Return paginated CRM records.

    Returns:
      (items, total_items, total_pages, invalid_items_skipped)
    """
    sq = _normalized_search(search)
    if _is_connected and _collection is not None:
        filt: dict[str, Any] = _mongo_search_filter(sq) if sq else {}
        total_items = _collection.count_documents(filt)
        total_pages = ((total_items + page_size - 1) // page_size) if total_items else 0

        start_idx = (page - 1) * page_size
        cursor = (
            _collection.find(filt, {"_id": 0})
            .sort("person.id", ASCENDING)
            .skip(start_idx)
            .limit(page_size)
        )

        items: list[CRMRecord] = []
        invalid_items = 0
        for raw in cursor:
            try:
                items.append(CRMRecord.model_validate(raw))
            except ValidationError:
                invalid_items += 1
            except Exception:
                invalid_items += 1

        return items, total_items, total_pages, invalid_items

    records = list(_fallback_records)
    if sq:
        records = [r for r in records if _record_matches_search(r, sq)]
    total_items = len(records)
    total_pages = ((total_items + page_size - 1) // page_size) if total_items else 0

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size

    return records[start_idx:end_idx], total_items, total_pages, _seed_invalid_count


def upsert_crm_record(record: CRMRecord) -> CRMRecord:
    """
    Upsert a CRM record into MongoDB if connected; otherwise update fallback cache.
    """
    if _is_connected and _collection is not None:
        _collection.replace_one(
            {"person.id": record.person.id},
            record.model_dump(),
            upsert=True,
        )
        return record

    # Fallback in-memory upsert
    idx = next((i for i, r in enumerate(_fallback_records) if r.person.id == record.person.id), None)
    if idx is None:
        _fallback_records.append(record)
    else:
        _fallback_records[idx] = record

    return record


def get_cached_recommendation(record_id: str, engine: str) -> NBARResponse | None:
    """Retrieve saved recommendations. Prefix engine to record_id to cache heuristic/agentic separately."""
    key = f"{engine}_{record_id}"
    
    if _is_connected and _rec_collection is not None:
        doc = _rec_collection.find_one({"record_id": key})
        if doc:
            try:
                # Need to swap key back to original record_id so the UI handles it correctly
                doc["record_id"] = record_id
                return NBARResponse.model_validate(doc)
            except Exception as e:
                logger.warning(f"Failed to load cached recommendation: {e}")
                return None
        return None
        
    res = _fallback_recommendations.get(key)
    if res:
        # Clone it and swap the record_id back before returning to avoid mutating cache
        clone = res.model_copy()
        clone.record_id = record_id
        return clone
    return None


def save_cached_recommendation(response: NBARResponse, engine: str) -> None:
    """Save recommendations. Prefix engine to record_id to cache separately."""
    key = f"{engine}_{response.record_id}"
    
    # Store with the modified key
    doc_to_save = response.model_dump()
    doc_to_save["record_id"] = key
    
    if _is_connected and _rec_collection is not None:
        _rec_collection.replace_one(
            {"record_id": key},
            doc_to_save,
            upsert=True,
        )
    else:
        # Cache memory copy using the modified key
        to_store = response.model_copy()
        to_store.record_id = key
        _fallback_recommendations[key] = to_store
