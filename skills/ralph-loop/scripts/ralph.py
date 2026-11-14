#!/usr/bin/env python3
"""ralph-loop helper. Stdlib only.

Usage (run from the project root, or pass --target DIR):
  ralph.py plan   [--check CMD] [--allowed TOOLS]   show what setup would change (writes nothing)
  ralph.py apply  [--check CMD] [--allowed TOOLS]   install the loop files
  ralph.py doctor                                   prove the setup works; exit 1 on any FAIL
  ralph.py status                                   what the loop has done and where it's stuck

Rules:
  - Never overwrite. A file that differs gets <file>.ralph-new and a CONFLICT line.
  - .ralph/config, IMPLEMENTATION_PLAN.md and the AGENTS.md section belong to you after the first run.
  - Safe to run twice: a second apply reports SKIP for everything.
"""
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
MARK_START, MARK_END = "<!-- ralph:start -->", "<!-- ralph:end -->"
BASE_TOOLS = ["Bash(git *)", "Bash(ls *)", "Bash(mkdir *)", "Bash(cat *)"]
FILES = [  # (relative path, executable, owned by the user after first install)
    ("loop.sh", True, False),
    ("PROMPT_plan.md", False, False),
    ("PROMPT_build.md", False, False),
    ("IMPLEMENTATION_PLAN.md", False, True),
    ("specs/_TEMPLATE.md", False, False),
    (".ralph/.gitignore", False, False),
    (".ralph/settings.json", False, False),
    (".ralph/hooks/guard.py", True, False),
    (".ralph/hooks/gate.py", True, False),
]


# ---------------------------------------------------------------- detection
def detect(t: Path):
    """Return (stack, check_cmd, extra_tools)."""
    pj = t / "package.json"
    if pj.exists():
        pm = "pnpm" if (t / "pnpm-lock.yaml").exists() else "yarn" if (t / "yarn.lock").exists() else "npm"
        try:
            scripts = json.loads(pj.read_text()).get("scripts", {})
        except ValueError:
            scripts = {}
        parts = []
        for name in ("typecheck", "lint", "test"):
            body = scripts.get(name, "")
            if body and "no test specified" not in body:
                parts.append(f"{pm} run {name}")
        tools = [f"Bash({pm} *)", "Bash(npx *)", "Bash(node *)"]
        return f"node ({pm})", " && ".join(parts), tools
    if any((t / f).exists() for f in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg")):
        py = (t / "pyproject.toml").read_text() if (t / "pyproject.toml").exists() else ""
        parts = ["ruff check ."] if ("[tool.ruff" in py or (t / "ruff.toml").exists()) else []
        parts.append("python3 -m pytest -q")
        tools = ["Bash(python3 *)", "Bash(python *)", "Bash(pytest *)", "Bash(ruff *)", "Bash(pip *)"]
        return "python", " && ".join(parts), tools
    if (t / "go.mod").exists():
        return "go", "go vet ./... && go test ./...", ["Bash(go *)"]
    if (t / "Cargo.toml").exists():
        return "rust", "cargo test", ["Bash(cargo *)"]
    return "unknown", "", []


def check_parts(check: str):
    return [p.strip() for p in re.split(r"&&|\|\||;", check) if p.strip()]


def tools_for_check(check: str):
    """The agent must be allowed to run the check, or it can't verify anything."""
    out = []
    for p in check_parts(check):
        words = [w for w in p.split() if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)]
        if words:
            out.append(f"Bash({words[0]} *)")
    return out


def merge_tools(*lists):
    out = []
    for lst in lists:
        for x in lst:
            if x and x not in out:
                out.append(x)
    return out


def covered(part: str, tools: str) -> bool:
    for entry in re.findall(r"Bash\(([^)]*)\)", tools):
        if entry == part:
            return True
        for suffix in (" *", ":*", "*"):
            if entry.endswith(suffix) and part.startswith(entry[: -len(suffix)]):
                return True
    return False


def read_config(t: Path):
    cfg = {}
    p = t / ".ralph" / "config"
    if p.exists():
        for line in p.read_text().splitlines():
            m = re.match(r'^(RALPH_[A-Z_]+|CLAUDE_BIN)=(.*)$', line.strip())
            if m:
                cfg[m.group(1)] = m.group(2).strip().strip('"')
    return cfg


