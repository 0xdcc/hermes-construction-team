"""Hermes plugin entry point. Official source and global configuration stay untouched."""
from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _core():
    path = Path(__file__).parent / "bootstrap.py"
    spec = importlib.util.spec_from_file_location("hermes_construction_bootstrap", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_core()


def _actor_agent():
    from agent.subagent_lifecycle import get_active_subagent_parent
    agent = get_active_subagent_parent()
    if agent is None or not getattr(agent, "session_id", None):
        raise RuntimeError("没有宿主绑定的活动会话身份；不能从请求正文伪造身份")
    return agent


def _actor():
    return _actor_agent().session_id


def register(ctx):
    from hermes_constants import get_hermes_home
    core = _core()
    from hermes_construction_team_core.runtime import HermesRuntime
    from hermes_construction_team_core.workers import WorkerBridge
    home = get_hermes_home().resolve()
    runtime = HermesRuntime(profile=ctx.profile_name)
    settings = {key: ctx.get_config(key, value) for key, value in core.service.DEFAULT_SETTINGS.items()}

    def changed(payload):
        ctx.emit("construction-team.changed", payload)

    service = core.TeamService(core.Store(home / "construction-team" / "state.db"), runtime,
                               inject=ctx.inject_message, settings=settings, changed=changed)
    core.register_service_for_home(home, service)
    ctx.on_unload(service.close)
    service.start()

    def scoped():
        if get_hermes_home().resolve() != home:
            raise core.TeamError("profile_forbidden", "拒绝跨Profile操作施工团队")
        return service

    def team_tool(args=None, **kwargs):
        args = args or kwargs
        try:
            active = scoped()
            actor = _actor()
            payload = args.get("payload") or {}
            action, team_id = args.get("action", "status"), args.get("team_id")
            action = {"add_member": "add_supervisor", "post_task": "dispatch", "review_task": "review"}.get(action, action)
            if action == "create":
                result = active.create_team(payload, actor_key=actor)
            elif action == "defaults":
                result = active.defaults()
            elif action in {"plan", "resolve_models", "prepare_root"}:
                result = _kickoff(active, action, payload, actor)
            elif not team_id:
                teams = [t for t in active.store.list_teams() if t["coordinator_key"] == actor]
                member = active.store.find_member_by_session(actor)
                if member:
                    teams = [active.store.get_team(member["team_id"])]
                result = {"teams": teams}
            elif action == "status":
                result = active.snapshot(team_id, actor_key=actor)
            elif action == "add_supervisor":
                result = active.add_member(team_id, payload, actor_key=actor)
            elif action == "dispatch":
                result = active.add_task(team_id, payload, actor_key=actor)
            elif action in {"pause", "resume", "stop", "recover"}:
                result = active.control(team_id, action, actor_key=actor)
            elif action == "review":
                result = active.review(team_id, payload.get("task_id", ""), payload, actor_key=actor)
            elif action == "message":
                result = active.message(team_id, payload.get("member_id", ""), payload, actor_key=actor)
            elif action == "drain_outbox":
                result = active.drain_outbox(team_id, actor_key=actor)
            else:
                raise core.TeamError("invalid_action", "未知团队动作")
            return json.dumps({"ok": True, "result": result}, ensure_ascii=False)
        except Exception as exc:
            logger.exception("施工团队工具失败")
            return json.dumps({"ok": False, "error": {"code": getattr(exc, "code", "tool_failure"), "message": str(exc)}}, ensure_ascii=False)

    def _kickoff(active, action, payload, actor):
        from hermes_construction_team_core import kickoff
        from hermes_construction_team_core.model_catalog import get_candidate_catalog
        if active.store.find_member_by_session(actor) or active.store.find_worker_by_session(actor):
            raise core.TeamError("permission_denied", "主管/工人不能发起新团队开工")
        catalog = get_candidate_catalog(service=active)["models"]
        if action == "resolve_models":
            names = payload.get("models") or {}
            if not isinstance(names, dict) or not names:
                raise core.TeamError("invalid_payload", "models需为{角色: 口语模型名}")
            return {role: kickoff.resolve_model(text, catalog) for role, text in names.items()}
        if action == "prepare_root":
            if payload.get("confirmed") is not True:
                raise core.TeamError("confirmation_required", "建目录前需用户在本窗口确认；确认后传confirmed=true")
            base = kickoff.projects_base(active.settings)
            root = payload.get("root") or kickoff.suggest_root(payload.get("category"), payload.get("project"), base=base)
            return kickoff.prepare_root(root, base=base)
        agent = _actor_agent()
        coordinator = {"session": "当前窗口", "model": getattr(agent, "model", None),
                       "provider": getattr(agent, "provider", None),
                       "note": "总控即当前对话，模型随本窗口；要换请先用/model切换"}
        busy = [t["id"] for t in active.store.list_teams() if t["coordinator_key"] == actor and t["status"] != "stopped"]
        plan = kickoff.build_plan(payload, catalog=catalog, defaults=active.settings, coordinator=coordinator,
                                  base=kickoff.projects_base(active.settings))
        if busy:
            plan["blockers"].append(f"本窗口已绑定活动团队{busy[0]}；复用它或先stop")
            plan["next"] = "先与用户解决blockers，再重新plan"
        return plan

    def worker_tool(args=None, **kwargs):
        args = args or kwargs
        try:
            active = scoped()
            result = WorkerBridge(ctx, active.worker_callbacks(), None).run(args.get("payload") or args, parent_session_key=_actor())
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            logger.exception("施工工人工具失败")
            return json.dumps({"ok": False, "error": {"code": getattr(exc, "code", "worker_failure"), "message": str(exc)}}, ensure_ascii=False)

    ctx.register_tool(name="construction_team", toolset="construction-team", handler=team_tool,
        description="创建项目团队、添加持久主管、自动派发任务与回传；查看、验收、暂停、继续、停止和恢复对账。",
        schema={"name": "construction_team", "description": "项目总控使用。主管只读自己的团队。开工先plan（只预览确认卡，可附category/project生成目录）/resolve_models（口语模型名→真实ID）/prepare_root（用户确认后建空项目与git基线），用户确认后再create（绑定当前窗口为总控，不传coordinator_model）。其它动作status/defaults/add_supervisor/dispatch/pause/resume/stop/recover/review/message/drain_outbox；兼容别名add_member/post_task/review_task。payload字段遵循操作返回的真实team/member/task标识；必须用稳定request_key，验收需真实evidence，不允许自报PASS。", "parameters": {
            "type": "object", "properties": {"action": {"type": "string"}, "team_id": {"type": "string"}, "payload": {"type": "object"}}, "required": ["action"]}})
    ctx.register_tool(name="construction_workers", toolset="construction-team", handler=worker_tool,
        description="主管派临时工人。固定团队worker模型、工区与并发；收集真实工具结果，不自动验收。",
        schema={"name": "construction_workers", "description": "payload.tasks为明确工单列表，每项goal必填，context可选，mode=write或read。必须实际调用此工具，不能把工人工作改成主管自己完成。写工人同工区单writer；纯读可并行。", "parameters": {
            "type": "object", "properties": {"payload": {"type": "object", "properties": {"tasks": {"type": "array", "items": {"type": "object", "properties": {"goal": {"type": "string"}, "context": {"type": "string"}, "mode": {"type": "string", "enum": ["read", "write"]}}, "required": ["goal", "mode"]}}, "model": {"type": "string"}}, "required": ["tasks"]}}, "required": ["payload"]}})

    def final_turn(**kwargs):
        active = scoped()
        active.on_worker_turn(**kwargs)
        active.on_turn(**kwargs)
    ctx.register_hook("post_llm_call", final_turn)
    ctx.register_hook("subagent_start", lambda **kwargs: scoped().on_subagent_start(**kwargs))

    def guard(tool_name="", args=None, session_id="", **kwargs):
        member = service.store.find_member_by_session(session_id)
        worker = service.store.find_worker_by_session(session_id)
        if not member and not worker:
            return None
        team = service.store.get_team((member or worker)["team_id"])
        if worker and tool_name in {"delegate_task", "construction_team", "construction_workers"}:
            return {"action": "block", "message": "临时工人是叶节点，不得创建团队、委派或改变主管工作"}
        if tool_name == "delegate_task":
            return {"action": "block", "message": "团队主管请用construction_workers，保证固定worker模型、项目并发与结果账本"}
        if member and member["role"] == "advisor" and tool_name not in {
            "read_file", "search_files", "web_extract", "omni_search", "vision_analyze"}:
            return {"action": "block", "message": "顾问只读取证并提供意见，不执行施工或项目控制"}
        if team and team["status"] == "stopped":
            return {"action": "block", "message": "本团队已停止，不再启动工具工作；请返回未完成项"}
        return None
    ctx.register_hook("pre_tool_call", guard)

    def slash(args="", **kwargs):
        if str(args or "").strip() in {"help", "帮助", "start", "开工"}:
            return ("三级施工：在聊天里直接说“用三级施工做这个，主管用X，工人用Y”。"
                    "我会先整理任务书并出确认卡（总控=当前窗口模型），你回复“开工”后才建团队。"
                    "/team 查看状态；停工请说“停止施工团队”。")
        return team_tool({"action": "status"})
    ctx.register_command("team", slash, description="查看施工团队状态；/team help 看对话内开工方式", args_hint="[help]")

    skill_md = Path(__file__).parent / "skills" / "kickoff" / "SKILL.md"
    if skill_md.is_file() and hasattr(ctx, "register_skill"):
        try:
            ctx.register_skill("kickoff", skill_md,
                "Use when 用户在聊天中要求三级施工/施工团队/开工复杂项目. 当前窗口作总控、确认卡后开工.")
        except Exception:
            logger.warning("施工团队开工skill注册失败", exc_info=True)
