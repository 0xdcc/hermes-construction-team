"""Prompt generation and output parsing for Hermes construction-team plugin.

Formats supervisor task prompts with embedded markers and constraints,
and parses post-turn reports back from supervisor sessions.
"""
from __future__ import annotations

import re
from typing import Any


def format_supervisor_task_prompt(task: dict[str, Any], member: dict[str, Any], team: dict[str, Any]) -> str:
    """Format the complete task specification prompt for a supervisor."""
    acc_lines = "\n".join(f"- [ ] {a}" for a in task.get("acceptance", [])) or "- [ ] 按照目标要求完成施工并提供可验证产物"
    forb_lines = "\n".join(f"- {f}" for f in task.get("forbidden", [])) or "- 无特殊禁止项，遵守常规安全规范"

    workspace = member.get("workspace", team.get("root", ""))
    marker = task["marker"]

    prompt = f"""[CTEAM_TASK_DISPATCH]
任务编号: {task['id']} (第 {task.get('attempt', 1)} 次尝试)
任务标题: {task['title']}
施工工区: {workspace}
任务目标:
{task['goal']}

验收标准 (Acceptance Criteria):
{acc_lines}

禁止动作 (Forbidden Actions):
{forb_lines}

施工规范与限制:
1. 你的工作目录为: {workspace}。严禁向工区外部写文件或破坏仓库基础结构。
2. 如需并行只读检索或单写子任务，可调用 construction_workers 工具委派子代理。
3. 你的施工产物必须保留在工区内，不得在未经验收前自报完成。
4. 本次任务绑定凭证:
[CTEAM_MARKER: {marker}]

汇报格式要求:
施工结束（或遇到阻断/失败）时，请在最终回复末尾附带以下格式的汇报块:
```
[CTEAM_REPORT]
STATUS: CANDIDATE | BLOCKED | FAILED
SUMMARY: <简要施工总结或阻断原因>
EVIDENCE:
- <可验证证据1: 产物路径、测试通过日志或代码变更>
- <可验证证据2>
[/CTEAM_REPORT]
```
注意: 施工完成请填写 STATUS: CANDIDATE。总控将基于你提交的 EVIDENCE 进行业务验收裁定。请勿自称 DONE 或 PASS。
[/CTEAM_TASK_DISPATCH]"""
    return prompt.strip()


def parse_supervisor_report(text: str) -> dict[str, Any]:
    """Parse supervisor turn output to extract status, summary, and evidence.

    Status is restricted to 'candidate', 'blocked', or 'failed'.
    Any self-claimed 'done' or 'passed' is normalized to 'candidate'.
    """
    if not text:
        return {
            "status": "unknown",
            "summary": "主管回合结束，未提供文字汇报",
            "evidence": [],
        }

    # 1. Look for explicit [CTEAM_REPORT] block
    report_match = re.search(r"\[CTEAM_REPORT\](.*?)\[/CTEAM_REPORT\]", text, re.DOTALL | re.IGNORECASE)
    raw_block = report_match.group(1).strip() if report_match else text

    status = "candidate"
    status_match = re.search(r"STATUS:\s*([A-Za-z_-]+)", raw_block, re.IGNORECASE)
    if status_match:
        val = status_match.group(1).upper()
        if "BLOCK" in val:
            status = "blocked"
        elif "FAIL" in val or "ERROR" in val:
            status = "failed"
        else:
            status = "candidate"
    else:
        # Check text heuristics
        lower = text.lower()
        if "blocked" in lower or "阻断" in lower:
            status = "blocked"
        elif "failed" in lower or "失败" in lower:
            status = "failed"
        else:
            status = "candidate"

    # Extract summary
    summary = ""
    summary_match = re.search(r"SUMMARY:\s*(.*?)(?=(EVIDENCE:|\[/CTEAM_REPORT\]|$))", raw_block, re.DOTALL | re.IGNORECASE)
    if summary_match:
        summary = summary_match.group(1).strip()
    else:
        # Use first 300 chars of text as summary
        lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("[")]
        summary = " ".join(lines[:3])[:300] if lines else "施工完成"

    # Extract evidence lines
    evidence: list[str] = []
    evidence_match = re.search(r"EVIDENCE:\s*(.*?)(?=(\[/CTEAM_REPORT\]|$))", raw_block, re.DOTALL | re.IGNORECASE)
    if evidence_match:
        ev_block = evidence_match.group(1).strip()
        for line in ev_block.splitlines():
            line = line.strip()
            if line.startswith("-") or line.startswith("*"):
                cleaned = line.lstrip("-* ").strip()
                if cleaned:
                    evidence.append(cleaned)
    if not evidence:
        # Scan text for file paths or test outputs
        path_matches = re.findall(r"(?:created|modified|file|path|产物|文件)[:\s]+([^\s,;]+)", text, re.IGNORECASE)
        for p in path_matches[:3]:
            if p and not p.startswith("http"):
                evidence.append(f"产物/路径: {p}")

    return {
        "status": status,
        "summary": summary,
        "evidence": evidence,
    }


def format_coordinator_notification(task: dict[str, Any], member: dict[str, Any], report: dict[str, Any]) -> str:
    """Format user-readable Chinese notification for inject_message."""
    status = report.get("status", "candidate")
    status_map = {
        "candidate": "【成果待验收 (CANDIDATE)】",
        "blocked": "【施工遇阻 (BLOCKED)】",
        "failed": "【施工失败 (FAILED)】",
    }
    status_zh = status_map.get(status, f"【{status}】")

    ev_text = "\n".join(f"  - {e}" for e in report.get("evidence", [])) or "  - （未提交显式依据）"
    summary = report.get("summary", "无详细总结")

    return (
        f"[施工团队回报:{task.get('id', '')}:{task.get('attempt', 1)}]\n"
        f"📢 施工团队自动回传:\n"
        f"主管: {member.get('name', '主管')} ({member.get('id', '')})\n"
        f"任务: {task.get('title', '')} (ID: {task.get('id', '')})\n"
        f"状态: {status_zh}\n"
        f"总结: {summary}\n"
        f"依据/产物:\n{ev_text}\n"
        f"完整报告（未独立验收）:\n{report.get('report') or summary}\n"
        f"实际模型:{task.get('actual_model') or member.get('actual_model') or '宿主未报告'}\n"
        f"请总控查验并使用 review 接口裁定。"
    )
