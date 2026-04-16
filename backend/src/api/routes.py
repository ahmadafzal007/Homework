"""
FastAPI routes for the NBA Engine.

Public: GET /api/v1/health, POST /api/v1/auth/login-json
Protected: all other /api/v1/* (Bearer JWT)
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.api.deps import get_current_user
from src.core.database import (
    data_store_mode,
    get_cached_recommendation,
    get_records_page,
    save_cached_recommendation,
    upsert_crm_record,
)
from src.core.heuristics import get_heuristic_recommendations
from src.core.security import create_access_token
from src.graph.workflow import run_nba_pipeline
from src.models.schemas import CRMRecord, NBARResponse, PaginatedCRMRecordResponse
from src.core.config import settings

public_router = APIRouter(prefix="/api/v1")
protected_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(get_current_user)],
)


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@public_router.get("/health", tags=["Health"])
def health_check() -> JSONResponse:
    """Liveness/readiness probe."""
    return JSONResponse(
        content={
            "status": "ok",
            "engine": "agentic",
            "data_store": data_store_mode(),
        }
    )


@public_router.post(
    "/auth/login-json",
    response_model=TokenResponse,
    tags=["Auth"],
)
def login_json(body: LoginRequest) -> TokenResponse:
    email = body.email.strip().lower()
    password = body.password
    expected_email = settings.LOGIN_EMAIL.strip().lower()
    if email != expected_email or password != settings.LOGIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = create_access_token(subject=email)
    return TokenResponse(access_token=token)


@protected_router.get(
    "/records",
    response_model=PaginatedCRMRecordResponse,
    status_code=status.HTTP_200_OK,
    tags=["Data"],
    summary="Get paginated CRM fixture records for UI browsing",
)
def list_fixture_records(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    q: str | None = Query(
        default=None,
        max_length=200,
        description="Optional case-insensitive substring filter across id, name, company, role, industry, stage, email, phone",
    ),
) -> PaginatedCRMRecordResponse:
    """Return CRM records (Mongo-backed when available) with pagination metadata."""
    try:
        items, total_items, total_pages, invalid_items = get_records_page(page, page_size, q)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load records: {exc}",
        ) from exc

    if total_pages and page > total_pages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Requested page={page} exceeds total_pages={total_pages}. "
                f"Use a page value between 1 and {total_pages}."
            ),
        )

    return PaginatedCRMRecordResponse(
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
        has_next=bool(total_pages and page < total_pages),
        has_prev=bool(total_pages and page > 1),
        invalid_items_skipped=invalid_items,
        items=items,
    )


@protected_router.post(
    "/records",
    response_model=CRMRecord,
    status_code=status.HTTP_201_CREATED,
    tags=["Data"],
    summary="Create or update a CRM record",
)
def create_or_update_record(record: CRMRecord) -> CRMRecord:
    """Persist a CRM record into MongoDB (or fallback store)."""
    try:
        return upsert_crm_record(record)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist record: {exc}",
        ) from exc


@protected_router.post(
    "/recommend",
    response_model=NBARResponse,
    status_code=status.HTTP_200_OK,
    tags=["NBA Engine"],
    summary="Get NBA recommendations for a CRM record (Agentic defaults)",
)
def recommend(
    record: CRMRecord, engine: str = "agentic", force_refresh: bool = False
) -> NBARResponse:
    """
    Run the NBA pipeline on the provided CRM record.
    Supports 'agentic' (default) and 'heuristic' engines.
    """
    if not force_refresh:
        cached = get_cached_recommendation(record.person.id, engine)
        if cached:
            return cached

    if engine == "heuristic":
        result = get_heuristic_recommendations(record)
    else:
        try:
            result = run_nba_pipeline(record)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Pipeline error: {str(exc)}",
            ) from exc

    if not result.recommendations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "No valid recommendations could be generated for this record. "
                f"Reason: {result.uncertainty_note or 'Unknown'}"
            ),
        )

    save_cached_recommendation(result, engine)
    return result


@protected_router.post(
    "/recommend/heuristic",
    response_model=NBARResponse,
    status_code=status.HTTP_200_OK,
    tags=["NBA Engine"],
    summary="Get NBA recommendations using the Rule-Based (Heuristic) Engine",
)
def recommend_heuristic(record: CRMRecord, force_refresh: bool = False) -> NBARResponse:
    """
    Directly access the deterministic, rule-based heuristic engine.
    """
    if not force_refresh:
        cached = get_cached_recommendation(record.person.id, "heuristic")
        if cached:
            return cached

    result = get_heuristic_recommendations(record)
    save_cached_recommendation(result, "heuristic")
    return result


# --- Submission endpoints (README / AI usage / tests) ---

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_TESTS_DIR = _BACKEND_ROOT / "tests"

_TEST_RUN_LOCK = threading.Lock()
_MAX_TEST_OUTPUT_CHARS = 60_000


class SubmissionDocResponse(BaseModel):
    name: str
    content: str
    content_type: str = "text/markdown"


class SubmissionTestFile(BaseModel):
    path: str
    content: str


class SubmissionTestsResponse(BaseModel):
    files: list[SubmissionTestFile]


class TestRunResponse(BaseModel):
    ok: bool
    exit_code: int
    duration_ms: int
    output: str


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {path.name}",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read {path.name}: {exc}",
        ) from exc


@protected_router.get(
    "/submission/readme",
    response_model=SubmissionDocResponse,
    status_code=status.HTTP_200_OK,
    tags=["Submission"],
    summary="Fetch README.md for the frontend dashboard",
)
def get_submission_readme() -> SubmissionDocResponse:
    path = _REPO_ROOT / "README.md"
    return SubmissionDocResponse(name="README.md", content=_read_text_file(path))


@protected_router.get(
    "/submission/ai-usage",
    response_model=SubmissionDocResponse,
    status_code=status.HTTP_200_OK,
    tags=["Submission"],
    summary="Fetch AI_USAGE.md for the frontend dashboard",
)
def get_submission_ai_usage() -> SubmissionDocResponse:
    path = _REPO_ROOT / "AI_USAGE.md"
    return SubmissionDocResponse(name="AI_USAGE.md", content=_read_text_file(path))


@protected_router.get(
    "/submission/tests",
    response_model=SubmissionTestsResponse,
    status_code=status.HTTP_200_OK,
    tags=["Submission"],
    summary="Fetch backend test files for the frontend dashboard",
)
def get_submission_tests() -> SubmissionTestsResponse:
    if not _TESTS_DIR.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tests folder not found",
        )

    files: list[SubmissionTestFile] = []
    conftest = _TESTS_DIR / "conftest.py"
    if conftest.exists():
        files.append(
            SubmissionTestFile(
                path="backend/tests/conftest.py",
                content=_read_text_file(conftest),
            )
        )

    for p in sorted(_TESTS_DIR.glob("test_*.py")):
        files.append(
            SubmissionTestFile(
                path=f"backend/tests/{p.name}",
                content=_read_text_file(p),
            )
        )

    return SubmissionTestsResponse(files=files)


@protected_router.post(
    "/submission/tests/run",
    response_model=TestRunResponse,
    status_code=status.HTTP_200_OK,
    tags=["Submission"],
    summary="Run backend tests (pytest) and return the output",
)
def run_submission_tests() -> TestRunResponse:
    if not settings.ENABLE_TEST_RUNNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Test runner endpoint is disabled.",
        )

    if not _TEST_RUN_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A test run is already in progress.",
        )

    started = time.perf_counter()
    try:
        env = os.environ.copy()
        env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

        cmd = [sys.executable, "-m", "pytest", "-q", "--color=no"]
        proc = subprocess.run(
            cmd,
            cwd=str(_BACKEND_ROOT),
            capture_output=True,
            text=True,
            timeout=settings.TEST_RUNNER_TIMEOUT_SECONDS,
            env=env,
        )

        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if len(output) > _MAX_TEST_OUTPUT_CHARS:
            output = output[:_MAX_TEST_OUTPUT_CHARS] + "\n\n...output truncated..."

        duration_ms = int((time.perf_counter() - started) * 1000)
        return TestRunResponse(
            ok=proc.returncode == 0,
            exit_code=proc.returncode,
            duration_ms=duration_ms,
            output=output,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)

        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")

        output = (stdout + ("\n" if stdout and stderr else "") + stderr).strip()
        if len(output) > _MAX_TEST_OUTPUT_CHARS:
            output = output[:_MAX_TEST_OUTPUT_CHARS] + "\n\n...output truncated..."

        prefix = "Test run timed out.\n"
        return TestRunResponse(
            ok=False,
            exit_code=124,
            duration_ms=duration_ms,
            output=(prefix + output).strip(),
        )
    finally:
        _TEST_RUN_LOCK.release()
