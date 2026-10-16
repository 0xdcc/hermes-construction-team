"""Controlled temporary worker tool execution bridge for Hermes construction teams.

Invokes subagents via ctx.subagent_lifecycle (launch, wait, result, cancel),
enforces team-pinned worker model & provider configuration, isolates parent
context per worker thread, and guarantees slot release only upon confirmed termination.
"""
from __future__ import annotations

import contextvars
import dataclasses
import logging
import threading
import time
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from .store import TeamError

logger = logging.getLogger(__name__)

MAX_TASKS_PER_RUN = 8


def preflight_provider_compatibility(configured_provider: Optional[str], parent_agent: Any) -> None:
    """Preflight check that configured worker provider matches the parent agent's route.

    Must run BEFORE launch. Resolves domain/endpoint from parent base_url or profile
    config without exposing or reading API keys. Never mutates settings.
    """
    if not configured_provider or not str(configured_provider).strip():
        return  # No override configured; inherits parent route

    cfg_p = str(configured_provider).strip().lower()
    parent_p = (getattr(parent_agent, "provider", None) or "").strip().lower()
    parent_req_p = (getattr(parent_agent, "requested_provider", None) or "").strip().lower()

    # Exact match on provider or requested_provider
    if cfg_p in (parent_p, parent_req_p):
        return

    # Check custom provider routing via full endpoint comparison
    parent_base = getattr(parent_agent, "base_url", None) or ""
    parent_parts = urlsplit(parent_base) if parent_base else None
    parent_endpoint = (
        parent_parts.scheme.lower(),
        parent_parts.netloc.lower(),
        parent_parts.path.rstrip("/").lower(),
    ) if parent_parts and parent_parts.netloc else None

    cfg_endpoint = None
    try:
        from hermes_cli.runtime_provider_custom import _get_named_custom_provider

        named = _get_named_custom_provider(configured_provider)
        if isinstance(named, dict) and named.get("base_url"):
            cfg_parts = urlsplit(named["base_url"])
            if cfg_parts.netloc:
                cfg_endpoint = (
                    cfg_parts.scheme.lower(),
                    cfg_parts.netloc.lower(),
                    cfg_parts.path.rstrip("/").lower(),
                )
    except Exception:
        pass

    # If both resolve to custom endpoints with the exact same endpoint (scheme, host/port, path)
    if (parent_p == "custom" or parent_req_p.startswith("custom")) and cfg_endpoint and parent_endpoint and cfg_endpoint == parent_endpoint:
        return

    parent_host = parent_endpoint[1] if parent_endpoint else ""
    raise TeamError(
        "provider_mismatch",
        f"Configured worker provider '{configured_provider}' incompatible with parent route "
        f"'{parent_req_p or parent_p or 'unknown'}' (endpoint: {parent_host or 'none'})",
    )


def _to_dict(obj: Any) -> dict[str, Any]:
    """Convert dataclass or object with to_dict to standard python dict."""
    if obj is None:
        return {}
    if not isinstance(obj, type) and dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)  # pyright: ignore[reportArgumentType]
    to_dict_fn = getattr(obj, "to_dict", None)
    if callable(to_dict_fn):
        res = to_dict_fn()
        if isinstance(res, dict):
            return res
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    if isinstance(obj, dict):
        return dict(obj)
    return {}


def capture_worker_probe(lifecycle, handle):
    """Query only a host-confirmed terminal result in the authentic parent context.

    The context contains the host's weak parent binding, not a fabricated parent.
    It stays process-local; UNKNOWN/expired handles never release capacity.
    """
    parent_context = contextvars.copy_context()
    probe_lock = threading.Lock()

    def inspect():
        terminal = {"SUCCEEDED": "completed", "FAILED": "failed",
                    "CANCELLED": "cancelled", "INTERRUPTED": "interrupted"}
        state = lifecycle.status(handle)
        state_name = str(getattr(state.state, "value", state.state))
        if state_name not in terminal:
            return None
        result = lifecycle.result(handle)
        result_name = str(getattr(result.terminal_state, "value", result.terminal_state))
        if not result.ready or result.handle != handle or result_name not in terminal:
            return None
        return {"status": terminal[result_name], "summary": result.summary,
                "error": result.error_message, "actual_model": None, "actual_provider": None}

    def probe():
        with probe_lock:
            return parent_context.run(inspect)

    return probe


