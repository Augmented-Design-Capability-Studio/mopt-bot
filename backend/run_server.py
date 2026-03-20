#!/usr/bin/env python3
"""
Start the MOPT Study API (Uvicorn).

Defaults come from environment / .env (MOPT_HOST, MOPT_PORT). CLI flags override.

Run from repo root:
  ./venv/bin/python backend/run_server.py
Or from backend/:
  ../venv/Scripts/python.exe run_server.py   # Windows
  ../venv/bin/python run_server.py           # Unix
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent


def main() -> None:
    os.chdir(BACKEND_ROOT)
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    parser = argparse.ArgumentParser(description="Run MOPT FastAPI backend")
    parser.add_argument(
        "--host",
        default=None,
        help="Bind address (default: MOPT_HOST from .env, else 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        metavar="N",
        help="Listen port (default: MOPT_PORT from .env, else 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on code changes (development only; avoid on Pi in production)",
    )
    args = parser.parse_args()

    import uvicorn

    from app.config import get_settings

    settings = get_settings()
    host = args.host if args.host is not None else settings.host
    port = args.port if args.port is not None else settings.port

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
