"""Public metadata routes (test problems, etc.)."""

from __future__ import annotations

from fastapi import APIRouter

from app.problems.registry import list_test_problems_meta

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/test-problems")
def get_test_problems():
    return {"test_problems": list_test_problems_meta()}
