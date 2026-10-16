"""Hermes construction team package."""
from __future__ import annotations

from . import kickoff  # noqa: F401
from .prompts import format_coordinator_notification, format_supervisor_task_prompt, parse_supervisor_report
from .service import TeamService, get_service_for_home, register_service_for_home
from .store import Store, TeamError
from .workspace import is_workspace_dirty, prepare_member_workspace, remove_member_workspace

__all__ = [
    "Store",
    "TeamError",
    "TeamService",
    "get_service_for_home",
    "register_service_for_home",
    "prepare_member_workspace",
    "is_workspace_dirty",
    "remove_member_workspace",
    "format_supervisor_task_prompt",
    "parse_supervisor_report",
    "format_coordinator_notification",
]
