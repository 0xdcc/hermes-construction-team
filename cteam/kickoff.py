"""In-chat kickoff: resolve spoken model names, prepare a project root, build a confirm card.

Nothing here creates sessions, calls models or writes config. ``plan`` is a pure preview;
the coordinator still calls ``create`` / ``add_supervisor`` / ``dispatch`` after the user
explicitly confirms the card in the same chat.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from .store import TeamError

ROLES = ("supervisor", "worker", "advisor")
DEFAULT_PROJECTS_BASE = Path.home() / "projects"


def projects_base(settings: Optional[dict[str, Any]] = None) -> Path:
    """Configured ``projects_base`` (plugins.entries.construction-team.projects_base), else ~/projects."""
    value = (settings or {}).get("projects_base")
    if isinstance(value, str) and value.strip():
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise TeamError("invalid_settings", "projects_base必须是绝对路径")
        return path
    return DEFAULT_PROJECTS_BASE
_SAFE_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SPLIT = re.compile(r"[\s/_.:\-]+")
# Common spoken aliases → tokens that must all appear in the real model id.
_ALIASES = {
    "opus": ["opus"], "sonnet": ["sonnet"], "haiku": ["haiku"], "claude": ["claude"],
    "gemini": ["gemini"], "flash": ["flash"], "gpt": ["gpt"], "sol": ["sol"], "astra": ["astra"],
    "qwen": ["qwen"], "glm": ["glm"], "deepseek": ["deepseek"], "ds": ["deepseek"],
    "混元": ["hy"], "hy": ["hy"],
}


def _tokens(text: str) -> list[str]:
    return [t for t in _SPLIT.split(text.lower()) if t]


def resolve_model(spoken: Any, catalog: list[dict[str, Any]]) -> dict[str, Any]:
    """Map a spoken model name to exactly one catalog entry, or return honest candidates.

    Result: ``{status: exact|resolved|ambiguous|not_found, input, model?, provider?, candidates}``.
    Never invents a model id; an ambiguous or unknown name must be confirmed by the user.
    """
    if not isinstance(spoken, str) or not spoken.strip():
        raise TeamError("invalid_payload", "模型名称必须为非空文字")
    raw = spoken.strip()
    provider_hint = None
    if "@" in raw:  # "model-id@provider-name"
        raw, provider_hint = (part.strip() for part in raw.split("@", 1))
    entries = [e for e in catalog if e.get("model")]
    if provider_hint:
        entries = [e for e in entries if (e.get("provider") or "").lower() == provider_hint.lower()]

    def pack(status, chosen=None, candidates=()):
        out = {"status": status, "input": spoken, "candidates": [
            {"model": c["model"], "provider": c.get("provider")} for c in candidates]}
        if chosen:
            out.update(model=chosen["model"], provider=chosen.get("provider"))
        return out

    exact = [e for e in entries if e["model"] == raw]
    if not exact:
        exact = [e for e in entries if e["model"].lower() == raw.lower()]
    if exact:
        # Same id on several providers: keep the id, provider stays a user choice (None = inherit).
        providers = {e.get("provider") for e in exact}
        chosen = exact[0] if len(providers) == 1 else {"model": exact[0]["model"], "provider": None}
        return pack("exact", chosen, exact if len(providers) > 1 else ())

    wanted: list[str] = []
    for token in _tokens(raw):
        wanted.extend(_ALIASES.get(token, [token]))
    if not wanted:
        return pack("not_found", candidates=entries[:12])
    matches = [e for e in entries if all(w in e["model"].lower() for w in wanted)]
    ids = sorted({e["model"] for e in matches})
    if len(ids) == 1:
        same = [e for e in matches if e["model"] == ids[0]]
        providers = {e.get("provider") for e in same}
        chosen = same[0] if len(providers) == 1 else {"model": ids[0], "provider": None}
        return pack("resolved", chosen, same if len(providers) > 1 else ())
    if matches:
        return pack("ambiguous", candidates=matches[:12])
    return pack("not_found", candidates=entries[:12])


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=30, check=False)


def inspect_root(root: Any, *, base: Path = DEFAULT_PROJECTS_BASE) -> dict[str, Any]:
    """Describe whether ``root`` can host worktrees, without changing anything."""
    if not isinstance(root, str) or not root.strip():
        raise TeamError("invalid_payload", "项目目录必须为非空文字")
    path = Path(root).expanduser()
    if not path.is_absolute():
        raise TeamError("invalid_payload", "项目目录必须是绝对路径")
    path = Path(str(path.resolve()))
    info: dict[str, Any] = {"root": str(path), "exists": path.is_dir(), "is_git": False,
                            "has_head": False, "dirty": None, "ready": False, "needs": []}
    if path.exists() and not path.is_dir():
        raise TeamError("root_not_directory", "项目路径存在但不是目录")
    if not info["exists"]:
        info["needs"].append("create")
        info["inside_projects_base"] = path.is_relative_to(base.resolve()) if base.exists() else False
        return info
    top = _git(path, "rev-parse", "--show-toplevel")
    if top.returncode == 0 and Path(top.stdout.strip()).resolve() == path:
        info["is_git"] = True
        info["has_head"] = _git(path, "rev-parse", "--verify", "HEAD").returncode == 0
        status = _git(path, "status", "--porcelain", "--untracked-files=all")
        info["dirty"] = bool(status.stdout.strip()) if status.returncode == 0 else None
    elif top.returncode == 0:
        info["needs"].append("use_repo_root")
        info["repo_root"] = top.stdout.strip()
        return info
    if not info["is_git"]:
        info["needs"].append("git_init")
        info["empty"] = not any(path.iterdir())
    elif not info["has_head"]:
        info["needs"].append("initial_commit")
    elif info["dirty"]:
        info["needs"].append("clean_worktree")
    info["ready"] = info["is_git"] and info["has_head"] and info["dirty"] is False
    return info


def suggest_root(category: Any, name: Any, *, base: Path = DEFAULT_PROJECTS_BASE) -> str:
    for label, value in (("分类", category), ("项目名", name)):
        if not isinstance(value, str) or not _SAFE_SEGMENT.match(value):
            raise TeamError("invalid_payload", f"{label}只能用小写字母、数字、点、横线或下划线，且不超过64字符")
    return str(base / category / name)


def prepare_root(root: Any, *, base: Path = DEFAULT_PROJECTS_BASE, readme: Optional[str] = None) -> dict[str, Any]:
    """Create a missing project directory under ``base`` and give it a clean git baseline.

    Only acts on a path that does not exist yet, or an existing EMPTY non-git directory, both
    inside ``base``. Existing repos and non-empty folders are never touched: dirty or headless
    repos are reported for the user to resolve.
    """
    info = inspect_root(root, base=base)
    path = Path(info["root"])
    base_resolved = base.resolve()
    if not path.is_relative_to(base_resolved) or path == base_resolved:
        raise TeamError("root_outside_projects", f"只自动初始化{base_resolved}下的新项目目录；其它位置请先手动准备")
    if info["ready"]:
        return {**info, "changed": False}
    if info["exists"] and (info["is_git"] or not info.get("empty")):
        raise TeamError("root_not_auto_prepared",
                        "目录已有内容或已是仓库，不自动提交或改动：" + "、".join(info["needs"] or ["unknown"]))
    path.mkdir(parents=True, exist_ok=True)
    for args in (("init", "-q", "-b", "main"),):
        done = _git(path, *args)
        if done.returncode:
            raise TeamError("git_failed", done.stderr.strip() or "git init 失败")
    (path / "README.md").write_text(readme or f"# {path.name}\n\n由施工团队开工准备创建的空项目基线。\n", encoding="utf-8")
    for args in (("add", "README.md"),
                 ("-c", "user.name=construction-team", "-c", "user.email=construction-team@localhost",
                  "commit", "-q", "-m", "Initial baseline for construction team")):
        done = _git(path, *args)
        if done.returncode:
            raise TeamError("git_failed", done.stderr.strip() or "初始提交失败")
    after = inspect_root(str(path), base=base)
    if not after["ready"]:
        raise TeamError("root_not_ready", "初始化后仍未达到干净基线，现场保留")
    return {**after, "changed": True}


def _as_list(value: Any) -> list[Any]:
    """A single string stays one item; never split it into characters."""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def build_plan(payload: dict[str, Any], *, catalog: list[dict[str, Any]], defaults: dict[str, Any],
               coordinator: dict[str, Any], base: Path = DEFAULT_PROJECTS_BASE) -> dict[str, Any]:
    """Pure preview of a team launch from the current chat. Changes nothing."""
    if not isinstance(payload, dict):
        raise TeamError("invalid_payload", "payload必须为对象")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise TeamError("invalid_payload", "团队名称必须为非空文字")
    root = payload.get("root")
    if not root and payload.get("category") and payload.get("project"):
        root = suggest_root(payload["category"], payload["project"], base=base)
    root_info = inspect_root(root, base=base) if root else {"root": None, "ready": False, "needs": ["choose_root"]}

    blockers: list[str] = []
    models: dict[str, Any] = {}
    spoken = payload.get("models") or {}
    if not isinstance(spoken, dict) or set(spoken) - set(ROLES):
        raise TeamError("invalid_payload", "models只接受supervisor/worker/advisor；总控就是当前窗口")
    for role in ROLES:
        if role in spoken and spoken[role]:
            models[role] = resolve_model(spoken[role], catalog)
            if models[role]["status"] in {"ambiguous", "not_found"}:
                blockers.append(f"{role}模型“{spoken[role]}”需确认")
        elif role != "advisor":
            models[role] = {"status": "default", "model": defaults.get(f"{role}_model"),
                            "provider": defaults.get(f"{role}_provider")}

    modules = payload.get("modules") or []
    if not isinstance(modules, list) or not modules:
        blockers.append("至少需要一个模块（主管）")
        modules = []
    clean_modules = []
    for i, module in enumerate(modules):
        if not isinstance(module, dict) or not str(module.get("name") or "").strip() or not str(module.get("goal") or "").strip():
            raise TeamError("invalid_payload", f"模块{i + 1}需要name与goal")
        override = module.get("model")
        resolved = resolve_model(override, catalog) if override else None
        if resolved and resolved["status"] in {"ambiguous", "not_found"}:
            blockers.append(f"模块“{module['name']}”的主管模型“{override}”需确认")
        clean_modules.append({"name": module["name"], "goal": module["goal"],
                              "acceptance": _as_list(module.get("acceptance")),
                              "depends_on": _as_list(module.get("depends_on")),
                              "model": resolved})
    limits = {}
    for key in ("max_active_supervisors", "max_workers"):
        value = payload.get(key, defaults.get(key))
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8:
            raise TeamError("invalid_payload", "并发范围为1～8")
        limits[key] = value
    needs = root_info.get("needs", [])
    if "choose_root" in needs:
        blockers.append("需指定项目目录：已有仓库的绝对路径，或分类+项目名")
    if "create" in needs and not root_info.get("inside_projects_base"):
        blockers.append("新目录不在项目区，需手动准备或换路径")
    if "git_init" in needs:
        inside = Path(root_info["root"]).is_relative_to(base.resolve()) if base.exists() else False
        if not inside or not root_info.get("empty"):
            blockers.append("目录已有内容但不是git仓库，不自动初始化；需先手动建立基线或换路径")
    if root_info.get("needs") and set(root_info["needs"]) & {"use_repo_root", "initial_commit", "clean_worktree"}:
        blockers.append("项目目录需先处理：" + "、".join(root_info["needs"]))
    if len(clean_modules) == 1:
        advice = "只有一个模块：普通子代理通常更快更省，三级更适合≥3个需分别验收的模块"
    else:
        advice = None
    worker_note = ("工人继承所属主管的Provider路由；工人模型须在该Provider上可用"
                   if models.get("worker", {}).get("model") else None)
    return {
        "name": name, "root": root_info, "coordinator": coordinator, "models": models,
        "modules": clean_modules, "limits": limits, "blockers": blockers, "advice": advice,
        "worker_note": worker_note,
        "next": ("等待用户在本窗口明确确认开工；确认前不得调用create" if not blockers
                 else "先与用户解决blockers，再重新plan"),
    }
