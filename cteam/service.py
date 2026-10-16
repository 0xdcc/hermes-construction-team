"""Persistent supervisors, short workers, explicit candidate review and reliable reports."""
from __future__ import annotations

import contextvars
import functools
import logging
import os
import re
import secrets
import threading
from pathlib import Path
from typing import Any, Callable

from . import prompts, workspace
from .store import Store, TeamError

logger = logging.getLogger(__name__)
DEFAULT_SETTINGS = {
    "coordinator_model": "gpt-6.1-sol", "coordinator_provider": None,
    "supervisor_model": "gpt-6.1-sol", "supervisor_provider": None,
    "worker_model": "gemini-3.8-flash-high", "worker_provider": None,
    "max_active_supervisors": 2, "max_workers": 4, "advisor_enabled": False,
    "advisor_model": None, "advisor_provider": None,
    "projects_base": None,  # kickoff: where new project folders may be created (default ~/projects)
}
_SERVICES: dict[str, Any] = {}
_REGISTRY_LOCK = threading.RLock()
_PROCESS_KEY = f"{os.getpid()}:{secrets.token_hex(12)}"


def get_service_for_home(home_path=None):
    from hermes_constants import get_hermes_home
    key = str(Path(home_path or get_hermes_home()).resolve())
    with _REGISTRY_LOCK:
        service = _SERVICES.get(key)
    if service is None:
        raise TeamError("plugin_not_ready", "插件执行核心未加载，禁止创建只有账本没有执行器的团队")
    return service


def register_service_for_home(home_path, service):
    with _REGISTRY_LOCK:
        _SERVICES[str(Path(home_path).resolve())] = service


def _mutation(operation):
    def decorate(fn):
        @functools.wraps(fn)
        def run(self, *args, **kwargs):
            payload = args[-1] if args and isinstance(args[-1], dict) else kwargs.get("payload", {})
            team_id = "" if operation == "create_team" else str(args[0])
            actor = kwargs.get("actor_key")
            with self._lock:
                if operation != "create_team":
                    self.authorize(team_id, actor)
                elif actor and self.store.find_member_by_session(actor):
                    raise TeamError("permission_denied", "主管不能创建或接管团队")
                key = payload.get("request_key")
                fingerprint = {**payload, "_actor": actor, "_args": list(args[:-1])}
                cached = self.store.begin_operation(key, team_id, operation, fingerprint)
                if cached is not None:
                    return self.snapshot(cached["team"]["id"])
                try:
                    result = fn(self, *args, **kwargs)
                    self.store.finish_operation(key, result)
                    return result
                except Exception as exc:
                    self.store.finish_operation(key, error=str(exc))
                    if isinstance(exc, TeamError):
                        raise
                    raise TeamError("host_failure", str(exc)) from exc
        return run
    return decorate


