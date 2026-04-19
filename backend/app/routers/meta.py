"""Public metadata routes (test problems, gemini config, etc.)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import get_settings
from app.problems.registry import list_test_problems_meta, _repo_root

router = APIRouter(prefix="/meta", tags=["meta"])

_SAFE_FILENAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")


def _upload_dir(problem_id: str) -> Path:
    safe_id = "".join(c for c in problem_id if c.isalnum() or c == "_")
    return _repo_root() / f"{safe_id}_problem" / "upload"


@router.get("/test-problems")
def get_test_problems():
    return {"test_problems": list_test_problems_meta()}


@router.get("/problem-files/{problem_id}")
def list_problem_files(problem_id: str):
    """List filenames available for upload in a problem's upload folder (no auth)."""
    d = _upload_dir(problem_id)
    if not d.is_dir():
        return {"files": []}
    files = sorted(p.name for p in d.iterdir() if p.is_file() and not p.name.startswith("."))
    return {"files": files}


@router.get("/problem-files/{problem_id}/{filename}")
def get_problem_file(problem_id: str, filename: str):
    """Download a file from a problem's upload folder (no auth)."""
    if not all(c in _SAFE_FILENAME_CHARS for c in filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = _upload_dir(problem_id) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


@router.get("/config")
def get_public_config():
    """Return server-driven UI config (no auth required — no secrets exposed)."""
    s = get_settings()
    return {
        "default_gemini_model": s.default_gemini_model,
        "gemini_model_suggestions": s.gemini_model_suggestions_list,
    }
