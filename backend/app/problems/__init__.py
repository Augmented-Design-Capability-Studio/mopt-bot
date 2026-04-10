"""Pluggable study problem modules (registry + port protocol)."""

from app.problems.registry import get_study_port, list_test_problems_meta, register_study_ports

__all__ = ["get_study_port", "list_test_problems_meta", "register_study_ports"]
