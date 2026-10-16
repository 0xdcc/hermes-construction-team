"""In-chat kickoff: spoken model resolution, project root preparation, plan preview, tool entry."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

# pyright: reportMissingImports=false
from cteam import kickoff
from cteam.store import TeamError

CATALOG = [
    {"model": "gpt-6.1-sol", "provider": "custom"},
    {"model": "gemini-3.8-flash-high", "provider": "proxy-a"},
    {"model": "gemini-3.8-flash-high", "provider": "gateway-b"},
    {"model": "claude-opus-4.6", "provider": "proxy-a"},
    {"model": "vendor/claude-opus-5-5", "provider": "anthropic-proxy"},
    {"model": "vendor/claude-sonnet-5-5", "provider": "anthropic-proxy"},
    {"model": "gpt-5.6-sol", "provider": "proxy-a"},
]
DEFAULTS = {"supervisor_model": "gpt-6.1-sol", "supervisor_provider": None, "worker_model": "gemini-3.8-flash-high",
            "worker_provider": None, "max_active_supervisors": 2, "max_workers": 4}


class ResolveModelTests(unittest.TestCase):
    def test_exact_single_provider(self):
        r = kickoff.resolve_model("gpt-6.1-sol", CATALOG)
        self.assertEqual((r["status"], r["model"], r["provider"]), ("exact", "gpt-6.1-sol", "custom"))

    def test_exact_multi_provider_keeps_provider_open(self):
        r = kickoff.resolve_model("gemini-3.8-flash-high", CATALOG)
        self.assertEqual(r["status"], "exact")
        self.assertIsNone(r["provider"])
        self.assertEqual(len(r["candidates"]), 2)

    def test_provider_hint(self):
        r = kickoff.resolve_model("gemini-3.8-flash-high@gateway-b", CATALOG)
        self.assertEqual(r["provider"], "gateway-b")

    def test_spoken_unique(self):
        r = kickoff.resolve_model("sonnet", CATALOG)
        self.assertEqual((r["status"], r["model"]), ("resolved", "vendor/claude-sonnet-5-5"))
        r = kickoff.resolve_model("flash", CATALOG)
        self.assertEqual((r["status"], r["model"]), ("resolved", "gemini-3.8-flash-high"))

    def test_spoken_ambiguous_never_guesses(self):
        r = kickoff.resolve_model("opus", CATALOG)
        self.assertEqual(r["status"], "ambiguous")
        self.assertNotIn("model", r)
        self.assertEqual({c["model"] for c in r["candidates"]}, {"claude-opus-4.6", "vendor/claude-opus-5-5"})
        r = kickoff.resolve_model("opus 5.5", CATALOG)
        self.assertEqual(r["model"], "vendor/claude-opus-5-5")

    def test_unknown(self):
        r = kickoff.resolve_model("llama-9", CATALOG)
        self.assertEqual(r["status"], "not_found")
        self.assertNotIn("model", r)
        with self.assertRaises(TeamError):
            kickoff.resolve_model("  ", CATALOG)


class RootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve() / "projects"
        self.base.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_suggest_root_rejects_unsafe(self):
        self.assertEqual(kickoff.suggest_root("tools", "demo-x", base=self.base), str(self.base / "tools/demo-x"))
        for bad in ("../x", "Tools", "a/b", ""):
            with self.assertRaises(TeamError):
                kickoff.suggest_root("tools", bad, base=self.base)

    def test_prepare_new_root_creates_clean_baseline(self):
        target = self.base / "tools" / "demo"
        before = kickoff.inspect_root(str(target), base=self.base)
        self.assertEqual(before["needs"], ["create"])
        self.assertFalse(target.exists())
        info = kickoff.prepare_root(str(target), base=self.base)
        self.assertTrue(info["ready"] and info["changed"])
        log = subprocess.run(["git", "-C", str(target), "log", "--oneline"], capture_output=True, text=True)
        self.assertEqual(len(log.stdout.strip().splitlines()), 1)
        again = kickoff.prepare_root(str(target), base=self.base)
        self.assertFalse(again["changed"])

    def test_prepare_refuses_outside_base_and_existing_content(self):
        outside = Path(self.tmp.name).resolve() / "elsewhere"
        with self.assertRaises(TeamError) as ctx:
            kickoff.prepare_root(str(outside), base=self.base)
        self.assertEqual(ctx.exception.code, "root_outside_projects")
        self.assertFalse(outside.exists())
        busy = self.base / "tools" / "busy"
        busy.mkdir(parents=True)
        (busy / "keep.txt").write_text("user data")
        with self.assertRaises(TeamError) as ctx:
            kickoff.prepare_root(str(busy), base=self.base)
        self.assertEqual(ctx.exception.code, "root_not_auto_prepared")
        self.assertFalse((busy / ".git").exists())

    def test_dirty_repo_reported_not_touched(self):
        repo = self.base / "tools" / "dirty"
        kickoff.prepare_root(str(repo), base=self.base)
        (repo / "new.txt").write_text("x")
        info = kickoff.inspect_root(str(repo), base=self.base)
        self.assertEqual(info["needs"], ["clean_worktree"])
        with self.assertRaises(TeamError):
            kickoff.prepare_root(str(repo), base=self.base)
        self.assertTrue((repo / "new.txt").exists())

    def test_prepare_refuses_ready_repo_outside_base(self):
        other_base = Path(self.tmp.name).resolve() / "other"
        other_base.mkdir()
        repo = other_base / "repo"
        kickoff.prepare_root(str(repo), base=other_base)
        with self.assertRaises(TeamError) as ctx:
            kickoff.prepare_root(str(repo), base=self.base)
        self.assertEqual(ctx.exception.code, "root_outside_projects")

    def test_projects_base_setting(self):
        self.assertEqual(kickoff.projects_base({"projects_base": str(self.base)}), self.base)
        self.assertEqual(kickoff.projects_base({}), Path.home() / "projects")
        with self.assertRaises(TeamError):
            kickoff.projects_base({"projects_base": "relative"})

    def test_relative_root_rejected(self):
        with self.assertRaises(TeamError):
            kickoff.inspect_root("relative/path", base=self.base)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve() / "projects"
        self.base.mkdir()
        self.coord = {"session": "当前窗口", "model": "vendor/claude-opus-5-5"}

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, **payload):
        body = {"name": "demo", "category": "tools", "project": "demo",
                "modules": [{"name": "后端", "goal": "API"}, {"name": "前端", "goal": "UI"}, {"name": "测试", "goal": "E2E"}]}
        body.update(payload)
        return kickoff.build_plan(body, catalog=CATALOG, defaults=DEFAULTS, coordinator=self.coord, base=self.base)

    def test_clean_plan_has_no_side_effects(self):
        p = self.plan(models={"supervisor": "sonnet", "worker": "flash"})
        self.assertEqual(p["blockers"], [])
        self.assertEqual(p["models"]["supervisor"]["model"], "vendor/claude-sonnet-5-5")
        self.assertEqual(p["models"]["worker"]["model"], "gemini-3.8-flash-high")
        self.assertEqual(p["root"]["needs"], ["create"])
        self.assertTrue(p["root"]["inside_projects_base"])
        self.assertFalse((self.base / "tools").exists())
        self.assertIn("确认", p["next"])
        self.assertIsNone(p["advice"])

    def test_defaults_when_unspecified(self):
        p = self.plan()
        self.assertEqual(p["models"]["supervisor"], {"status": "default", "model": "gpt-6.1-sol", "provider": None})
        self.assertNotIn("advisor", p["models"])

    def test_ambiguous_model_blocks(self):
        p = self.plan(models={"supervisor": "opus"})
        self.assertTrue(any("supervisor" in b for b in p["blockers"]))
        self.assertIn("解决", p["next"])

    def test_coordinator_model_cannot_be_set(self):
        with self.assertRaises(TeamError):
            self.plan(models={"coordinator": "sonnet"})

    def test_single_module_advice_and_empty_modules(self):
        p = self.plan(modules=[{"name": "x", "goal": "y"}])
        self.assertIn("子代理", p["advice"])
        p = self.plan(modules=[])
        self.assertTrue(p["blockers"])

    def test_limits_validated(self):
        with self.assertRaises(TeamError):
            self.plan(max_workers=9)

    def test_missing_root_blocks(self):
        p = self.plan(category=None, project=None)
        self.assertTrue(any("项目目录" in b for b in p["blockers"]))
        self.assertIn("解决", p["next"])

    def test_nonempty_non_git_root_blocks(self):
        folder = self.base / "tools" / "loose"
        folder.mkdir(parents=True)
        (folder / "notes.txt").write_text("keep")
        p = self.plan(root=str(folder), category=None, project=None)
        self.assertTrue(any("不是git仓库" in b for b in p["blockers"]))
        empty = self.base / "tools" / "empty"
        empty.mkdir()
        self.assertEqual(self.plan(root=str(empty), category=None, project=None)["blockers"], [])

    def test_string_acceptance_is_not_split(self):
        p = self.plan(modules=[{"name": "a", "goal": "b", "acceptance": "make test", "depends_on": "t_1"},
                               {"name": "c", "goal": "d"}, {"name": "e", "goal": "f"}])
        self.assertEqual(p["modules"][0]["acceptance"], ["make test"])
        self.assertEqual(p["modules"][0]["depends_on"], ["t_1"])

    def test_outside_root_blocks(self):
        p = self.plan(root=str(Path(self.tmp.name).resolve() / "outside"), category=None, project=None)
        self.assertTrue(any("项目区" in b for b in p["blockers"]))


if __name__ == "__main__":
    unittest.main()
