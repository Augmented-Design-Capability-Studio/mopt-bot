"""Public metadata routes (test problems, gemini config, etc.)."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.problems.registry import list_test_problems_meta

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/test-problems")
def get_test_problems():
    return {"test_problems": list_test_problems_meta()}


@router.get("/config")
def get_public_config():
    """Return server-driven UI config (no auth required — no secrets exposed)."""
    s = get_settings()
    return {
        "default_gemini_model": s.default_gemini_model,
        "gemini_model_suggestions": s.gemini_model_suggestions_list,
    }
