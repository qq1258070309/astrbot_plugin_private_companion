"""Fork release tooling for qq1258070309/astrbot_plugin_private_companion.

Upstream hardcodes its version in five places and verifies that metadata.yaml
points at the upstream repository. This tool rewrites those fields idempotently,
keeps a record of the upstream tag we are aligned to, refreshes the upstream
native-capability baseline, and validates everything before a release.

Commands:
  prepare --upstream-tag v7.1.21 [--revision a]   rewrite for a new fork release
  check                                           validate all release invariants
  version                                         print the current fork version
  base                                            print the aligned upstream tag

The CI workflow runs `prepare` after merging an upstream tag, so the version
fields never become a manual merge conflict.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORK_REPO = "https://github.com/qq1258070309/astrbot_plugin_private_companion"
UPSTREAM_REPO = "https://github.com/menglimi/astrbot_plugin_private_companion"
BASE_FILE = ROOT / "UPSTREAM_BASE"
CHANGELOG = ROOT / "CHANGELOG.md"
BASELINE = ROOT / "tools/native_capability_baseline.json"

# Files whose merge conflicts are always resolved in favour of upstream.
# `prepare` rewrites our version/repo fields back into them afterwards, so no
# upstream improvements are lost and no manual conflict resolution is needed.
UPSTREAM_SIDE_FILES = {
    "metadata.yaml", "pyproject.toml", "CHANGELOG.md", "README.md",
    "companion_v2/product/__init__.py",
    "tools/build_v2_release.py", "tools/verify_v2_release.py",
    "tools/native_capability_baseline.json",
    "pages/陪伴小屋/index.html",
    "pages/陪伴小屋/page-build.json",
    "pages/陪伴小屋/workspace-bundles/designer.js",
    "pages/陪伴小屋/workspace-bundles/host.js",
    "pages/陪伴小屋/workspace-bundles/identity.js",
    "pages/陪伴小屋/workspace-bundles/life.js",
    "pages/陪伴小屋/workspace-bundles/persona.js",
}

# Anchors that prove the local customization survived a merge. A missing anchor
# blocks auto-release and opens a review PR instead.
CUSTOM_ANCHORS = {
    "main.py": ["_start_qzone_credential_watch", "apply_pre_reply_reaction",
                "_qzone_life_publisher", "_route_core_peak_provider"],
    "companion_v2/qzone/configuration.py": ["credential_admin_notice", "life_publish_enabled"],
    "companion_v2/configuration/service.py": ["ApplyMode.IMMEDIATE"],
    "companion_v2/storage/runtime.py": ["WAL_SIZE_LIMIT_BYTES", "journal_size_limit"],
    "companion_v2/agenda/planning_output.py": ['"presence"', '"routine"'],
    "pages/陪伴小屋/config-editor.js": ["credential_admin_notice", "life_publish_enabled"],
    "pages/陪伴小屋/index.html": ["decision-page.js", "app.js"],
    "astrbot_host/qq_pre_reply_reaction.py": [],
    "astrbot_host/qzone_credential_watch.py": [],
    "companion_v2/qzone/credential.py": [],
}


def read(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def substitute(path: Path, pattern: str, replacement: str) -> bool:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, flags=re.M)
    if count == 0:
        raise SystemExit(f"failed to rewrite {path.relative_to(ROOT)}: pattern not found")
    if updated != text:
        write(path, updated)
    return updated != text


def current_version() -> str:
    match = re.search(r"(?m)^version:[^\r\n]*?([0-9][0-9.]*[a-z]?)\s*$", read(ROOT / "metadata.yaml"))
    if not match:
        raise SystemExit("cannot read version from metadata.yaml")
    return match.group(1)


def current_base() -> str:
    return read(BASE_FILE).strip() if BASE_FILE.exists() else ""


def upstream_version(tag: str) -> str:
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+[a-z]?)", tag.strip())
    if not match:
        raise SystemExit(f"unsupported upstream tag: {tag}")
    return match.group(1)


def next_revision(tag: str, explicit: str | None) -> str:
    # An explicitly empty revision ("") means "plain X.Y.Z", which is the only
    # shape AstrBot's VersionComparator can parse (a trailing letter makes it
    # fall back to 0.0.0, so the dashboard would never report an update).
    if explicit is not None:
        if not re.fullmatch(r"[a-z]?", explicit):
            raise SystemExit("revision must be a single lowercase letter or empty")
        return explicit
    if current_base() == tag:
        version = current_version()
        match = re.fullmatch(r"(\d+\.\d+\.\d+)([a-z])", version)
        if match and match.group(2) < "z":
            return chr(ord(match.group(2)) + 1)
        raise SystemExit("cannot auto-advance revision past z; pass --revision")
    return "a"


def apply_version(version: str) -> None:
    substitute(ROOT / "metadata.yaml", r"(?m)^version:[^\r\n]*", f"version: {version}")
    substitute(ROOT / "metadata.yaml", r"(?m)^repo:[^\r\n]*", f"repo: {FORK_REPO}")
    substitute(ROOT / "pyproject.toml", r'(?m)^version = "[^"]*"', f'version = "{version}"')
    substitute(ROOT / "companion_v2/product/__init__.py",
               r'(?m)^PRODUCT_VERSION = "[^"]*"', f'PRODUCT_VERSION = "{version}"')
    substitute(ROOT / "tools/build_v2_release.py",
               r'(?m)^VERSION = "[^"]*"', f'VERSION = "{version}"')
    substitute(ROOT / "tools/verify_v2_release.py",
               r'metadata\.get\("repo"\)\s*!=\s*"[^"]*"',
               f'metadata.get("repo") != "{FORK_REPO}"')
    # README: point at this fork while keeping the upstream credit link.
    readme = ROOT / "README.md"
    text = read(readme)
    upstream_line = f"- 源代码：[GitHub 仓库]({UPSTREAM_REPO})"
    fork_line = (f"- 源代码：[本定制发行仓库]({FORK_REPO}) · "
                 f"[上游原仓库]({UPSTREAM_REPO})")
    if upstream_line in text:
        write(readme, text.replace(upstream_line, fork_line, 1))
    elif fork_line not in text:
        print(f"warning: README source line not found, skipped", file=sys.stderr)


def apply_changelog(version: str, upstream: str, tag: str, date: str) -> None:
    text = read(CHANGELOG)
    heading = f"## {version} - {date}"
    entry = (
        f"{heading}\n\n"
        f"- 对齐上游 `{tag}`（{upstream}），并保留本仓库的本地定制；\n"
        f"- 由 `sync-release` 流水线完成三方合并、契约测试与兼容性审查后自动发布；\n"
        f"- 完整差异与审查结论见该版本 Release 附带的 `COMPAT_REPORT.md`。\n"
    )
    if re.search(rf"(?m)^## {re.escape(version)}\b", text):
        text = re.sub(rf"(?m)^## {re.escape(version)}[^\r\n]*\r?\n(?:.*?\r?\n)*?(?=^## |\Z)",
                      entry + "\n", text, count=1, flags=re.M | re.S)
    else:
        anchor = re.search(r"(?m)^# 更新日志\r?\n", text)
        if not anchor:
            raise SystemExit("CHANGELOG.md has no '# 更新日志' heading")
        text = text[:anchor.end()] + "\n" + entry + "\n" + text[anchor.end():].lstrip("\r\n")
    write(CHANGELOG, text)


def reapply_page_order() -> bool:
    """Keep decision-page.js before app.js (its mount point resolves once)."""
    path = ROOT / "pages/陪伴小屋/index.html"
    text = read(path)
    decision = re.search(r'(?m)^[ \t]*<script defer src="decision-page\.js[^\r\n]*</script>\r?\n?', text)
    app = re.search(r'(?m)^[ \t]*<script defer src="app\.js[^\r\n]*</script>\r?\n?', text)
    if not decision or not app or decision.start() < app.start():
        return False
    start = decision.start()
    preceding = re.search(r"(?:[ \t]*<!--.*?-->\r?\n)+$", text[:start], re.S)
    if preceding:
        start = preceding.start()
    block = text[start:decision.end()]
    text = text[:start] + text[decision.end():]
    app = re.search(r'(?m)^[ \t]*<script defer src="app\.js[^\r\n]*</script>\r?\n?', text)
    if not app:
        raise SystemExit("lost app.js while reordering index.html")
    write(path, text[:app.start()] + block + text[app.start():])
    return True


def verify_customizations() -> list[str]:
    problems = []
    for rel, anchors in CUSTOM_ANCHORS.items():
        path = ROOT / rel
        if not path.exists():
            problems.append(f"customization file missing: {rel}")
            continue
        content = read(path)
        for anchor in anchors:
            if anchor not in content:
                problems.append(f"customization anchor missing in {rel}: {anchor}")
    index = read(ROOT / "pages/陪伴小屋/index.html")
    decision = re.search(r'(?m)^[ \t]*<script defer src="decision-page\.js', index)
    app = re.search(r'(?m)^[ \t]*<script defer src="app\.js', index)
    if decision and app and decision.start() > app.start():
        problems.append("index.html: decision-page.js loads after app.js")
    return problems


def tag_key(tag: str):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)([a-z]?)", tag.strip())
    if not match:
        raise SystemExit(f"unsupported tag: {tag}")
    return (*map(int, match.groups()[:3]), match.group(4))


def should_sync(args: argparse.Namespace) -> None:
    target = args.upstream_tag.strip()
    base = current_base()
    needed = (not base) or tag_key(target) > tag_key(base)
    print(json.dumps({"needed": needed, "current": base, "target": target}))
    if args.outputs:
        with open(args.outputs, "a", encoding="utf-8") as fh:
            fh.write(f"needed={'true' if needed else 'false'}\n"
                     f"tag={target}\nbase={base}\n")


def resolve_merge(args: argparse.Namespace) -> None:
    """Deterministically resolve conflicts left by `git merge`.

    Whitelisted files take the upstream side; every other conflict takes our
    side so the tree stays committable, and is reported for human review.
    """
    result = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"],
                            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    conflicts = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    upstream_side, ours_side = [], []
    for rel in conflicts:
        side = "--theirs" if rel in UPSTREAM_SIDE_FILES else "--ours"
        subprocess.run(["git", "checkout", side, "--", rel], cwd=ROOT, check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "add", "--", rel], cwd=ROOT, check=True,
                       capture_output=True, text=True)
        (upstream_side if side == "--theirs" else ours_side).append(rel)
    report = {"conflicts": conflicts, "resolved_from_upstream": upstream_side,
              "needs_review": ours_side, "auto_releasable": not ours_side}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def refresh_baseline() -> None:
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "tools/build_v2_release.py",
         "--refresh-native-capability-baseline"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise SystemExit("native baseline refresh failed:\n" + result.stdout + result.stderr)
    print(result.stdout.strip())


def prepare(args: argparse.Namespace) -> None:
    tag = args.upstream_tag.strip()
    upstream = upstream_version(tag)
    revision = next_revision(tag, args.revision)
    version = upstream + revision
    date = args.date or datetime.date.today().isoformat()
    apply_version(version)
    reapply_page_order()
    apply_changelog(version, upstream, tag, date)
    write(BASE_FILE, tag + "\n")
    refresh_baseline()
    print(json.dumps({"version": version, "upstream_tag": tag, "revision": revision,
                      "date": date, "repo": FORK_REPO}, ensure_ascii=False))


def collect_versions() -> dict[str, str]:
    checks = {
        "metadata.yaml": (r"(?m)^version:\s*([^\r\n]+)", ROOT / "metadata.yaml"),
        "pyproject.toml": (r'(?m)^version = "([^"]+)"', ROOT / "pyproject.toml"),
        "product/__init__.py": (r'(?m)^PRODUCT_VERSION = "([^"]+)"', ROOT / "companion_v2/product/__init__.py"),
        "build_v2_release.py": (r'(?m)^VERSION = "([^"]+)"', ROOT / "tools/build_v2_release.py"),
    }
    out = {}
    for name, (pattern, path) in checks.items():
        match = re.search(pattern, read(path))
        if not match:
            raise SystemExit(f"cannot read version from {name}")
        out[name] = match.group(1).strip()
    return out


def check(_args: argparse.Namespace) -> None:
    versions = collect_versions()
    version = versions["metadata.yaml"]
    problems = verify_customizations()
    if len(set(versions.values())) != 1:
        problems.append(f"version mismatch: {versions}")
    metadata = read(ROOT / "metadata.yaml")
    if f"repo: {FORK_REPO}" not in metadata:
        problems.append("metadata.yaml repo does not point at this fork")
    verifier = read(ROOT / "tools/verify_v2_release.py")
    if f'metadata.get("repo") != "{FORK_REPO}"' not in verifier:
        problems.append("verify_v2_release.py still expects the upstream repo")
    baseline = json.loads(read(BASELINE))
    if baseline.get("package_version") != version:
        problems.append(f"native baseline is stale: {baseline.get('package_version')} != {version}")
    if not re.search(rf"(?m)^## {re.escape(version)}\b", read(CHANGELOG)):
        problems.append(f"CHANGELOG.md has no section for {version}")
    if not current_base():
        problems.append("UPSTREAM_BASE is missing")
    for rel in ("metadata.yaml", "main.py", "tools/build_v2_release.py", "pyproject.toml"):
        if re.search(r"(?m)^<<<<<<< |^=======$|^>>>>>>> ", read(ROOT / rel)):
            problems.append(f"unresolved merge markers in {rel}")
    result = {"ok": not problems, "version": version, "versions": versions,
              "upstream_base": current_base(), "problems": problems}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if problems:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--upstream-tag", required=True, help="upstream release tag, e.g. v7.1.21")
    p.add_argument("--revision", default=None, help="fork revision letter, default: a (or next letter)")
    p.add_argument("--date", default=None, help="release date, default: today")
    p.set_defaults(func=prepare)
    p = sub.add_parser("check")
    p.set_defaults(func=check)
    p = sub.add_parser("should-sync")
    p.add_argument("--upstream-tag", required=True)
    p.add_argument("--outputs", default=None, help="path to GITHUB_OUTPUT")
    p.set_defaults(func=should_sync)
    p = sub.add_parser("resolve-merge", help="deterministically resolve git merge conflicts")
    p.add_argument("--report", default="CONFLICTS.json")
    p.set_defaults(func=resolve_merge)
    p = sub.add_parser("reapply-page-order")
    p.set_defaults(func=lambda _a: print(json.dumps({"changed": reapply_page_order()})))
    p = sub.add_parser("version")
    p.set_defaults(func=lambda _a: print(current_version()))
    p = sub.add_parser("base")
    p.set_defaults(func=lambda _a: print(current_base()))
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
