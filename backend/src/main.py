"""
FastAPI application entry point.

Run with:
  uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import protected_router, public_router
from src.core.config import settings
from src.core.database import initialize_data_store, shutdown_data_store


logger = logging.getLogger(__name__)

app = FastAPI(
    title="CRM Next Best Action Engine",
    description=(
        "A multi-agent agentic AI system that recommends the top 3 next best actions "
        "for a CRM customer/prospect record. Powered by LangGraph + Gemini."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Allow all origins for local development — tighten this in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public_router)
app.include_router(protected_router)


@app.on_event("startup")
def on_startup() -> None:
    """Initialize database connectivity and seed fixture data."""
    init_status = initialize_data_store()
    logger.info("Data store initialization status: %s", init_status)


@app.on_event("shutdown")
def on_shutdown() -> None:
    """Close database connections cleanly."""
    shutdown_data_store()


@app.get("/", tags=["Root"])
def root():
    return {
        "message": "CRM Next Best Action Engine is running",
        "docs": "/docs",
        "health": "/api/v1/health",
        "recommend": "POST /api/v1/recommend",
    }