def render_config(check: str, tools: str) -> str:
    for v in (check, tools):
        if '"' in v:
            sys.exit('ralph: use single quotes inside --check/--allowed; double quotes break .ralph/config')
    text = (ASSETS / ".ralph" / "config").read_text()
    text = re.sub(r'^RALPH_CHECK=.*$', f'RALPH_CHECK="{check}"', text, flags=re.M)
    return re.sub(r'^RALPH_ALLOWED_TOOLS=.*$', f'RALPH_ALLOWED_TOOLS="{tools}"', text, flags=re.M)


# ---------------------------------------------------------------- plan / apply
def build_plan(t: Path, check_arg, allowed_arg):
    stack, check, extra = detect(t)
    check = check if check_arg is None else check_arg
    given = [x.strip() for x in allowed_arg.split(",")] if allowed_arg is not None else BASE_TOOLS + extra
    tools = ",".join(merge_tools(given, tools_for_check(check)))
    items = []  # (kind, rel, note, content, executable)

    for rel, exe, owned in FILES:
        src = (ASSETS / rel).read_text()
        dest = t / rel
        if not dest.exists():
            items.append(("CREATE", rel, "", src, exe))
        elif dest.read_text() == src:
            items.append(("SKIP", rel, "up to date", None, exe))
        elif owned:
            items.append(("SKIP", rel, "yours, left alone", None, exe))
        else:
            items.append(("CONFLICT", rel, f"differs; new version goes to {rel}.ralph-new", src, exe))

    cfg = t / ".ralph" / "config"
    if cfg.exists():
        items.append(("SKIP", ".ralph/config", "yours, left alone", None, False))
    else:
        items.append(("CREATE", ".ralph/config", f'RALPH_CHECK="{check}"', render_config(check, tools), False))

    section = (ASSETS / "AGENTS.md").read_text()
    ag = t / "AGENTS.md"
    if not ag.exists():
        items.append(("CREATE", "AGENTS.md", "with the Ralph section", section, False))
    elif MARK_START in ag.read_text():
        items.append(("SKIP", "AGENTS.md", "Ralph section present, yours", None, False))
    else:
        items.append(("MERGE", "AGENTS.md", "append the Ralph section", ag.read_text().rstrip("\n") + "\n\n" + section, False))
    return stack, check, tools, items


def print_plan(stack, check, tools, items):
    print(f"stack: {stack}")
    print(f"check: {check or '(none detected: setup must supply --check)'}")
    print(f"allowed tools: {tools}")
    for kind, rel, note, _, _ in items:
        print(f"  {kind:<8} {rel}" + (f"  ({note})" if note else ""))


