"""Hermes JSON-RPC runtime adapter for construction team plugin.

Handles profile scoping, request dispatching via server.dispatch with OwnedTransport,
project reuse, session creation/resumption, and event broadcasting.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import logging
import os
from pathlib import Path
import threading
from typing import Any, Callable, Optional
import uuid

logger = logging.getLogger(__name__)

EXPECTED_HERMES_VERSION = "0.21.6"


class HostError(Exception):
    """Hermes JSON-RPC host error with error code and description."""

    def __init__(self, code: Any, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


def _verify_host_compatibility() -> None:
    """Check that host Hermes matches expected version v0.21.6."""
    try:
        from hermes_cli import __version__ as version

        if version != EXPECTED_HERMES_VERSION:
            logger.warning(
                "Host version mismatch: running on %s, expected %s",
                version,
                EXPECTED_HERMES_VERSION,
            )
    except ImportError as exc:
        raise HostError("hermes_not_found", f"Failed to import hermes_cli: {exc}") from exc


def _resolve_active_profile() -> str:
    """Resolve the active profile name, honoring custom and environment without sticky defaults."""
    env_prof = os.environ.get("HERMES_PROFILE")
    if env_prof and env_prof.strip():
        return env_prof.strip()
    try:
        from hermes_constants import get_hermes_home, profile_name_for_home

        name = profile_name_for_home(get_hermes_home())
        if name and str(name).strip():
            return str(name).strip()
    except Exception:
        pass
    return "default"


class OwnedTransport:
    """Minimal transport protocol implementation owned by construction-team adapter.

    Complies with tui_gateway.transport.Transport protocol while tracking pending
    handler futures and broadcasting completion events.
    """

    def __init__(self, owner: str = "construction-team", auth_identity: dict | None = None) -> None:
        self.owner = owner
        self.auth_identity = auth_identity
        self._closed = False
        self._lock = threading.Lock()
        self._pending: dict[str, concurrent.futures.Future[dict[str, Any]]] = {}
        self._event_handlers: list[Callable[[str, str, dict[str, Any]], None]] = []

    @property
    def closed(self) -> bool:
        return self._closed

    def is_closed(self) -> bool:
        return self._closed

    def register_pending(self, req_id: str, future: concurrent.futures.Future[dict[str, Any]]) -> None:
        with self._lock:
            if self._closed:
                future.cancel()
                return
            self._pending[req_id] = future

    def unregister_pending(self, req_id: str) -> Optional[concurrent.futures.Future[dict[str, Any]]]:
        with self._lock:
            return self._pending.pop(req_id, None)

    def add_event_handler(self, handler: Callable[[str, str, dict[str, Any]], None]) -> Callable[[], None]:
        with self._lock:
            self._event_handlers.append(handler)

        def remove():
            with self._lock:
                if handler in self._event_handlers:
                    self._event_handlers.remove(handler)

        return remove

    def write(self, obj: dict) -> bool:
        """Handle outbound JSON-RPC response or notification frame."""
        if self._closed or not isinstance(obj, dict):
            return False

        # 1. Match response by request ID
        req_id = obj.get("id")
        if req_id is not None:
            fut = self.unregister_pending(str(req_id))
            if fut and not fut.done():
                fut.set_result(obj)
                return True

        # 2. Match server event frames (e.g. message.complete, turn.complete)
        if obj.get("method") == "event":
            params = obj.get("params")
            if isinstance(params, dict):
                event_type = params.get("type", "")
                sid = params.get("session_id", "")
                payload = params.get("payload")
                if payload is None:
                    payload = {k: v for k, v in params.items() if k not in ("type", "session_id")}
                with self._lock:
                    handlers = list(self._event_handlers)
                for handler in handlers:
                    try:
                        handler(event_type, sid, payload)
                    except Exception:
                        logger.exception("Error in OwnedTransport event handler")
                return True

        return True

    def close(self) -> None:
        """Close transport and cancel any pending wait futures."""
        with self._lock:
            self._closed = True
            for fut in self._pending.values():
                if not fut.done():
                    fut.cancel()
            self._pending.clear()


class HermesRuntime:
    """Hermes JSON-RPC runtime adapter scoped to a specific profile.

    Dispatches requests through server.dispatch(req, transport=OwnedTransport).
    Never accesses private server._sessions or modifies core functions.
    """

    def __init__(self, profile: Optional[str] = None) -> None:
        _verify_host_compatibility()
        try:
            from hermes_constants import get_hermes_home

            self.hermes_home = str(get_hermes_home())
        except Exception:
            self.hermes_home = os.environ.get("HERMES_HOME", "")

        active_prof = _resolve_active_profile()
        if profile is not None and profile.strip():
            target = profile.strip()
            # Allow matching active profile, or 'custom' / 'default' when safely scoped
            if target != active_prof and target not in ("default", "custom"):
                raise HostError(
                    "profile_forbidden",
                    f"Cross-profile operations forbidden: target profile '{target}' != active profile '{active_prof}'",
                )
            self.profile = target
        else:
            self.profile = active_prof

        self._transport = OwnedTransport(owner=f"construction-team-{self.profile}")
        self._lock = threading.Lock()
        self._completed_callbacks: list[Callable[[str, str, dict[str, Any]], None]] = []
        self._runtime_to_key: dict[str, str] = {}
        self._key_to_runtime: dict[str, str] = {}

        # Wire event listener for message.complete / turn.complete
        self._transport.add_event_handler(self._on_transport_event)

    def _on_transport_event(self, event_type: str, runtime_id: str, payload: dict[str, Any]) -> None:
        if event_type in ("message.complete", "turn.complete"):
            session_key = self._runtime_to_key.get(runtime_id, runtime_id)
            with self._lock:
                callbacks = list(self._completed_callbacks)
            for cb in callbacks:
                try:
                    cb(session_key, runtime_id, payload)
                except Exception:
                    logger.exception("Error in watch_completed callback")

    def call(self, method: str, params: Optional[dict[str, Any]] = None, timeout: float = 60.0) -> dict[str, Any]:
        """Synchronously execute a JSON-RPC method with bounded timeout."""
        _verify_host_compatibility()
        p = dict(params or {})

        # Profile scoping check
        req_profile = p.get("profile")
        from hermes_constants import get_hermes_home
        if str(get_hermes_home().resolve()) != str(Path(self.hermes_home).resolve()):
            raise HostError("profile_forbidden", "当前调用Profile与执行器所属HOME不同")
        if req_profile is not None:
            rp = str(req_profile).strip()
            if rp and rp != self.profile:
                raise HostError(
                    "profile_forbidden",
                    f"Cross-profile parameter forbidden: '{req_profile}' != '{self.profile}'",
                )

        # 'custom' and 'default' rely on current HERMES_HOME context; sending profile='custom'
        # fails with 4064 because 'custom' is not a directory in ~/.hermes/profiles/.
        # Only attach profile param when it is a true distinct named profile.
        if not self.profile or self.profile in ("default", "custom"):
            p.pop("profile", None)
        else:
            p["profile"] = self.profile

        req_id = f"cteam-{uuid.uuid4().hex[:12]}"
        req = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": p,
        }

        fut: concurrent.futures.Future[dict[str, Any]] = concurrent.futures.Future()
        self._transport.register_pending(req_id, fut)

        try:
            from tui_gateway import server

            dispatch_fn = getattr(server, "dispatch", None)
            if not callable(dispatch_fn):
                from tui_gateway.rpc_dispatch import dispatch as dispatch_fn
            direct_resp = dispatch_fn(req, transport=self._transport)
            if direct_resp is not None:
                # Synchronous / inline method response
                self._transport.unregister_pending(req_id)
                resp = direct_resp
            else:
                # Asynchronous pool-dispatched handler; await transport.write frame
                try:
                    resp = fut.result(timeout=timeout)
                except concurrent.futures.TimeoutError as exc:
                    self._transport.unregister_pending(req_id)
                    raise HostError(
                        "timeout",
                        f"JSON-RPC method '{method}' (id={req_id}) timed out after {timeout}s",
                    ) from exc
                except concurrent.futures.CancelledError as exc:
                    self._transport.unregister_pending(req_id)
                    raise HostError("cancelled", f"Request {method} (id={req_id}) was cancelled") from exc

            if not isinstance(resp, dict):
                raise HostError("invalid_response", f"Expected dict response for {method}, got {type(resp)}")

            if resp.get("error"):
                err = resp["error"]
                if isinstance(err, dict):
                    code = err.get("code", "unknown")
                    msg = err.get("message", "RPC error")
                else:
                    code = "unknown"
                    msg = str(err)
                raise HostError(code, msg)

            result = resp.get("result")
            if result is None:
                return {}
            if isinstance(result, dict):
                return result
            return {"value": result}
        except HostError:
            raise
        except Exception as exc:
            raise HostError("dispatch_failed", f"Failed dispatching {method}: {exc}") from exc

    async def rpc(self, method: str, params: Optional[dict[str, Any]] = None, timeout: float = 60.0) -> dict[str, Any]:
        """Asynchronously dispatch JSON-RPC off the asyncio event loop thread with context copy."""
        ctx = contextvars.copy_context()
        return await asyncio.to_thread(ctx.run, self.call, method, params, timeout)

    def create_project(self, name: str, root: str) -> dict[str, Any]:
        """Create or reuse a project for the given root directory without switching active project."""
        resolved_root = str(Path(root).resolve())

        # 1. Query bound cwd reuse via projects.for_cwd without swallowing RPC errors
        cwd_res = self.call("projects.for_cwd", {"cwd": resolved_root})
        proj = cwd_res.get("project")
        if isinstance(proj, dict) and proj.get("id"):
            return proj

        # 2. Create fresh project with use=False so active project is NOT switched
        params = {
            "name": name,
            "folders": [resolved_root],
            "primary_path": resolved_root,
            "use": False,
        }
        res = self.call("projects.create", params)
        proj = res.get("project")
        if isinstance(proj, dict) and proj.get("id"):
            return proj
        if isinstance(res, dict) and "id" in res:
            return res
        raise HostError("create_project_failed", f"Could not create or find project for root '{root}'")

    def add_project_folder(self, project_id: str, path: str, label: Optional[str] = None) -> None:
        """Add a folder to an existing project."""
        resolved_path = str(Path(path).resolve())
        params: dict[str, Any] = {
            "id": project_id,
            "path": resolved_path,
            "label": label,
            "is_primary": False,
        }
        self.call("projects.add_folder", params)

    def create_session(
        self,
        cwd: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        parent_key: Optional[str] = None,
        title: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Mint a live ordinary session; durable DB row appears upon prompt submission."""
        resolved_cwd = str(Path(cwd).resolve())
        params: dict[str, Any] = {
            "cwd": resolved_cwd,
            "cwd_explicit": True,
            "source": "construction-team",
            "messages": [{"role": "user", "content": f"施工团队角色会话：{title or '未命名角色'}。等待明确任务书；这条分配记录不是施工结果。", "display_kind": "hidden"}],
        }
        if model:
            params["model"] = model
        if provider:
            params["provider"] = provider
        if parent_key:
            params["parent_session_id"] = parent_key
        if title:
            params["title"] = title
        if idempotency_key:
            params["idempotency_key"] = idempotency_key

        res = self.call("session.create", params)
        runtime_id = res.get("session_id")
        if not runtime_id:
            raise HostError("create_session_failed", "No session_id returned from session.create")

        stored_key = res.get("stored_session_id")
        if not isinstance(stored_key, str) or not stored_key:
            raise HostError("create_session_failed", "宿主没有返回持久会话标识，不能用runtime ID伪装可恢复会话")
        if title:
            # Native branch seeding derives a title from its parent; explicitly
            # set the requested role title through the public method afterwards.
            assigned = self.call('session.title', {'session_id': runtime_id, 'title': title})
            if assigned.get('title') != title or assigned.get('pending') is True:
                raise HostError('session_title_failed', '宿主没有持久化指定角色会话标题')
        info = res.get("info") or {}
        # Session route metadata is not evidence of a served model. If the
        # host omits it, keep it unknown rather than copying the request.
        session_model = info.get("model")
        session_provider = info.get("provider")

        with self._lock:
            self._runtime_to_key[runtime_id] = stored_key
            self._key_to_runtime[stored_key] = runtime_id

        return {
            "session_key": stored_key,
            "runtime_id": runtime_id,
            "model": session_model,
            "provider": session_provider,
        }

    def resume_session(self, session_key: str, cwd: Optional[str] = None) -> dict[str, Any]:
        """Resume an existing session key with lazy=True to prevent automatic execution of old prompts."""
        params: dict[str, Any] = {
            "session_id": session_key,
            "lazy": True,
        }
        res = self.call("session.resume", params)
        runtime_id = res.get("session_id")
        if not runtime_id:
            raise HostError("resume_session_failed", f"No session_id returned when resuming {session_key}")

        stored_key = res.get("session_key") or res.get("resumed") or res.get("stored_session_id") or session_key
        info = res.get("info") or {}
        actual_model = info.get("model")
        actual_provider = info.get("provider")

        if cwd:
            resolved_cwd = str(Path(cwd).resolve())
            try:
                self.call(
                    "session.cwd.set",
                    {"session_id": runtime_id, "cwd": resolved_cwd},
                )
            except Exception:
                pass

        with self._lock:
            self._runtime_to_key[runtime_id] = stored_key
            self._key_to_runtime[stored_key] = runtime_id

        out = {
            "session_key": stored_key,
            "runtime_id": runtime_id,
            "model": actual_model,
            "provider": actual_provider,
        }
        if "auto_continue" in res:
            out["auto_continue"] = res["auto_continue"]
        return out

    def submit(self, runtime_id: str, text: str, queued: bool = True) -> dict[str, Any]:
        """Submit a prompt turn to the live session."""
        params: dict[str, Any] = {
            "session_id": runtime_id,
            "text": text,
            "queued": bool(queued),
        }
        return self.call("prompt.submit", params)

    def steer(self, runtime_id: str, text: str) -> dict[str, Any]:
        """Steer a busy running turn; if steer is rejected or unsupported, fall back to queued submit."""
        params: dict[str, Any] = {
            "session_id": runtime_id,
            "text": text,
        }
        try:
            res = self.call("session.steer", params)
            if isinstance(res, dict) and res.get("status") == "rejected":
                return self.submit(runtime_id, text, queued=True)
            return res
        except HostError as err:
            if err.code in (4010, -32601):
                return self.submit(runtime_id, text, queued=True)
            raise

    def interrupt(self, runtime_id: str) -> dict[str, Any]:
        """Interrupt an in-flight session turn."""
        params: dict[str, Any] = {
            "session_id": runtime_id,
        }
        return self.call("session.interrupt", params)

    def set_title(self, runtime_id: str, title: str) -> dict[str, Any]:
        """Persist session title via session.title RPC."""
        params: dict[str, Any] = {
            "session_id": runtime_id,
            "title": title,
        }
        return self.call("session.title", params)

    def watch_completed(self, callback: Callable[[str, str, dict[str, Any]], None]) -> Callable[[], None]:
        """Register a callback for turn completion: callback(session_key, runtime_id, payload).

        Returns a disposer callable to unregister.
        """
        with self._lock:
            self._completed_callbacks.append(callback)

        def dispose():
            with self._lock:
                if callback in self._completed_callbacks:
                    self._completed_callbacks.remove(callback)

        return dispose

    def close(self) -> None:
        """Release adapter resources."""
        self._transport.close()