class WorkerBridge:
    """Orchestrates ephemeral subagent workers with concurrency and role constraints.

    Callbacks protocol:
      - resolve_actor(session_key) -> dict | None
      - acquire(actor, goal, mode, requested_model) -> worker_id (raises TeamError)
      - launched(worker_id, handle_dict) -> None
      - finished(worker_id, result_dict) -> None
    """

    def __init__(
        self,
        context: Any,
        callbacks: dict[str, Callable],
        settings_of: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    ) -> None:
        self._context = context
        self._callbacks = callbacks
        self._settings_of = settings_of
        self._write_lock = threading.Lock()

    def run(self, payload: dict[str, Any], parent_session_key: Optional[str] = None) -> dict[str, Any]:
        """Execute a batch of worker tasks under supervisor or coordinator delegation."""
        from agent.subagent_lifecycle import get_active_subagent_parent

        # 1. Resolve parent session key strictly from context or authorized argument (no payload forging)
        parent_agent = get_active_subagent_parent()
        actual_parent_key = getattr(parent_agent, 'session_id', None) if parent_agent is not None else None
        if not actual_parent_key or (parent_session_key is not None and parent_session_key != actual_parent_key):
            return {"ok": False, "workers": [], "errors": [{"code": "no_parent_context", "message": "工人派单必须绑定实际主管会话，不能由参数替代宿主身份"}]}
        parent_session_key = actual_parent_key
        if not parent_session_key:
            if parent_agent is None:
                return {
                    "ok": False,
                    "workers": [],
                    "errors": [
                        {
                            "code": "no_parent_context",
                            "message": "No active Hermes parent session bound to current execution context",
                        }
                    ],
                }
            parent_session_key = getattr(parent_agent, "session_id", None) or getattr(parent_agent, "session_key", None)
            if not parent_session_key:
                return {
                    "ok": False,
                    "workers": [],
                    "errors": [
                        {
                            "code": "no_session_key",
                            "message": "Cannot extract session key from active parent agent",
                        }
                    ],
                }

        # 2. Resolve actor using authentic parent session key
        resolve_actor = self._callbacks.get("resolve_actor")
        if not callable(resolve_actor):
            return {
                "ok": False,
                "workers": [],
                "errors": [{"code": "misconfigured_callbacks", "message": "Missing resolve_actor callback"}],
            }

        actor = resolve_actor(str(parent_session_key))
        if not actor or not isinstance(actor, dict):
            return {
                "ok": False,
                "workers": [],
                "errors": [
                    {
                        "code": "unauthorized",
                        "message": f"Session '{parent_session_key}' is not authorized for construction workers",
                    }
                ],
            }

        team_status = actor.get("team_status") or actor.get("status")
        if team_status != "active":
            return {
                "ok": False,
                "workers": [],
                "errors": [
                    {
                        "code": "team_inactive",
                        "message": f"Team status is '{team_status}'; worker dispatch blocked",
                    }
                ],
            }

        # 3. Validate task payload
        if not isinstance(payload, dict):
            return {
                "ok": False,
                "workers": [],
                "errors": [{"code": "invalid_payload", "message": "Payload must be a dictionary"}],
            }

        tasks = payload.get("tasks") or []
        if not isinstance(tasks, list) or len(tasks) == 0:
            return {
                "ok": False,
                "workers": [],
                "errors": [{"code": "empty_tasks", "message": "Payload tasks list cannot be empty"}],
            }

        if len(tasks) > MAX_TASKS_PER_RUN:
            return {
                "ok": False,
                "workers": [],
                "errors": [
                    {
                        "code": "too_many_tasks",
                        "message": f"Payload specifies {len(tasks)} tasks; maximum allowed is {MAX_TASKS_PER_RUN}",
                    }
                ],
            }

        for index, task in enumerate(tasks):
            if not isinstance(task, dict) or not isinstance(task.get("goal"), str) or not task["goal"].strip() or task.get("mode", "read") not in {"read", "write"}:
                return {"ok": False, "workers": [], "errors": [{"code": "invalid_task", "message": f"Task {index} must have goal text and mode read/write"}]}
            if task.get("timeout_seconds") is not None:
                value = task["timeout_seconds"]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 300:
                    return {"ok": False, "workers": [], "errors": [{"code": "invalid_timeout", "message": "Worker timeout must be 1–300 seconds"}]}

        # 4. Resolve and validate model & provider (fixed team pinning)
        settings = self._settings_of(actor) if self._settings_of else actor.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}

        configured_model = settings.get("worker_model")
        requested_model = payload.get("model")
        if requested_model and configured_model and requested_model != configured_model:
            return {
                "ok": False,
                "workers": [],
                "errors": [
                    {
                        "code": "invalid_model",
                        "message": (
                            f"Worker model override '{requested_model}' rejected; "
                            f"worker model is pinned to team configuration '{configured_model}'"
                        ),
                    }
                ],
            }

        target_model = configured_model or requested_model or "gemini-3.8-flash-high"
        configured_provider = settings.get("worker_provider")

        # 5. Preflight provider route compatibility before launch
        if parent_agent is not None:
            try:
                preflight_provider_compatibility(configured_provider, parent_agent)
            except TeamError as pe:
                return {
                    "ok": False,
                    "workers": [],
                    "errors": [{"code": pe.code, "message": pe.message}],
                }

        # 6. Partition tasks into read and write sets
        read_tasks = [t for t in tasks if t.get("mode", "read") != "write"]
        write_tasks = [t for t in tasks if t.get("mode", "read") == "write"]

        workers: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        # 7. Execute read tasks concurrently with isolated thread contexts
        if read_tasks:
            read_threads: list[threading.Thread] = []
            read_outcomes: list[Any] = [None] * len(read_tasks)

            def make_read_runner(idx: int, t_item: dict[str, Any]) -> Callable[[], None]:
                def runner():
                    w_res, w_err = self._execute_task(t_item, actor, target_model, configured_provider, str(parent_session_key))
                    read_outcomes[idx] = (w_res, w_err)

                return runner

            for i, t_item in enumerate(read_tasks):
                t_ctx = contextvars.copy_context()
                th = threading.Thread(
                    target=t_ctx.run,
                    args=(make_read_runner(i, t_item),),
                    name=f"cteam-worker-read-{i}",
                )
                read_threads.append(th)
                th.start()

            for th in read_threads:
                th.join()

            for w_res, w_err in read_outcomes:
                if w_res:
                    workers.append(w_res)
                if w_err:
                    errors.append(w_err)

        # 8. Execute write tasks serially (one write worker at a time per bridge)
        for i, t_item in enumerate(write_tasks):
            with self._write_lock:
                write_outcome: list[Any] = [None]

                def make_write_runner(t_target: dict[str, Any]) -> Callable[[], None]:
                    def runner():
                        w_res, w_err = self._execute_task(t_target, actor, target_model, configured_provider, str(parent_session_key))
                        write_outcome[0] = (w_res, w_err)

                    return runner

                t_ctx = contextvars.copy_context()
                th = threading.Thread(
                    target=t_ctx.run,
                    args=(make_write_runner(t_item),),
                    name=f"cteam-worker-write-{i}",
                )
                th.start()
                th.join()

                w_res, w_err = write_outcome[0]
                if w_res:
                    workers.append(w_res)
                if w_err:
                    errors.append(w_err)

        is_ok = len(errors) == 0 and len(workers) > 0 and all(w.get("status") == "completed" for w in workers)
        return {
            "ok": is_ok,
            "workers": workers,
            "errors": errors,
        }

    def _execute_task(
        self,
        task: dict[str, Any],
        actor: dict[str, Any],
        target_model: str,
        configured_provider: Optional[str],
        active_parent_key: str,
    ) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        """Execute a single worker task through ctx.subagent_lifecycle with confirmed slot cleanup."""
        from agent.subagent_lifecycle import SubagentLaunchRequest

        goal = str(task.get("goal") or "").strip()
        if not goal:
            return None, {"code": "invalid_goal", "message": "Worker goal cannot be empty"}

        mode = task.get("mode", "read")
        if mode not in {"read", "write"}:
            return None, {"code": "invalid_mode", "message": f"Task mode must be 'read' or 'write', got '{mode}'"}

        workspace = actor.get("workspace") or ""
        ws_clause = (
            f"[Workspace Constraint: Operate strictly within {workspace}. "
            "Never create or edit files outside this directory. Report artifacts with relative paths.]"
        )
        if mode == 'read':
            ws_clause += "\n[Read-only assignment: do not edit files, call write/patch, or create resources. Use read-only tools.]"
        effective_goal = f"{ws_clause}\n\n{goal}" if workspace else goal

        acquire_cb = self._callbacks["acquire"]
        try:
            worker_id = acquire_cb(actor, goal, mode, target_model)
        except TeamError as te:
            return None, {"code": te.code, "message": te.message}
        except Exception as exc:
            return None, {"code": "acquire_failed", "message": f"Failed to acquire worker slot: {exc}"}

        handle = None
        result = None
        confirmed_terminal = False
        start_time = time.time()
        lifecycle = getattr(self._context, "subagent_lifecycle", None)

        try:
            if lifecycle is None:
                confirmed_terminal = True
                raise TeamError("lifecycle_unavailable", "ctx.subagent_lifecycle service is not available")

            # Construct SubagentLaunchRequest
            context_text = task.get("context")
            req = SubagentLaunchRequest(
                goal=effective_goal,
                context=str(context_text) if context_text else None,
                role="leaf",
                model=target_model,
            )

            handle = lifecycle.launch(req)
            handle_dict = _to_dict(handle)
            # Selected route metadata never proves which model served a turn.
            handle_dict["actual_model"] = None
            handle_dict["actual_provider"] = None
            remember_probe = self._callbacks.get("remember_probe")
            if callable(remember_probe):
                remember_probe(worker_id, capture_worker_probe(lifecycle, handle))

            # Signal launched callback
            launched_cb = self._callbacks.get("launched")
            if callable(launched_cb):
                launched_cb(worker_id, handle_dict)

            # Polling wait loop with short timeout to ensure responsiveness to project pause/stop
            task_timeout = float(task.get("timeout_seconds") or 60.0)
            cancel_requested = False
            while True:
                cur_actor = self._callbacks["resolve_actor"](active_parent_key)
                cur_status = (cur_actor.get("team_status") or cur_actor.get("status")) if isinstance(cur_actor, dict) else None
                if not isinstance(cur_actor, dict) or cur_status not in {"active", "paused"}:
                    cancel_requested = True
                    reason = f"Team transitioned to '{cur_status}'"
                    with contextlib_suppress():
                        lifecycle.cancel(handle, reason=reason)
                    break

                if (time.time() - start_time) >= task_timeout:
                    cancel_requested = True
                    reason = f"Worker task timed out after {task_timeout}s"
                    with contextlib_suppress():
                        lifecycle.cancel(handle, reason=reason)
                    break

                term_state = lifecycle.wait(handle, timeout_seconds=0.5)
                if term_state.completed:
                    confirmed_terminal = True
                    break

            if cancel_requested:
                # Await cancellation confirmation
                term_state = lifecycle.wait(handle, timeout_seconds=3.0)
                confirmed_terminal = term_state.completed

            if confirmed_terminal:
                result = lifecycle.result(handle)
                state = getattr(result, 'terminal_state', None)
                if not getattr(result, 'ready', False) or str(getattr(state, 'value', state)) == 'UNKNOWN':
                    confirmed_terminal = False
                    result = None
            else:
                logger.warning(
                    "Worker %s cancellation unconfirmed (subagent_id=%s); retaining slot",
                    worker_id,
                    getattr(handle, "subagent_id", "unknown"),
                )

            duration = time.time() - start_time
            if result is not None:
                terminal_val = str(
                    result.terminal_state.value
                    if hasattr(result.terminal_state, "value")
                    else result.terminal_state
                )
                status_map = {
                    "SUCCEEDED": "completed",
                    "FAILED": "failed",
                    "CANCELLED": "cancelled",
                    "INTERRUPTED": "interrupted",
                }
                worker_status = status_map.get(terminal_val, "completed" if terminal_val == "SUCCEEDED" else "failed")
                summary_text = result.summary
                error_text = result.error_message or (
                    result.error_classification
                    if result.error_classification not in (None, "NONE")
                    else None
                )
            else:
                worker_status = "unknown"
                summary_text = None
                error_text = "Worker cancellation or execution unconfirmed"

            worker_summary = {
                "id": worker_id,
                "team_id": actor.get("team_id"),
                "member_id": actor.get("member_id"),
                "task_id": actor.get("task_id"),
                "subagent_id": getattr(handle, "subagent_id", None) or "unknown",
                "session_key": None,  # the lifecycle handle does not expose a child session key
                "goal": goal,
                "mode": mode,
                "status": worker_status,
                "requested_model": target_model,
                "actual_model": None,  # handle records selected route, not actually served model
                "actual_provider": None,
                "summary": summary_text,
                "error": error_text,
                "duration_seconds": duration,
            }
            return worker_summary, None

        except TeamError as te:
            if handle is None:
                confirmed_terminal = True
            elif lifecycle is not None:
                try:
                    lifecycle.cancel(handle, reason=str(te))
                    terminal = lifecycle.wait(handle, timeout_seconds=2.0)
                    confirmed_terminal = bool(terminal.completed)
                except Exception:
                    confirmed_terminal = False
            return None, {"code": te.code, "message": te.message}
        except Exception as exc:
            if handle is not None and lifecycle is not None:
                with contextlib_suppress():
                    lifecycle.cancel(handle, reason=f"Worker exception: {exc}")
                try:
                    term_state = lifecycle.wait(handle, timeout_seconds=2.0)
                    confirmed_terminal = bool(term_state.completed)
                except Exception:
                    confirmed_terminal = False
            else:
                confirmed_terminal = True
            return None, {"code": "worker_execution_failed", "message": str(exc)}
        finally:
            duration = time.time() - start_time
            finish_cb = self._callbacks.get("finished")
            if callable(finish_cb):
                if confirmed_terminal:
                    if result is not None:
                        finish_payload = _to_dict(result)
                        finish_payload["duration_seconds"] = duration
                        term_str = str(
                            result.terminal_state.value
                            if hasattr(result.terminal_state, "value")
                            else result.terminal_state
                        )
                        finish_payload["status"] = {"SUCCEEDED": "completed", "CANCELLED": "cancelled", "INTERRUPTED": "interrupted"}.get(term_str, "failed")
                        finish_payload["summary"] = result.summary
                        finish_payload["error"] = result.error_message
                        finish_payload["actual_model"] = None
                        finish_payload["actual_provider"] = None
                    else:
                        finish_payload = {
                            "status": "failed",
                            "error": "Worker execution terminated abnormally",
                            "duration_seconds": duration,
                        }
                    try:
                        finish_cb(worker_id, finish_payload)
                    except Exception:
                        logger.exception("Error in worker finished callback for worker %s", worker_id)
                else:
                    try:
                        finish_cb(worker_id, {"status": "unknown", "error": "取消未确认，保留并发槽位", "duration_seconds": duration})
                    except Exception:
                        logger.exception("Could not record unknown worker outcome")
                    # Unconfirmed termination: retain slot reservation to prevent spawning excess workers
                    logger.warning(
                        "Worker %s termination unconfirmed; skipping slot release to preserve capacity lock",
                        worker_id,
                    )


class contextlib_suppress:
    """Zero-dependency exception suppressor."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return True
