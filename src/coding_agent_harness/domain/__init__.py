"""Frozen domain protocol for Coding Agent Harness."""

from .actions import ActionUnion, parse_action
from .models import PayloadT

__all__ = ["ActionUnion", "PayloadT", "parse_action"]
