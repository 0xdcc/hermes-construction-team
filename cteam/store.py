"""SQLite store for Hermes construction-team plugin.

Provides atomic transactions, idempotency tracking via request_key,
and snapshots for teams, members, tasks, workers, events, and outbox.
"""
from __future__ import annotations

import functools
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional


class TeamError(Exception):
    """Domain error with specific machine code and human message."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


class Store:
    """Atomic SQLite store for construction teams."""

    def __init__(self, db_path: Path | str):
        if str(db_path) == ":memory:":
            self._db_path = ":memory:"
        else:
            p = Path(db_path).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            self._db_path = str(p)

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self._db_path,
            timeout=10.0,
            check_same_thread=False,
            isolation_level=None,  # autocommit / manual transaction control
        )
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA busy_timeout = 5000;")
            self._conn.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self._conn.execute("CREATE TABLE IF NOT EXISTS operations (request_key TEXT PRIMARY KEY, team_id TEXT NOT NULL, operation TEXT NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL, response TEXT, error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS teams (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    root TEXT NOT NULL,
                    project_id TEXT,
                    coordinator_key TEXT,
                    coordinator_runtime_id TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    settings TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS members (
                    id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    model TEXT NOT NULL,
                    provider TEXT,
                    session_key TEXT,
                    runtime_id TEXT,
                    workspace TEXT NOT NULL,
                    base_commit TEXT,
                    status TEXT NOT NULL DEFAULT 'idle',
                    actual_model TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (team_id) REFERENCES teams(id)
                );
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    member_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    acceptance TEXT NOT NULL,
                    forbidden TEXT NOT NULL,
                    depends_on TEXT NOT NULL,
                    request_key TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt INTEGER NOT NULL DEFAULT 1,
                    marker TEXT NOT NULL,
                    report TEXT,
                    actual_model TEXT,
                    evidence TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (team_id) REFERENCES teams(id),
                    FOREIGN KEY (member_id) REFERENCES members(id)
                );
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS workers (
                    id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    member_id TEXT NOT NULL,
                    task_id TEXT,
                    subagent_id TEXT,
                    session_key TEXT,
                    goal TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    requested_model TEXT NOT NULL,
                    actual_model TEXT,
                    actual_provider TEXT,
                    summary TEXT,
                    error TEXT,
                    duration_seconds REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (team_id) REFERENCES teams(id),
                    FOREIGN KEY (member_id) REFERENCES members(id)
                );
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS worker_slots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    team_id TEXT NOT NULL,
                    member_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'acquired',
                    acquired_at REAL NOT NULL
                );
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (team_id) REFERENCES teams(id)
                );
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    payload TEXT NOT NULL,
                    last_error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (team_id) REFERENCES teams(id)
                );
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS request_logs (
                    request_key TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_members_team ON members(team_id);")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_team ON tasks(team_id);")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_member ON tasks(member_id);")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_marker ON tasks(marker);")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_req ON tasks(request_key);")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_workers_team ON workers(team_id);")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_team ON events(team_id);")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_outbox_team ON outbox(team_id);")

    def close(self) -> None:
        self._conn.close()

    def begin_operation(self, request_key: str | None, team_id: str, operation: str, payload: dict) -> dict | None:
        if not request_key:
            return None
        fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
        now = time.time()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute("SELECT * FROM operations WHERE request_key = ?", (request_key,)).fetchone()
            if row:
                if row["team_id"] != team_id or row["operation"] != operation or row["fingerprint"] != fingerprint:
                    raise TeamError("idempotency_conflict", "同一请求标识对应不同操作或参数")
                if row["state"] == "done":
                    result = json.loads(row["response"])
                    self._conn.execute("COMMIT")
                    return result
                raise TeamError("request_needs_reconcile", f"请求状态为{row['state']}，可能已经执行；禁止自动重放")
            self._conn.execute("INSERT INTO operations VALUES (?, ?, ?, ?, 'started', NULL, NULL, ?, ?)",
                               (request_key, team_id, operation, fingerprint, now, now))
            self._conn.execute("COMMIT")
            return None
        except Exception:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def finish_operation(self, request_key: str | None, result: dict | None = None, error: str | None = None) -> None:
        if not request_key:
            return
        self._conn.execute("UPDATE operations SET state = ?, response = ?, error = ?, updated_at = ? WHERE request_key = ?",
                           ("failed" if error else "done", json.dumps(result, ensure_ascii=False) if result else None,
                            error, time.time(), request_key))

    def claim_process(self, process_key: str) -> bool:
        row = self._conn.execute("SELECT value FROM metadata WHERE key='process_owner'").fetchone()
        previous = row[0] if row else None
        self._conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES ('process_owner',?)", (process_key,))
        return previous == process_key

    def count_worker_slots(self, team_id: str) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM worker_slots WHERE team_id=?", (team_id,)).fetchone()[0]

    def clear_worker_slots(self, team_id: str) -> None:
        self._conn.execute("DELETE FROM worker_slots WHERE team_id = ?", (team_id,))

    def mark_orphaned_operations(self) -> None:
        self._conn.execute("UPDATE operations SET state='unknown', error='执行进程中断，需核对现场', updated_at=? WHERE state IN ('started','running')", (time.time(),))

    # --- Request Idempotency ---

    def get_request_log(self, request_key: str) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM request_logs WHERE request_key = ?",
            (request_key,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "request_key": row["request_key"],
            "team_id": row["team_id"],
            "operation": row["operation"],
            "response": json.loads(row["response_json"]),
            "created_at": row["created_at"],
        }

    def log_request(self, request_key: str, team_id: str, operation: str, response: dict[str, Any]) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO request_logs (request_key, team_id, operation, response_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (request_key, team_id, operation, json.dumps(response, ensure_ascii=False), time.time()),
            )

    # --- Team CRUD ---

    def create_team(self, data: dict[str, Any]) -> dict[str, Any]:
        team_id = data.get("id") or f"team_{uuid.uuid4().hex[:8]}"
        now = time.time()
        settings_json = json.dumps(data.get("settings", {}), ensure_ascii=False)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO teams (id, name, root, project_id, coordinator_key, coordinator_runtime_id, status, settings, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    team_id,
                    data["name"],
                    str(data["root"]),
                    data.get("project_id"),
                    data.get("coordinator_key"),
                    data.get("coordinator_runtime_id"),
                    data.get("status", "active"),
                    settings_json,
                    now,
                    now,
                ),
            )
        team = self.get_team(team_id)
        if not team:
            raise TeamError("team_create_failed", f"Failed to retrieve created team {team_id}")
        return team

    def get_team(self, team_id: str) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_team(row)

    def list_teams(self) -> list[dict[str, Any]]:
        cursor = self._conn.execute("SELECT * FROM teams ORDER BY created_at DESC")
        return [self._row_to_team(r) for r in cursor.fetchall()]

    def update_team(self, team_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {"name", "root", "project_id", "coordinator_key", "coordinator_runtime_id", "status", "settings"}
        cols = []
        vals = []
        for k, v in updates.items():
            if k in allowed:
                cols.append(f"{k} = ?")
                vals.append(json.dumps(v, ensure_ascii=False) if k == "settings" else v)
        if not cols:
            team = self.get_team(team_id)
            if not team:
                raise TeamError("team_not_found", f"Team {team_id} not found")
            return team

        cols.append("updated_at = ?")
        vals.append(time.time())
        vals.append(team_id)

        with self._conn:
            self._conn.execute(
                f"UPDATE teams SET {', '.join(cols)} WHERE id = ?",
                vals,
            )
        team = self.get_team(team_id)
        if not team:
            raise TeamError("team_not_found", f"Team {team_id} not found")
        return team

    def _row_to_team(self, row: sqlite3.Row) -> dict[str, Any]:
        settings = {}
        if row["settings"]:
            try:
                settings = json.loads(row["settings"])
            except Exception:
                pass
        return {
            "id": row["id"],
            "name": row["name"],
            "root": row["root"],
            "project_id": row["project_id"],
            "coordinator_key": row["coordinator_key"],
            "coordinator_runtime_id": row["coordinator_runtime_id"],
            "status": row["status"],
            "settings": settings,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # --- Member CRUD ---

    def create_member(self, data: dict[str, Any]) -> dict[str, Any]:
        member_id = data.get("id") or f"m_{uuid.uuid4().hex[:8]}"
        now = time.time()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO members (id, team_id, name, role, model, provider, session_key, runtime_id, workspace, base_commit, status, actual_model, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    member_id,
                    data["team_id"],
                    data["name"],
                    data.get("role", "supervisor"),
                    data["model"],
                    data.get("provider"),
                    data.get("session_key"),
                    data.get("runtime_id"),
                    str(data["workspace"]),
                    data.get("base_commit"),
                    data.get("status", "idle"),
                    data.get("actual_model"),
                    now,
                    now,
                ),
            )
        member = self.get_member(member_id)
        if not member:
            raise TeamError("member_create_failed", f"Failed to retrieve member {member_id}")
        return member

    def get_member(self, member_id: str) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute("SELECT * FROM members WHERE id = ?", (member_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_member(row)

    def find_member_by_session(self, session_key_or_id: str) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM members WHERE session_key = ? OR runtime_id = ?",
            (session_key_or_id, session_key_or_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_member(row)

    def list_members(self, team_id: str) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM members WHERE team_id = ? ORDER BY created_at ASC",
            (team_id,),
        )
        return [self._row_to_member(r) for r in cursor.fetchall()]

    def update_member(self, member_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {"name", "role", "model", "provider", "session_key", "runtime_id", "workspace", "base_commit", "status", "actual_model"}
        cols = []
        vals = []
        for k, v in updates.items():
            if k in allowed:
                cols.append(f"{k} = ?")
                vals.append(v)
        if not cols:
            member = self.get_member(member_id)
            if not member:
                raise TeamError("member_not_found", f"Member {member_id} not found")
            return member

        cols.append("updated_at = ?")
        vals.append(time.time())
        vals.append(member_id)

        with self._conn:
            self._conn.execute(
                f"UPDATE members SET {', '.join(cols)} WHERE id = ?",
                vals,
            )
        member = self.get_member(member_id)
        if not member:
            raise TeamError("member_not_found", f"Member {member_id} not found")
        return member

    def _row_to_member(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "team_id": row["team_id"],
            "name": row["name"],
            "role": row["role"],
            "model": row["model"],
            "provider": row["provider"],
            "session_key": row["session_key"],
            "runtime_id": row["runtime_id"],
            "workspace": row["workspace"],
            "base_commit": row["base_commit"],
            "status": row["status"],
            "actual_model": row["actual_model"],
        }

    # --- Task CRUD ---

    def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        task_id = data.get("id") or f"t_{uuid.uuid4().hex[:8]}"
        now = time.time()
        acceptance_json = json.dumps(data.get("acceptance", []), ensure_ascii=False)
        forbidden_json = json.dumps(data.get("forbidden", []), ensure_ascii=False)
        depends_on_json = json.dumps(data.get("depends_on", []), ensure_ascii=False)
        evidence_json = json.dumps(data.get("evidence", []), ensure_ascii=False)

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO tasks (
                    id, team_id, member_id, title, goal, acceptance, forbidden,
                    depends_on, request_key, status, attempt, marker, report,
                    actual_model, evidence, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    data["team_id"],
                    data["member_id"],
                    data["title"],
                    data["goal"],
                    acceptance_json,
                    forbidden_json,
                    depends_on_json,
                    data.get("request_key"),
                    data.get("status", "pending"),
                    int(data.get("attempt", 1)),
                    data["marker"],
                    data.get("report"),
                    data.get("actual_model"),
                    evidence_json,
                    now,
                    now,
                ),
            )
        task = self.get_task(task_id)
        if not task:
            raise TeamError("task_create_failed", f"Failed to retrieve task {task_id}")
        return task

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_task(row)

    def find_task_by_marker(self, marker: str) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute("SELECT * FROM tasks WHERE marker = ?", (marker,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_task(row)

    def find_task_by_request_key(self, request_key: str) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute("SELECT * FROM tasks WHERE request_key = ?", (request_key,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_task(row)

    def list_tasks(self, team_id: str) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM tasks WHERE team_id = ? ORDER BY created_at ASC",
            (team_id,),
        )
        return [self._row_to_task(r) for r in cursor.fetchall()]

    def list_tasks_for_member(self, member_id: str) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM tasks WHERE member_id = ? ORDER BY created_at ASC",
            (member_id,),
        )
        return [self._row_to_task(r) for r in cursor.fetchall()]

    def update_task(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "goal", "acceptance", "forbidden", "depends_on", "status", "attempt", "marker", "report", "actual_model", "evidence"}
        cols = []
        vals = []
        for k, v in updates.items():
            if k in allowed:
                cols.append(f"{k} = ?")
                if k in {"acceptance", "forbidden", "depends_on", "evidence"} and isinstance(v, list):
                    vals.append(json.dumps(v, ensure_ascii=False))
                else:
                    vals.append(v)
        if not cols:
            task = self.get_task(task_id)
            if not task:
                raise TeamError("task_not_found", f"Task {task_id} not found")
            return task

        cols.append("updated_at = ?")
        vals.append(time.time())
        vals.append(task_id)

        with self._conn:
            self._conn.execute(
                f"UPDATE tasks SET {', '.join(cols)} WHERE id = ?",
                vals,
            )
        task = self.get_task(task_id)
        if not task:
            raise TeamError("task_not_found", f"Task {task_id} not found")
        return task

    def _row_to_task(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "team_id": row["team_id"],
            "member_id": row["member_id"],
            "title": row["title"],
            "goal": row["goal"],
            "acceptance": json.loads(row["acceptance"]) if row["acceptance"] else [],
            "forbidden": json.loads(row["forbidden"]) if row["forbidden"] else [],
            "depends_on": json.loads(row["depends_on"]) if row["depends_on"] else [],
            "request_key": row["request_key"],
            "status": row["status"],
            "attempt": row["attempt"],
            "marker": row["marker"],
            "report": row["report"],
            "actual_model": row["actual_model"],
            "evidence": json.loads(row["evidence"]) if row["evidence"] else [],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # --- Worker CRUD & Slot Concurrency ---

    def create_worker(self, data: dict[str, Any]) -> dict[str, Any]:
        worker_id = data.get("id") or f"w_{uuid.uuid4().hex[:8]}"
        now = time.time()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO workers (
                    id, team_id, member_id, task_id, subagent_id, session_key,
                    goal, mode, status, requested_model, actual_model,
                    actual_provider, summary, error, duration_seconds,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    worker_id,
                    data["team_id"],
                    data["member_id"],
                    data.get("task_id"),
                    data.get("subagent_id"),
                    data.get("session_key"),
                    data["goal"],
                    data.get("mode", "read"),
                    data.get("status", "pending"),
                    data["requested_model"],
                    data.get("actual_model"),
                    data.get("actual_provider"),
                    data.get("summary"),
                    data.get("error"),
                    data.get("duration_seconds"),
                    now,
                    now,
                ),
            )
        worker = self.get_worker(worker_id)
        if not worker:
            raise TeamError("worker_create_failed", f"Failed to retrieve worker {worker_id}")
        return worker

    def get_worker(self, worker_id: str) -> Optional[dict[str, Any]]:
        cursor = self._conn.execute("SELECT * FROM workers WHERE id = ?", (worker_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_worker(row)

    def find_worker_by_session(self, session_key: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM workers WHERE session_key=? ORDER BY created_at DESC LIMIT 1", (session_key,)).fetchone()
        return self._row_to_worker(row) if row else None

    def list_workers(self, team_id: str) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM workers WHERE team_id = ? ORDER BY created_at ASC",
            (team_id,),
        )
        return [self._row_to_worker(r) for r in cursor.fetchall()]

    def update_worker(self, worker_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {"subagent_id", "session_key", "status", "actual_model", "actual_provider", "summary", "error", "duration_seconds"}
        cols = []
        vals = []
        for k, v in updates.items():
            if k in allowed:
                cols.append(f"{k} = ?")
                vals.append(v)
        if not cols:
            worker = self.get_worker(worker_id)
            if not worker:
                raise TeamError("worker_not_found", f"Worker {worker_id} not found")
            return worker

        cols.append("updated_at = ?")
        vals.append(time.time())
        vals.append(worker_id)

        with self._conn:
            self._conn.execute(
                f"UPDATE workers SET {', '.join(cols)} WHERE id = ?",
                vals,
            )
        worker = self.get_worker(worker_id)
        if not worker:
            raise TeamError("worker_not_found", f"Worker {worker_id} not found")
        return worker

    def _row_to_worker(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "team_id": row["team_id"],
            "member_id": row["member_id"],
            "task_id": row["task_id"],
            "subagent_id": row["subagent_id"],
            "session_key": row["session_key"],
            "goal": row["goal"],
            "mode": row["mode"],
            "status": row["status"],
            "requested_model": row["requested_model"],
            "actual_model": row["actual_model"],
            "actual_provider": row["actual_provider"],
            "summary": row["summary"],
            "error": row["error"],
            "duration_seconds": row["duration_seconds"],
        }

    # --- Atomic Worker Slot Acquisition ---

    def acquire_worker_slot(self, team_id: str, member_id: str, mode: str, max_workers: int) -> int:
        """Atomically acquire a concurrency slot in SQLite.

        Rules:
        - Total active slots across the team cannot exceed max_workers.
        - For mode == 'write', only 1 active write worker is permitted per member/workspace.
        """
        with self._conn:
            # 1. Check total active slots for team
            cur = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM worker_slots WHERE team_id = ? AND status = 'acquired'",
                (team_id,),
            )
            total_active = cur.fetchone()["cnt"]
            if total_active >= max_workers:
                raise TeamError(
                    "worker_limit_reached",
                    f"Team active worker limit ({max_workers}) reached (current active: {total_active})",
                )

            # 2. Check single-writer constraint for member
            if mode == "write":
                cur_write = self._conn.execute(
                    "SELECT COUNT(*) AS cnt FROM worker_slots WHERE member_id = ? AND mode = 'write' AND status = 'acquired'",
                    (member_id,),
                )
                active_writes = cur_write.fetchone()["cnt"]
                if active_writes > 0:
                    raise TeamError(
                        "write_slot_busy",
                        f"Member {member_id} already has an active write worker ({active_writes} running)",
                    )

            # 3. Insert slot
            cursor = self._conn.execute(
                """
                INSERT INTO worker_slots (team_id, member_id, mode, status, acquired_at)
                VALUES (?, ?, ?, 'acquired', ?)
                """,
                (team_id, member_id, mode, time.time()),
            )
            return int(cursor.lastrowid or 0)

    def release_worker_slot(self, slot_id: int) -> None:
        """Atomically release an acquired slot."""
        with self._conn:
            self._conn.execute("DELETE FROM worker_slots WHERE id = ?", (slot_id,))

    def count_active_worker_slots(self, team_id: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM worker_slots WHERE team_id = ? AND status = 'acquired'",
            (team_id,),
        )
        return cur.fetchone()["cnt"]

    # --- Event Logging ---

    def add_event(self, team_id: str, kind: str, message: str) -> dict[str, Any]:
        event_id = f"ev_{uuid.uuid4().hex[:8]}"
        now = time.time()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO events (id, team_id, kind, message, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event_id, team_id, kind, message, now),
            )
        return {"id": event_id, "team_id": team_id, "kind": kind, "message": message, "created_at": now}

    def list_events(self, team_id: str, limit: int = 100) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM events WHERE team_id = ? ORDER BY created_at DESC LIMIT ?",
            (team_id, limit),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": r["id"],
                "team_id": r["team_id"],
                "kind": r["kind"],
                "message": r["message"],
                "created_at": r["created_at"],
            }
            for r in reversed(rows)
        ]

    # --- Outbox ---

    def enqueue_outbox(self, team_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        outbox_id = f"out_{uuid.uuid4().hex[:8]}"
        now = time.time()
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO outbox (id, team_id, kind, status, payload, last_error, attempts, created_at, updated_at)
                VALUES (?, ?, ?, 'pending', ?, NULL, 0, ?, ?)
                """,
                (outbox_id, team_id, kind, payload_json, now, now),
            )
        return {
            "id": outbox_id,
            "team_id": team_id,
            "kind": kind,
            "status": "pending",
            "payload": payload,
            "last_error": None,
            "attempts": 0,
            "created_at": now,
            "updated_at": now,
        }

    def list_outbox(self, team_id: str) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM outbox WHERE team_id = ? ORDER BY created_at ASC",
            (team_id,),
        )
        items = []
        for r in cursor.fetchall():
            payload = {}
            if r["payload"]:
                try:
                    payload = json.loads(r["payload"])
                except Exception:
                    pass
            items.append({
                "id": r["id"],
                "team_id": r["team_id"],
                "kind": r["kind"],
                "status": r["status"],
                "payload": payload,
                "last_error": r["last_error"],
                "attempts": r["attempts"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            })
        return items

    def list_pending_outbox(self, team_id: Optional[str] = None) -> list[dict[str, Any]]:
        if team_id:
            cursor = self._conn.execute(
                "SELECT * FROM outbox WHERE team_id = ? AND status IN ('pending', 'failed') ORDER BY created_at ASC",
                (team_id,),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM outbox WHERE status IN ('pending', 'failed') ORDER BY created_at ASC",
            )
        items = []
        for r in cursor.fetchall():
            payload = {}
            if r["payload"]:
                try:
                    payload = json.loads(r["payload"])
                except Exception:
                    pass
            items.append({
                "id": r["id"],
                "team_id": r["team_id"],
                "kind": r["kind"],
                "status": r["status"],
                "payload": payload,
                "last_error": r["last_error"],
                "attempts": r["attempts"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            })
        return items

    def update_outbox(self, item_id: str, status: str, last_error: Optional[str] = None) -> None:
        now = time.time()
        with self._conn:
            self._conn.execute(
                """
                UPDATE outbox
                SET status = ?, last_error = ?, attempts = attempts + 1, updated_at = ?
                WHERE id = ?
                """,
                (status, last_error, now, item_id),
            )

    # --- Snapshot ---

    def snapshot(self, team_id: str) -> dict[str, Any]:
        team = self.get_team(team_id)
        if not team:
            raise TeamError("team_not_found", f"Team {team_id} not found")

        members = self.list_members(team_id)
        tasks = self.list_tasks(team_id)
        workers = self.list_workers(team_id)
        events = self.list_events(team_id)
        outbox_items = self.list_outbox(team_id)

        # Build warnings
        warnings: list[str] = []
        if team["status"] == "paused":
            warnings.append("团队已处于暂停状态，停止新增任务派发")
        elif team["status"] == "stopped":
            warnings.append("团队已停止新增执行；正在取消的任务以各自状态为准，成果保留")
        elif team["status"] == "needs_reconcile":
            warnings.append("团队经历中断或未对账状态，需要显式核对现场")

        for ob in outbox_items:
            if ob["status"] == "failed":
                warnings.append(f"回传待发队列项 {ob['id']} 发送失败: {ob['last_error'] or '未知原因'}")

        # format outbox items for snapshot
        outbox_clean = [
            {
                "id": o["id"],
                "kind": o["kind"],
                "status": o["status"],
                "last_error": o["last_error"],
            }
            for o in outbox_items
        ]

        return {
            "team": team,
            "members": members,
            "tasks": tasks,
            "workers": workers,
            "events": events,
            "outbox": outbox_clean,
            "warnings": warnings,
        }


def _serialized(method):
    @functools.wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


# A single SQLite connection is shared within one profile; never interleave its
# manual transactions across threads. The service never holds this lock over LLM work.
for _method_name, _method in tuple(vars(Store).items()):
    if callable(_method) and _method_name != "__init__":
        setattr(Store, _method_name, _serialized(_method))