class TeamService:
    def __init__(self, store: Store, runtime=None, inject=None, settings=None, changed=None, process_key=None):
        self.store, self.runtime, self.inject = store, runtime, inject
        self.settings = {**DEFAULT_SETTINGS, **(settings or {})}
        self.changed = changed
        self._lock = threading.RLock()
        self._outbox_lock = threading.RLock()
        self._slot_by_worker_id = {}
        self._worker_probes = {}  # process-local, host-bound checks; never serialized capabilities
        self._child_metadata = {}
        self._awaiting_completion = {}
        self._stop = threading.Event()
        self._watch = runtime.watch_completed(self.on_complete) if runtime and hasattr(runtime, "watch_completed") else None
        self._pump = None
        same_process = self.store.claim_process(process_key or _PROCESS_KEY)
        self.same_process_reload = same_process
        self.store.mark_orphaned_operations()
        # Only a different process proves the previous in-process attempt gone.
        # Reload in the same gateway leaves UNKNOWN reservations occupied.
        for team in store.list_teams():
            self._mark_lost(team["id"], same_process=same_process)

    def start(self):
        if self._pump is not None:
            return
        context = contextvars.copy_context()
        self._pump = threading.Thread(target=lambda: context.run(self._background), name="construction-reports", daemon=True)
        self._pump.start()

    def _background(self):
        while not self._stop.wait(3):
            try:
                self.flush_outbox()
            except Exception:
                logger.exception("施工团队回传失败，保留队列")

    def close(self):
        self._stop.set()
        if self._pump:
            self._pump.join(timeout=5)
        if self._watch:
            self._watch()
        if self.runtime and hasattr(self.runtime, "close"):
            self.runtime.close()
        self.store.close()

    def _event(self, team_id, kind, message):
        self.store.add_event(team_id, kind, message)
        if self.changed:
            try:
                self.changed({"team_id": team_id, "kind": kind})
            except Exception:
                logger.exception("视图通知失败；账本与低频刷新仍保留")

    def _team(self, team_id):
        team = self.store.get_team(team_id)
        if not team:
            raise TeamError("team_not_found", "团队不存在")
        return team

    def authorize(self, team_id, actor_key=None, read=False):
        team = self._team(team_id)
        # None is used only by authenticated user REST and internal callbacks.
        if actor_key is None:
            return team
        if actor_key and actor_key == team.get("coordinator_key"):
            return team
        member = self.store.find_member_by_session(actor_key)
        if read and member and member["team_id"] == team_id:
            return team
        raise TeamError("permission_denied", "只有绑定的项目总控可以派发、验收或控制团队")

    def snapshot(self, team_id, actor_key=None):
        self.authorize(team_id, actor_key, read=True)
        return self.store.snapshot(team_id)

    def list_teams(self):
        return {"teams": self.store.list_teams()}

    def defaults(self):
        return {
            "defaults": dict(self.settings),
            "limits": {"max_active_supervisors": 8, "max_workers": 8},
            "capabilities": {
                "worker_provider_policy": "inherits_supervisor",
                "explanation": "工人由主管子代理链路启动，继承主管的Provider底座与路由；总控、主管与旁路顾问支持独立配置Model和Provider。",
            },
        }

    def _require_runtime(self):
        if self.runtime is None:
            raise TeamError("plugin_not_ready", "宿主执行接口未就绪")

    @staticmethod
    def _text(value, name):
        if not isinstance(value, str) or not value.strip():
            raise TeamError("invalid_payload", f"{name}必须为非空文字")
        return value

    @staticmethod
    def _strings(value, name):
        if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
            raise TeamError("invalid_payload", f"{name}必须为非空字符串列表")
        return value

    @_mutation("create_team")
    def create_team(self, payload, actor_key=None):
        self._require_runtime()
        name = self._text(payload.get("name"), "团队名称")
        root = Path(self._text(payload.get("root"), "项目目录")).resolve(strict=True)
        if not root.is_dir():
            raise TeamError("root_not_found", "项目目录不存在")
        settings = dict(self.settings)
        supplied = payload.get("settings") or {}
        if not isinstance(supplied, dict) or set(supplied) - set(DEFAULT_SETTINGS):
            raise TeamError("invalid_payload", "包含不支持的团队配置")
        for limit in ("max_active_supervisors", "max_workers"):
            if limit in supplied:
                value = supplied[limit]
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8:
                    raise TeamError("invalid_payload", "并发范围为1～8")
        for role in ("coordinator", "supervisor", "worker"):
            if f"{role}_model" in supplied:
                self._text(supplied[f"{role}_model"], f"{role}模型")
        if "advisor_model" in supplied and supplied["advisor_model"] is not None:
            self._text(supplied["advisor_model"], "旁路顾问模型")
        for role in ("coordinator", "supervisor", "worker", "advisor"):
            p_val = supplied.get(f"{role}_provider")
            if p_val is not None:
                self._text(p_val, f"{role} Provider")
        if "advisor_enabled" in supplied:
            if not isinstance(supplied["advisor_enabled"], bool):
                raise TeamError("invalid_payload", "advisor_enabled必须为布尔值")
        settings.update(supplied)
        for role in ("coordinator", "supervisor", "worker"):
            self._text(settings[f"{role}_model"], f"{role}模型")
        if settings.get("advisor_enabled"):
            adv_m = settings.get("advisor_model")
            if not adv_m or not isinstance(adv_m, str) or not adv_m.strip():
                raise TeamError("invalid_payload", "启用旁路顾问时必须指定有效的顾问模型")
        coordinator_key = actor_key or payload.get("coordinator_key")
        if actor_key and payload.get("coordinator_key") not in (None, actor_key):
            raise TeamError("permission_denied", "不能伪造其它会话为总控")
        if coordinator_key and ("coordinator_model" in supplied or "coordinator_provider" in supplied):
            raise TeamError("invalid_payload", "绑定已有总控会话时不能重新指定总控模型或Provider；已有会话模型由宿主原生会话界面控制")
        if coordinator_key and any(t["coordinator_key"] == coordinator_key and t["status"] != "stopped" for t in self.store.list_teams()):
            raise TeamError("idempotency_conflict", "该总控已有活动团队，请复用团队")
        project = self.runtime.create_project(name, str(root))
        if not project.get("id"):
            raise TeamError("host_failure", "宿主没有返回项目标识")
        coordinator_runtime = None
        if not coordinator_key:
            session = self.runtime.create_session(str(root), settings["coordinator_model"], settings.get("coordinator_provider"), title=f"总控 · {name}")
            coordinator_key, coordinator_runtime = session["session_key"], session["runtime_id"]
        team = self.store.create_team({"name": name, "root": str(root), "project_id": project["id"],
                                      "coordinator_key": coordinator_key, "coordinator_runtime_id": coordinator_runtime,
                                      "settings": settings, "status": "active"})
        if coordinator_runtime:
            try:
                self.runtime.submit(coordinator_runtime,
                    f"你是施工团队{team['id']}的唯一总控。用户从施工团队界面启动本项目。现在仅回复总控就绪，不自行施工。"
                    "等待用户目标或任务书；后续模块报告保持候选，独立核验真实证据后才能接受。已授权范围内连续推进依赖、返修和集成，禁止自行扩大目标、自动发布或修改生产。", queued=True)
            except Exception as exc:
                self.store.update_team(team["id"], {"status": "needs_reconcile"})
                self._event(team["id"], "coordinator_init_failed", str(exc))
                raise
        self._event(team["id"], "team_created", f"创建施工团队「{name}」，总控入口已绑定")
        return self.snapshot(team["id"])

    @_mutation("add_member")
    def add_member(self, team_id, payload, actor_key=None):
        team = self._team(team_id)
        self._require_runtime()
        if team["status"] in {"stopped", "needs_reconcile"}:
            raise TeamError("team_stopped", "团队停止或待对账，不能添加主管")
        name = self._text(payload.get("name"), "主管名称")
        role = payload.get("role") or "supervisor"
        if role not in {"supervisor", "advisor"}:
            raise TeamError("invalid_role", "未知角色")
        if role == "advisor" and not team["settings"].get("advisor_enabled"):
            raise TeamError("advisor_disabled", "顾问默认关闭；启用须明确模型和路由")
        if len(self.store.list_members(team_id)) >= 8:
            raise TeamError("supervisor_limit_reached", "首版一个团队最多8个主管/顾问")
        model = payload.get("model") or team["settings"].get(f"{role}_model")
        provider = payload.get("provider") or team["settings"].get(f"{role}_provider")
        self._text(model, "角色模型")
        if payload.get("provider") is not None:
            self._text(payload["provider"], "角色 Provider")
        member_id = f"m_{secrets.token_hex(6)}"
        state_root = Path(self.store._db_path).parent / "workspaces" / team_id
        info = workspace.prepare_member_workspace(team["root"], member_id, name, state_root=state_root)
        self.runtime.add_project_folder(team["project_id"], info["workspace"], label=name)
        try:
            session = self.runtime.create_session(info["workspace"], model, provider,
                        parent_key=team["coordinator_key"], title=f"{name} · {team['name']}")
        except Exception as exc:
            self._event(team_id, "member_create_failed", f"主管创建失败，工区保留在{info['workspace']}：{exc}")
            raise
        if not session.get("session_key") or not session.get("runtime_id"):
            raise TeamError("host_failure", "宿主没有返回真实会话标识")
        self.store.create_member({"id": member_id, "team_id": team_id, "name": name, "role": role,
                "model": model, "provider": provider, "session_key": session["session_key"],
                "runtime_id": session["runtime_id"], "workspace": info["workspace"], "base_commit": info["base_commit"], "status": "idle"})
        self._event(team_id, "member_added", f"新增「{name}」；工区隔离，角色会话记录已建立，尚无施工结果")
        return self.snapshot(team_id)

    @_mutation("add_task")
    def add_task(self, team_id, payload, actor_key=None):
        team = self._team(team_id)
        if team["status"] in {"stopped", "needs_reconcile"}:
            raise TeamError("team_stopped", "团队已停止或需要现场对账")
        member = self.store.get_member(payload.get("member_id", ""))
        if not member or member["team_id"] != team_id:
            raise TeamError("member_not_found", "主管不属于本团队")
        title, goal = self._text(payload.get("title"), "标题"), self._text(payload.get("goal"), "目标")
        dependencies = self._strings(payload.get("depends_on", []), "依赖")
        all_tasks = {t["id"]: t for t in self.store.list_tasks(team_id)}
        if any(dep not in all_tasks for dep in dependencies):
            raise TeamError("invalid_dependency", "依赖必须是本团队已存在任务")
        self.store.create_task({"team_id": team_id, "member_id": member["id"], "title": title, "goal": goal,
            "acceptance": self._strings(payload.get("acceptance", []), "验收"),
            "forbidden": self._strings(payload.get("forbidden", []), "禁止动作"), "depends_on": dependencies,
            "request_key": payload.get("request_key"), "status": "pending", "attempt": 1,
            "marker": f"CTEAM_{secrets.token_hex(12)}"})
        self._event(team_id, "task_created", f"任务「{title}」进入主管「{member['name']}」队列")
        self._check_and_dispatch_pending(team_id)
        return self.snapshot(team_id)

    def _check_and_dispatch_pending(self, team_id):
        with self._lock:
            team = self._team(team_id)
            if team["status"] != "active":
                return
            for task in self.store.list_tasks(team_id):
                if task["status"] != "pending":
                    continue
                member = self.store.get_member(task["member_id"])
                if not member or member["id"] in self._awaiting_completion or member["status"] not in {"idle", "failed", "blocked"}:
                    continue
                if any((self.store.get_task(dep) or {}).get("status") != "accepted" for dep in task["depends_on"]):
                    continue
                active = [t for t in self.store.list_tasks(team_id) if t["status"] in {"dispatching", "running"}]
                if any(t["member_id"] == member["id"] for t in active) or len(active) >= team["settings"]["max_active_supervisors"]:
                    continue
                self._dispatch_task_now(team, member, task)

    def _dispatch_task_now(self, team, member, task):
        self._require_runtime()
        if not member.get("runtime_id"):
            if not member.get("session_key"):
                raise TeamError("session_missing", "主管没有持久会话，需要显式核对")
            session = self.runtime.resume_session(member["session_key"], cwd=member["workspace"])
            self.store.update_member(member["id"], {"runtime_id": session["runtime_id"]})
            member = self.store.get_member(member["id"])
        # The exact same stored marker is embedded in the submitted task book.
        self.store.update_task(task["id"], {"status": "dispatching"})
        self.store.update_member(member["id"], {"status": "running"})
        text = prompts.format_supervisor_task_prompt(task, member, team)
        try:
            if self.runtime and hasattr(self.runtime, "watch_completed"):
                self._awaiting_completion[member["id"]] = task["id"]
            result = self.runtime.submit(member["runtime_id"], text, queued=True)
            if not result or result.get("status") in {"error", "failed"}:
                raise TeamError("submit_failed", "宿主拒绝任务提交")
            self.store.update_task(task["id"], {"status": "running"})
            self._event(team["id"], "task_dispatched", f"已派给「{member['name']}」；等真实回合报告，不把提交当完成")
        except Exception as exc:
            self._awaiting_completion.pop(member["id"], None)
            status = "unknown" if "timeout" in str(exc).lower() else "failed"
            self.store.update_task(task["id"], {"status": status, "report": str(exc)})
            self.store.update_member(member["id"], {"status": status})
            self._event(team["id"], "dispatch_failed", f"任务提交失败/未知：{exc}")

    @_mutation("review")
    def review(self, team_id, task_id, payload, actor_key=None):
        task = self.store.get_task(task_id)
        if not task or task["team_id"] != team_id:
            raise TeamError("task_not_found", "任务不存在")
        if task["status"] != "candidate":
            raise TeamError("invalid_task_status", "只能验收真实回报后的候选")
        verdict = payload.get("verdict")
        evidence = self._strings(payload.get("evidence", []), "证据")
        note = payload.get("note") or ""
        if verdict == "accept":
            if not evidence:
                raise TeamError("missing_evidence", "通过必须提供已核验的证据路径、命令或结果")
            self.store.update_task(task_id, {"status": "accepted", "evidence": evidence})
            self.store.update_member(task["member_id"], {"status": "idle"})
            self._event(team_id, "task_accepted", f"任务「{task['title']}」由{actor_key or '已认证用户'}核验，证据{len(evidence)}条；{note}")
        elif verdict == "reject":
            self._text(note, "返修原因")
            if task["attempt"] >= 3:
                self.store.update_task(task_id, {"status": "blocked"})
                self.store.update_member(task["member_id"], {"status": "blocked"})
                self._event(team_id, "retry_limit", "已三轮仍未通过，停止自动返修，由总控复盘")
                return self.snapshot(team_id)
            self.store.update_task(task_id, {"status": "pending", "attempt": task["attempt"] + 1,
                "marker": f"CTEAM_{secrets.token_hex(12)}", "goal": task["goal"] + "\n总控返修意见：" + note,
                "report": None, "evidence": evidence})
            self.store.update_member(task["member_id"], {"status": "idle"})
            self._event(team_id, "task_rejected", f"返回原主管继续返修：{note}")
        else:
            raise TeamError("invalid_verdict", "验收动作必须accept或reject")
        self._check_and_dispatch_pending(team_id)
        return self.snapshot(team_id)

    def _mark_lost(self, team_id, same_process=False):
        lost = False
        for task in self.store.list_tasks(team_id):
            if task["status"] in {"dispatching", "running", "unknown"}:
                self.store.update_task(task["id"], {"status": "interrupted", "report": "原执行不再有现场证明；需对照工区后显式继续"})
                lost = True
        for member in self.store.list_members(team_id):
            updates = {"runtime_id": None}
            if member["status"] in {"running", "unknown"}:
                updates["status"] = "interrupted"
                lost = True
            self.store.update_member(member["id"], updates)
        for worker in self.store.list_workers(team_id):
            if worker["status"] in {"pending", "running", "unknown"}:
                self.store.update_worker(worker["id"], {"status": "unknown", "error": "进程重启，旧worker是否完成不可证明"})
                lost = True
        if lost:
            self.store.update_team(team_id, {"status": "needs_reconcile", "coordinator_runtime_id": None})
            self._event(team_id, "recovery_required", "保留会话、产物和候选；旧在途任务不自动重派")
        if not same_process:
            self.store.clear_worker_slots(team_id)
        return lost

    def control(self, team_id, action, actor_key=None):
        with self._lock:
            team = self.authorize(team_id, actor_key)
            if action == "pause":
                if team["status"] in {"stopped", "needs_reconcile"}:
                    raise TeamError("team_stopped", "先核对停止/中断状态")
                self.store.update_team(team_id, {"status": "paused"})
                self._event(team_id, "team_paused", "停止新增派发，在途任务仍可收口与回报")
            elif action == "resume":
                if team["status"] in {"stopped", "needs_reconcile"} and (
                    self.store.count_worker_slots(team_id) or any(w["status"] == "running" for w in self.store.list_workers(team_id))
                    or any(m["status"] == "unknown" for m in self.store.list_members(team_id))):
                    raise TeamError("request_needs_reconcile", "仍有在途或取消未确认的worker，不能释放并发或重派")
                for member in self.store.list_members(team_id):
                    if member["status"] == "interrupted":
                        self.store.update_member(member["id"], {"status": "idle", "runtime_id": None})
                self.store.update_team(team_id, {"status": "active"})
                self._event(team_id, "team_resumed", "显式继续；旧中断任务不重放，新任务复用原会话")
                self._check_and_dispatch_pending(team_id)
            elif action == "stop":
                self.store.update_team(team_id, {"status": "stopped"})
                for task in self.store.list_tasks(team_id):
                    if task["status"] == "pending":
                        self.store.update_task(task["id"], {"status": "cancelled"})
                for member in self.store.list_members(team_id):
                    if member["status"] != "running" and member["id"] not in self._awaiting_completion:
                        continue
                    final_status = "interrupted"
                    try:
                        self.runtime.interrupt(member["runtime_id"])
                        self.store.update_member(member["id"], {"status": "interrupted"})
                    except Exception as exc:
                        final_status = "unknown"
                        self.store.update_member(member["id"], {"status": "unknown"})
                        self._event(team_id, "interrupt_failed", str(exc))
                    for task in self.store.list_tasks_for_member(member["id"]):
                        if task["status"] in {"running", "dispatching"}:
                            self.store.update_task(task["id"], {"status": final_status})
                self._event(team_id, "team_stopped", "仅停止本团队；停止新增派发与自动唤醒，worker取消状态单独显示，成果不删除")
            elif action == "recover":
                if team["status"] == "active" and any(t["status"] in {"running", "dispatching"} for t in self.store.list_tasks(team_id)):
                    raise TeamError("recovery_busy", "本进程仍在施工，请先停止而不是覆盖现场状态")
                recovered = 0
                for worker in self.store.list_workers(team_id):
                    if worker["status"] != "unknown":
                        continue
                    probe = self._worker_probes.get(worker["id"])
                    if not probe:
                        continue
                    try:
                        result = probe()
                    except Exception as exc:
                        self._event(team_id, "worker_reconcile_failed", f"工人{worker['id']}仍未确认：{exc}")
                        continue
                    if not result or result.get("status") not in {"completed", "failed", "cancelled", "interrupted"}:
                        continue
                    self._cb_finished(worker["id"], result)
                    recovered += 1
                unresolved = (self.store.count_worker_slots(team_id)
                    or any(w["status"] in {"pending", "running"} for w in self.store.list_workers(team_id))
                    or any(m["status"] in {"running", "unknown"} for m in self.store.list_members(team_id)))
                if team["status"] == "needs_reconcile" and not unresolved:
                    self.store.update_team(team_id, {"status": "paused"})
                self._event(team_id, "team_recovered", f"宿主明确终态收口{recovered}个工人；未确认占用保持，旧任务不重放，继续需显式操作")
            else:
                raise TeamError("invalid_action", "未知控制动作")
            return self.snapshot(team_id)

    @_mutation("message")
    def message(self, team_id, member_id, payload, actor_key=None):
        team = self._team(team_id)
        if team["status"] != "active":
            raise TeamError("team_stopped", "团队未运行，不发送新回合")
        member = self.store.get_member(member_id)
        if not member or member["team_id"] != team_id:
            raise TeamError("member_not_found", "主管不属于团队")
        text = self._text(payload.get("text"), "消息")
        mode = payload.get("mode", "message")
        if mode not in {"message", "steer"}:
            raise TeamError("invalid_message_mode", "消息模式只能message或steer")
        if member["role"] != "supervisor":
            raise TeamError("invalid_role", "施工消息只能发送到主管；顾问走意见会话")
        if member["status"] == "running":
            if mode != "steer":
                raise TeamError("member_busy", "主管正在施工，纠偏请明确使用steer")
            if not member["runtime_id"]:
                raise TeamError("request_needs_reconcile", "没有可证实的主管运行会话，先对账")
            self.runtime.steer(member["runtime_id"], text)
            self._event(team_id, "member_message", "已向在途主管发送纠偏，以宿主返回处理方式为准")
            return self.snapshot(team_id)
        if mode == "steer" or member["status"] != "idle":
            raise TeamError("member_not_idle", "新消息只发给空闲主管；候选或未知状态先验收/对账")
        return self.add_task(team_id, {"member_id": member_id, "title": "主管后续任务", "goal": text,
            "acceptance": [], "forbidden": [], "depends_on": []}, actor_key=actor_key)

    def on_turn(self, session_id, user_message=None, assistant_response=None, model=None, turn_id=None, **kwargs):
        with self._lock:
            if not user_message:
                return
            member = self.store.find_member_by_session(session_id)
            marker_match = re.search(r"\[CTEAM_MARKER:\s*(CTEAM_[A-Za-z0-9_]+)\]", user_message)
            if marker_match is None:
                return
            task = self.store.find_task_by_marker(marker_match.group(1))
            if not task or task["status"] not in {"dispatching", "running"}:
                return
            if not member or member["id"] != task["member_id"]:
                # A task marker is not an identity credential. Unknown sessions cannot
                # report on another member; compression is reconciled by owned transport.
                return
            if session_id != member["session_key"] and session_id != member["runtime_id"]:
                return
            team = self._team(task["team_id"])
            if team["status"] == "stopped":
                return
            result = prompts.parse_supervisor_report(assistant_response or "")
            status = result["status"]
            if not assistant_response or not assistant_response.strip():
                status = "unknown"
            self.store.update_task(task["id"], {"status": status, "report": assistant_response,
                                  "actual_model": model, "evidence": result["evidence"]})
            self.store.update_member(member["id"], {"status": "awaiting_review" if status == "candidate" else status,
                                                  "actual_model": model})
            self.store.enqueue_outbox(team["id"], "task_report", {"task_id": task["id"], "member_id": member["id"],
                "status": status, "summary": result["summary"], "evidence": result["evidence"], "report": assistant_response})
            self._event(team["id"], "task_report", f"「{member['name']}」回报{status}；业务结果仍待独立核验")
        # Delivery may wait until the background pump; hook does not restart this supervisor.
        self.flush_outbox(task["team_id"])

    def on_complete(self, session_key, runtime_id, payload):
        member = self.store.find_member_by_session(runtime_id)
        expected_task_id = self._awaiting_completion.pop(member["id"], None) if member else None
        if member and session_key and member["session_key"] != session_key:
            self.store.update_member(member["id"], {"session_key": session_key})
        if payload.get("status") not in {"error", "interrupted", "cancelled"} and not payload.get("error"):
            if member:
                tasks = [t for t in self.store.list_tasks_for_member(member["id"]) if t["id"] == expected_task_id and t["status"] in {"running", "dispatching"}]
                if tasks:
                    self.on_turn(session_key, f"[CTEAM_MARKER: {tasks[0]['marker']}]", payload.get("text"),
                                 payload.get("model") or member.get("actual_model"))
                self._check_and_dispatch_pending(member["team_id"])
            return
        with self._lock:
            member = self.store.find_member_by_session(session_key) or self.store.find_member_by_session(runtime_id)
            if not member:
                return
            for task in self.store.list_tasks_for_member(member["id"]):
                if task["status"] not in {"running", "dispatching"}:
                    continue
                status = "interrupted" if payload.get("status") in {"interrupted", "cancelled"} else "failed"
                error = payload.get("error") or payload.get("failure_reason") or payload.get("text") or "宿主回合失败"
                if status != 'interrupted' or self._team(task['team_id'])['status'] != 'stopped':
                    self.store.update_task(task["id"], {"status": status, "report": str(error)})
                self.store.update_member(member["id"], {"status": status})
                self._event(task["team_id"], "turn_failed", str(error))
            if member and payload.get('status') in {'interrupted', 'cancelled'}:
                self.store.update_member(member['id'], {'status': 'interrupted'})
            self._check_and_dispatch_pending(member["team_id"])

    def flush_outbox(self, team_id=None):
        with self._outbox_lock, self._lock:
            for item in self.store.list_pending_outbox(team_id):
                team = self._team(item["team_id"])
                if team["status"] not in {"active", "paused"}:
                    continue
                if not self.inject or not team.get("coordinator_key"):
                    self.store.update_outbox(item["id"], "failed", "总控不在线或未授权自动回传")
                    continue
                task = self.store.get_task(item["payload"].get("task_id", ""))
                member = self.store.get_member(item["payload"].get("member_id", ""))
                if not task or not member:
                    self.store.update_outbox(item["id"], "failed", "回报任务/主管不存在")
                    continue
                text = prompts.format_coordinator_notification(task, member, item["payload"])
                try:
                    accepted = self.inject(text, session_key=team["coordinator_key"])
                    self.store.update_outbox(item["id"], "sent" if accepted else "failed",
                        None if accepted else "总控没有可注入的活动会话；报告保留，等待重试")
                except Exception as exc:
                    self.store.update_outbox(item["id"], "failed", str(exc))

    def drain_outbox(self, team_id, actor_key=None):
        self.authorize(team_id, actor_key)
        self.flush_outbox(team_id)
        return self.snapshot(team_id, actor_key=actor_key)

    def worker_callbacks(self):
        return {"resolve_actor": self._cb_resolve_actor, "acquire": self._cb_acquire,
                "launched": self._cb_launched, "finished": self._cb_finished,
                "remember_probe": self._cb_remember_probe}

    def _cb_remember_probe(self, worker_id, probe):
        with self._lock:
            if self.store.get_worker(worker_id) and callable(probe):
                self._worker_probes[worker_id] = probe

    def _cb_resolve_actor(self, session_key):
        member = self.store.find_member_by_session(session_key)
        if member:
            team = self._team(member["team_id"])
            if member["role"] == "advisor":
                return None
            tasks = [t for t in self.store.list_tasks_for_member(member["id"]) if t["status"] in {"running", "dispatching", "interrupted"}]
            if not tasks:
                return None
            return {"team_id": team["id"], "member_id": member["id"], "task_id": tasks[0]["id"],
                    "workspace": member["workspace"], "session_key": session_key,
                    "settings": team["settings"], "status": team["status"]}
        for team in self.store.list_teams():
            if team["coordinator_key"] == session_key:
                return {"team_id": team["id"], "member_id": "coordinator", "task_id": None,
                        "workspace": team["root"], "session_key": session_key,
                        "settings": team["settings"], "status": team["status"]}
        return None

    def _cb_acquire(self, actor, goal, mode, requested_model):
        with self._lock:
            team = self._team(actor["team_id"])
            if team["status"] != "active":
                raise TeamError("team_stopped", "团队暂停/停止，不启动新worker")
            if requested_model != team["settings"]["worker_model"]:
                raise TeamError("model_mismatch", "worker模型与团队约定不一致")
            slot = self.store.acquire_worker_slot(team["id"], actor["member_id"], mode, team["settings"]["max_workers"])
            try:
                worker = self.store.create_worker({"team_id": team["id"], "member_id": actor["member_id"],
                    "task_id": actor.get("task_id"), "goal": goal, "mode": mode,
                    "status": "pending", "requested_model": requested_model})
            except Exception:
                self.store.release_worker_slot(slot)
                raise
            self._slot_by_worker_id[worker["id"]] = slot
            return worker["id"]

    def _cb_launched(self, worker_id, handle):
        with self._lock:
            worker = self.store.get_worker(worker_id) or {}
            metadata = self._child_metadata.get(handle.get("subagent_id"), {})
            self.store.update_worker(worker_id, {"subagent_id": handle.get("subagent_id"),
                "session_key": metadata.get("child_session_id") or handle.get("session_key"), "status": "running",
                "actual_model": None, "actual_provider": None})

    def on_subagent_start(self, child_subagent_id=None, child_session_id=None, **kwargs):
        if child_subagent_id:
            self._child_metadata[child_subagent_id] = {"child_session_id": child_session_id}

    def on_worker_turn(self, session_id=None, model=None, **kwargs):
        worker = self.store.find_worker_by_session(session_id or "")
        if worker and model:
            self.store.update_worker(worker["id"], {"actual_model": model})


    def _cb_finished(self, worker_id, result):
        with self._lock:
            status = result.get("status") or "unknown"
            worker = self.store.get_worker(worker_id) or {}
            self.store.update_worker(worker_id, {"status": status, "summary": result.get("summary"),
                "error": result.get("error"), "duration_seconds": result.get("duration_seconds"),
                "actual_model": worker.get("actual_model"),
                "actual_provider": worker.get("actual_provider")})
            if status != "unknown":
                self._worker_probes.pop(worker_id, None)
                slot = self._slot_by_worker_id.pop(worker_id, None)
                if slot is not None:
                    self.store.release_worker_slot(slot)
