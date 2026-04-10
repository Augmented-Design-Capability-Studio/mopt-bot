from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)

_REGISTRY: dict[str, Any] | None = None
_DEFAULT_ID = "vrptw"

_BUILTIN_REL_DIRS = ("knapsack_problem", "vrptw_problem")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef,import-not-found]

    with path.open("rb") as f:
        raw = tomllib.load(f)
    return raw if isinstance(raw, dict) else {}


def _load_path_module(dir_path: Path, reg: dict[str, Any], module_name: str = "register_ports") -> None:
    """Load optional register_ports.py from an extra problem directory."""
    reg_file = dir_path / f"{module_name}.py"
    if not reg_file.is_file():
        log.warning("MOPT problem path %s has no %s.py; skipping", dir_path, module_name)
        return
    spec = importlib.util.spec_from_file_location(f"_mopt_problem_{dir_path.name}", reg_file)
    if spec is None or spec.loader is None:
        log.warning("Could not load spec for %s", reg_file)
        return
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    register_fn = getattr(mod, "register", None)
    if callable(register_fn):
        register_fn(reg)
    else:
        log.warning("%s missing register(registry) callable", reg_file)


def _register_from_manifest_root(reg: dict[str, Any], root: Path) -> None:
    manifest = root / "mopt_manifest.toml"
    if not manifest.is_file():
        log.warning("MOPT domain root %s has no mopt_manifest.toml; skipping", root)
        return
    data = _read_manifest(manifest)
    mod_name = data.get("port_module")
    attr_name = str(data.get("port_attr", "STUDY_PORT"))
    if not mod_name or not isinstance(mod_name, str):
        log.warning("%s missing string port_module", manifest)
        return

    repo_s = str(root.resolve().parent)
    inserted = False
    if repo_s not in sys.path:
        sys.path.insert(0, repo_s)
        inserted = True
    try:
        mod = importlib.import_module(mod_name)
        port = getattr(mod, attr_name)
        pid = getattr(port, "id", None)
        if not isinstance(pid, str) or not pid:
            log.warning("Port from %s has no valid id", manifest)
            return
        reg[pid] = port
    except Exception:
        log.exception("Failed to load study port from %s", manifest)


def register_study_ports() -> dict[str, Any]:
    """Idempotent registration of built-in and env-configured study ports."""
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY

    reg: dict[str, Any] = {}
    repo = _repo_root()
    for rel in _BUILTIN_REL_DIRS:
        _register_from_manifest_root(reg, (repo / rel).resolve())

    settings = get_settings()
    raw = (settings.problem_paths or "").strip()
    if raw:
        for part in raw.split(","):
            p = part.strip()
            if not p:
                continue
            path = Path(p)
            if not path.is_absolute():
                path = (repo / path).resolve()
            if not path.is_dir():
                log.warning("MOPT_PROBLEM_PATHS entry is not a directory: %s", path)
                continue
            manifest = path / "mopt_manifest.toml"
            if manifest.is_file():
                _register_from_manifest_root(reg, path)
            else:
                s = str(path)
                if s not in sys.path:
                    sys.path.insert(0, s)
                _load_path_module(path, reg)

    _REGISTRY = reg
    return reg


def get_study_port(problem_id: str | None) -> Any:
    reg = register_study_ports()
    pid = (problem_id or _DEFAULT_ID).strip().lower()
    port = reg.get(pid)
    if port is None:
        log.warning("Unknown test_problem_id %r; falling back to %s", problem_id, _DEFAULT_ID)
        port = reg[_DEFAULT_ID]
    return port


def list_test_problems_meta() -> list[dict[str, Any]]:
    reg = register_study_ports()
    return [p.meta().to_api_dict() for p in reg.values()]
