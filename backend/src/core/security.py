"""JWT helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from src.core.config import settings


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": subject, "exp": expire},
        settings.JWT_SECRET,
        algorithm="HS256",
    )
