"""Owned, non-destructive workspaces. A directory is not a security sandbox."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .store import TeamError


def _git(path: Path, *args: str, allow_failure: bool = False) -> str:
    try:
        completed = subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                                   text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TeamError("git_failed", str(exc)) from exc
    if completed.returncode and not allow_failure:
        raise TeamError("git_failed", completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip() if completed.returncode == 0 else ""


def is_git_repo(path: Path | str) -> bool:
    root = Path(path).resolve(strict=True)
    return _git(root, "rev-parse", "--is-inside-work-tree", allow_failure=True) == "true"


def get_head_commit(path: Path | str) -> str | None:
    return _git(Path(path), "rev-parse", "--verify", "HEAD", allow_failure=True) or None


def is_workspace_dirty(path: Path | str) -> bool:
    root = Path(path).resolve(strict=True)
    if is_git_repo(root):
        return bool(_git(root, "status", "--porcelain", "--untracked-files=all"))
    return any(root.iterdir())


def prepare_member_workspace(root: Path | str, member_id: str, member_name: str = "",
                             state_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise TeamError("root_not_found", "项目路径不是目录")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", member_id):
        raise TeamError("invalid_member_id", "成员标识不是安全目录名")
    if state_root is None:
        from hermes_constants import get_hermes_home
        state_root = get_hermes_home() / "construction-team" / "workspaces"
    owned_root = Path(state_root).resolve()
    # The caller chooses the owned state area, never a member-supplied absolute path.
    target = owned_root / member_id
    if target.exists() or target.is_symlink():
        raise TeamError("workspace_exists", "工区已存在；保留现场，不自动复用或删除")
    if owned_root.is_symlink() or target.resolve().parent != owned_root:
        raise TeamError("unsafe_path", "工区路径越界")
    git = is_git_repo(root)
    base = None
    if git:
        top = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
        if top != root:
            raise TeamError("invalid_project_root", "请使用仓库根目录，不能以仓库子目录创建工区")
        base = get_head_commit(root)
        if not base:
            raise TeamError("missing_head", "仓库还没有有效提交；不能把空仓库当作scratch悄悄执行")
        if is_workspace_dirty(root):
            raise TeamError("workspace_dirty", "原仓库存在未提交或未跟踪文件；请先选择干净基线")
    owned_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if git:
        assert base is not None
        _git(root, "worktree", "add", "--detach", str(target), base)
        if not target.is_dir() or get_head_commit(target) != base:
            raise TeamError("worktree_create_failed", "真实worktree没有到达指定基线；现场保留")
    else:
        target.mkdir(mode=0o700)
    marker = owned_root / f".{member_id}.owner.json"
    marker.write_text(json.dumps({"root": str(root), "workspace": str(target), "base_commit": base,
                                 "is_git": git}, ensure_ascii=False), encoding="utf-8")
    return {"workspace": str(target), "base_commit": base, "is_git": git,
            "limitation": "scratch工区不自动复制项目文件" if not git else None}


def remove_member_workspace(root: Path | str, workspace: Path | str, force: bool = False) -> bool:
    # v0.1 intentionally never deletes user-produced material. Stop and uninstall
    # preserve all worktrees; explicit manual archival/removal is a separate action.
    raise TeamError("cleanup_not_supported", "首版不自动删除工区；请核对并归档成果后另行处理")
