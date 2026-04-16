"""Test setup: bypass JWT on API routes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.deps import get_current_user
from src.main import app


@pytest.fixture(autouse=True)
def _auth_override() -> None:
    app.dependency_overrides[get_current_user] = lambda: "test-user"
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
