"""AI compatibility review for an upstream merge into this fork.

Reads the merge diff, upstream release notes, the customization inventory,
conflict report and mechanical gate results, then asks an OpenAI-compatible
chat endpoint for a conservative compatibility verdict. Emits COMPAT_REPORT.md
and GitHub Actions outputs. No API key is ever logged or written to disk.

Environment:
  LLM_API_KEY   required; when absent the review is skipped (not a pass)
  LLM_BASE_URL  default https://api.openai.com/v1
  LLM_MODEL     default gpt-4o-mini
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def clip(path: str | None, limit: int) -> str:
    if not path or not Path(path).exists():
        return "(not provided)"
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > limit:
        text = "\n".join(lines[:limit]) + f"\n... ({len(lines) - limit} more lines omitted)"
    return text[:limit * 200]


SYSTEM_PROMPT = """你是一个严谨的 Python/AstrBot 插件发布审查员。审查对象是「上游新版 + 本地定制」三方合并后的候选发布。
只在有充分证据时判定可发布。重点检查：
1) 本地定制清单里的功能是否可能因为上游改动而失效（符号被删、接口改名、行为被重写）；
2) 版本号、metadata repo、native capability baseline 等发布契约是否一致；
3) 机械门禁（编译、契约测试、发布包构建校验）是否有失败项；
4) 是否存在未解决的合并冲突或安全风险（凭据、隐私文件、越权改动）。
若任一门禁失败、存在需要人工裁决的冲突、或定制锚点缺失，必须判定 compatible=false。
只输出 JSON，不要输出解释性文字：{"compatible": boolean, "risk": "low|medium|high", "findings": ["..."], "summary": "..."}
findings 每条指出具体文件/符号与理由，最多 8 条。summary 用简体中文，不超过 200 字。"""


def call_llm(prompt: str) -> dict:
    key = os.environ.get("LLM_API_KEY", "").strip()
    base = (os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    model = os.environ.get("LLM_MODEL") or DEFAULT_MODEL
    if not key:
        return {}
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": prompt}],
        "temperature": 0,
    }
    request = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, ValueError, TimeoutError) as error:
        raise SystemExit(f"LLM request failed: {type(error).__name__}: {error}")
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        verdict = json.loads(content)
    except ValueError:
        raise SystemExit("LLM did not return JSON")
    if not isinstance(verdict.get("compatible"), bool):
        raise SystemExit("LLM verdict missing boolean 'compatible'")
    return verdict


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff", help="merge diff / diffstat file")
    parser.add_argument("--notes", help="upstream release notes")
    parser.add_argument("--conflicts", help="CONFLICTS.json from fork_release.py resolve-merge")
    parser.add_argument("--customizations", help="FORK_CUSTOMIZATIONS.md")
    parser.add_argument("--gates", help="mechanical gate results (JSON)")
    parser.add_argument("--version", required=True)
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument("--report", default="COMPAT_REPORT.md")
    parser.add_argument("--outputs", default=None, help="path to GITHUB_OUTPUT")
    args = parser.parse_args()

    sections = {
        "合并差异 (diffstat)": (args.diff, 200),
        "上游发布说明": (args.notes, 60),
        "合并冲突报告": (args.conflicts, 60),
        "本地定制清单": (args.customizations, 120),
        "机械门禁结果": (args.gates, 80),
    }
    prompt = (f"候选版本: {args.version}\n对齐上游: {args.upstream_tag}\n\n"
              + "\n\n".join(f"### {name}\n{clip(path, limit)}"
                            for name, (path, limit) in sections.items()))
    verdict = call_llm(prompt)
    configured = bool(verdict)
    if not configured:
        verdict = {"compatible": False, "risk": "unknown",
                   "findings": ["未配置 LLM_API_KEY，AI 兼容性审查未执行；按安全默认不自动发布。"],
                   "summary": "AI 审查跳过，需在仓库 Secrets 配置 LLM_API_KEY 后重跑。"}

    report = [
        f"# 兼容性报告 · {args.version}", "",
        f"- 对齐上游：`{args.upstream_tag}`",
        f"- 候选版本：`{args.version}`",
        f"- AI 审查：{'已执行' if configured else '未执行（缺少 LLM_API_KEY）'}",
        f"- 风险等级：`{verdict.get('risk', 'unknown')}`",
        f"- 结论：**{'可发布' if verdict.get('compatible') else '暂不发布'}**", "",
        "## AI 结论", "", verdict.get("summary", ""), "",
        "## 发现项", "",
    ]
    report += [f"- {item}" for item in verdict.get("findings", [])] or ["- 无"]
    report += ["", "## 输入摘要", ""]
    for name, (path, limit) in sections.items():
        report += [f"### {name}", "", "```", clip(path, limit), "```", ""]
    Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")

    lines = [f"ai_configured={'true' if configured else 'false'}",
             f"compatible={'true' if verdict.get('compatible') else 'false'}",
             f"risk={verdict.get('risk', 'unknown')}"]
    print("\n".join(lines))
    if args.outputs:
        with open(args.outputs, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    print(f"report written to {args.report}")


if __name__ == "__main__":
    main()