def apply(t: Path, items):
    for kind, rel, _, content, exe in items:
        if kind == "SKIP":
            continue
        dest = t / (rel + ".ralph-new" if kind == "CONFLICT" else rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        if exe:
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (t / ".ralph" / "logs").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- doctor
def run(cmd, cwd, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, **kw)


def doctor(t: Path) -> int:
    results = []

    def res(status, what, detail=""):
        results.append((status, what, detail))

    for rel, exe, _ in FILES:
        p = t / rel
        if not p.exists():
            res("FAIL", f"{rel} installed", "missing; run apply")
        elif exe and not os.access(p, os.X_OK):
            res("FAIL", f"{rel} executable", "chmod +x it")
    if not (t / ".ralph" / "config").exists():
        res("FAIL", ".ralph/config installed", "missing; run apply")

    for b in ("python3", "git"):
        res("PASS" if shutil.which(b) else "FAIL", f"{b} on PATH")
    cfg = read_config(t)
    cli = os.environ.get("CLAUDE_BIN") or cfg.get("CLAUDE_BIN") or "claude"
    res("PASS" if shutil.which(cli) else "FAIL", f"{cli} on PATH")

    if run(["git", "rev-parse", "--is-inside-work-tree"], t).returncode != 0:
        res("WARN", "git repo", "not a repo: no stall detection, no history. Run git init.")
    else:
        br = run(["git", "symbolic-ref", "--short", "-q", "HEAD"], t).stdout.strip() or "detached HEAD"
        res("WARN" if br in ("main", "master") else "PASS", "working branch", f"on {br}" + (": use a branch for the loop" if br in ("main", "master") else ""))

    try:
        json.loads((t / ".ralph" / "settings.json").read_text())
        res("PASS", ".ralph/settings.json is valid JSON")
    except (OSError, ValueError) as e:
        res("FAIL", ".ralph/settings.json is valid JSON", str(e))

    guard = t / ".ralph" / "hooks" / "guard.py"
    if guard.exists():
        probe = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(t / "specs" / "x.md")}, "cwd": str(t)})
        env = dict(os.environ, RALPH_MODE="build", CLAUDE_PROJECT_DIR=str(t))
        r = subprocess.run([sys.executable, str(guard)], input=probe, capture_output=True, text=True, env=env)
        res("PASS" if r.returncode == 2 else "FAIL", "guard blocks a spec edit", f"exit {r.returncode}")

    check = os.environ.get("RALPH_CHECK", cfg.get("RALPH_CHECK", "")).strip()
    if not check:
        res("FAIL", "RALPH_CHECK set", "empty: nothing would verify the agent's work")
    else:
        r = subprocess.run(["sh", "-c", check], cwd=t, capture_output=True, text=True)
        tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
        if r.returncode == 0:
            res("PASS", f"RALPH_CHECK runs: {check}")
        elif r.returncode in (126, 127):
            res("FAIL", f"RALPH_CHECK runs: {check}", "command not found: " + " | ".join(tail))
        else:
            res("WARN", f"RALPH_CHECK runs: {check}", f"exit {r.returncode}, so the loop starts red: " + " | ".join(tail))
        yolo = os.environ.get("RALPH_YOLO", cfg.get("RALPH_YOLO", "0")) == "1"
        tools = os.environ.get("RALPH_ALLOWED_TOOLS", cfg.get("RALPH_ALLOWED_TOOLS", ""))
        missing = [p for p in check_parts(check) if not covered(p, tools)]
        if yolo:
            res("PASS", "agent may run the check", "RALPH_YOLO=1")
        elif missing:
            res("FAIL", "agent may run the check", "add to RALPH_ALLOWED_TOOLS: " + ", ".join(tools_for_check(" && ".join(missing))))
        else:
            res("PASS", "agent may run the check")

    for status, what, detail in results:
        print(f"  {status:<4} {what}" + (f"  ({detail})" if detail else ""))
    fails = sum(1 for s, _, _ in results if s == "FAIL")
    print(f"doctor: {fails} fail, {sum(1 for s, _, _ in results if s == 'WARN')} warn")
    return 1 if fails else 0


# ---------------------------------------------------------------- status
def status(t: Path) -> int:
    cfg = read_config(t)
    plan = t / cfg.get("RALPH_PLAN", "IMPLEMENTATION_PLAN.md")
    text = plan.read_text() if plan.exists() else ""
    open_ = re.findall(r"^\s*[-*] \[ \] (.*)$", text, re.M)
    done = re.findall(r"^\s*[-*] \[[xX]\] (.*)$", text, re.M)
    print(f"plan: {len(done)} done, {len(open_)} open")
    for item in open_[:3]:
        print(f"  next: {item}")
    q = re.search(r"^## Questions\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if q and q.group(1).strip():
        print("questions for you:\n  " + "\n  ".join(q.group(1).strip().splitlines()))
    for name, label in (("STOP", "STOPPED"), ("CHECK_FAILED", "CHECKS RED")):
        p = t / ".ralph" / name
        if p.exists():
            print(f"{label}: " + "\n  ".join(p.read_text().strip().splitlines()[:8]))
    logs = sorted((t / ".ralph" / "logs").glob("*.log"))[-5:] if (t / ".ralph" / "logs").exists() else []
    for lg in logs:
        lines = [l for l in lg.read_text(errors="replace").splitlines() if l.strip()]
        print(f"log {lg.name}: {(lines[-1][:160] if lines else '(empty)')}")
    r = run(["git", "log", "--oneline", "-5"], t)
    if r.returncode == 0 and r.stdout.strip():
        print("recent commits:\n  " + "\n  ".join(r.stdout.strip().splitlines()))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "apply", "doctor", "status"])
    ap.add_argument("--target", default=".")
    ap.add_argument("--check", default=None, help="override the detected check command")
    ap.add_argument("--allowed", default=None, help="override the allowed tools (comma-separated)")
    a = ap.parse_args()
    t = Path(a.target).resolve()
    if not t.is_dir():
        sys.exit(f"ralph: {t} is not a directory")
    if a.cmd in ("plan", "apply"):
        stack, check, tools, items = build_plan(t, a.check, a.allowed)
        print_plan(stack, check, tools, items)
        if a.cmd == "apply":
            apply(t, items)
            print("applied. Next: ralph.py doctor")
        return 0
    return doctor(t) if a.cmd == "doctor" else status(t)


if __name__ == "__main__":
    sys.exit(main())
