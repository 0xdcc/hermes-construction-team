"""Authenticated, profile-scoped API on the existing Hermes serve listener."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

_root = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("hermes_construction_bootstrap_api", _root / "bootstrap.py")
_boot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_boot)
core = _boot.load_core()
from hermes_construction_team_core.model_catalog import get_candidate_catalog
router = APIRouter()


def _service():
    try:
        from hermes_constants import get_hermes_home
        from hermes_cli.plugins import discover_plugins
        discover_plugins()
        return core.get_service_for_home(get_hermes_home())
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "plugin_not_ready", "message": str(exc)}) from exc


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        code = getattr(exc, "code", "host_failure")
        status = 403 if code == "permission_denied" else 404 if code.endswith("not_found") else 409 if code in {
            "idempotency_conflict", "request_needs_reconcile", "invalid_task_status", "team_stopped", "workspace_dirty"} else 400
        raise HTTPException(status_code=status, detail={"code": code, "message": str(exc)}) from exc


@router.get("/health")
def health():
    from hermes_constants import get_hermes_home
    from hermes_cli.profiles import get_active_profile_name
    _service()
    return {"ok": True, "version": "0.2.0", "host_compatibility": "hermes-v0.21.6",
            "gateway": str(get_hermes_home()), "profile": get_active_profile_name(),
            "limitations": ["重启只恢复会话和账本，不恢复旧命令调用栈", "工区是协作隔离，不是恶意代码沙箱", "停止不删除工区"]}


@router.get("/settings")
def settings():
    from hermes_constants import get_hermes_home
    service = _service()
    defaults = service.defaults()
    catalog = get_candidate_catalog(service=service, runtime=getattr(service, "runtime", None))

    models = list(catalog.get("models") or [])
    if not models:
        models = [{"model": value, "provider": None} for key, value in service.settings.items() if key.endswith("_model") and value]
    providers = list(catalog.get("providers") or [])

    capabilities = defaults.get("capabilities", {
        "worker_provider_policy": "inherits_supervisor",
        "explanation": "工人由主管子代理链路启动，继承主管的Provider底座与路由；总控、主管与旁路顾问支持独立配置Model和Provider。",
    })

    return {**defaults, "models": models, "providers": providers,
            "capabilities": capabilities,
            "home": str(get_hermes_home()), "endpoint": catalog.get("endpoint"),
            "injection_permission": "需plugins.entries.construction-team.allow_gateway_injection=true"}


@router.get("/teams")
def teams():
    return _service().list_teams()


@router.post("/teams")
def create_team(payload: dict):
    return _run(_service().create_team, payload)


@router.get("/teams/{team_id}")
def snapshot(team_id: str):
    return _run(_service().snapshot, team_id)


@router.post("/teams/{team_id}/members")
def members(team_id: str, payload: dict):
    return _run(_service().add_member, team_id, payload)


@router.post("/teams/{team_id}/tasks")
def tasks(team_id: str, payload: dict):
    return _run(_service().add_task, team_id, payload)


@router.post("/teams/{team_id}/control")
def control(team_id: str, payload: dict):
    return _run(_service().control, team_id, payload.get("action", ""))


@router.post("/teams/{team_id}/tasks/{task_id}/review")
def review(team_id: str, task_id: str, payload: dict):
    return _run(_service().review, team_id, task_id, payload)


@router.post("/teams/{team_id}/members/{member_id}/message")
def message(team_id: str, member_id: str, payload: dict):
    return _run(_service().message, team_id, member_id, payload)


@router.post("/teams/{team_id}/outbox/retry")
def retry(team_id: str):
    active = _service()
    _run(active.flush_outbox, team_id)
    return _run(active.snapshot, team_id)
