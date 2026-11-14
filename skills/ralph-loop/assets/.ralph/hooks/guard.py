#!/usr/bin/env python3
"""ralph guard: PreToolUse hook, loaded only for loop runs (loop.sh passes --settings .ralph/settings.json).

Turns the prompt's "never" rules into hard blocks. Reads hook JSON on stdin.
  block -> reason on stderr, exit 2 (the tool call does not run; the agent sees why)
  allow -> exit 0

Policy (RALPH_MODE from loop.sh; unset means build):
  plan mode   file edits only to the plan file (RALPH_PLAN)
  build mode  no edits to specs/
  both        no edits to loop.sh, PROMPT_*.md, .ralph/** (except writing .ralph/STOP),
              .claude/settings*.json; no deleting test files; no adding test skips;
              no force push, reset --hard, clean -f, rm -rf, --no-verify / commit -n

Limit: a text guard. It stops lazy and accidental bypass, not code that builds commands at run
time. The loop's own RALPH_CHECK run after each iteration is the real gate.
"""
import json
import os
import re
import shlex
import sys

MODE = os.environ.get("RALPH_MODE", "build")
PLAN = os.environ.get("RALPH_PLAN", "IMPLEMENTATION_PLAN.md")

LOOP_FILES = re.compile(r"(^|/)(loop\.sh|PROMPT_[^/]*\.md)$|(^|/)\.claude/settings(\.local)?\.json$")
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(_test|\.test|\.spec|_spec)\.[a-z]+$|(^|/)test_[^/]+\.py$")
SKIP_MARKERS = re.compile(
    r"@pytest\.mark\.skip|pytest\.skip\(|@unittest\.skip|\b(it|test|describe)\.skip\(|\bx(it|describe|test)\(|"
    r"\bt\.Skip(Now|f)?\(|#\[ignore\]|@Disabled\b|@Ignore\b"
)
WRITERS = {"cp", "mv", "rm", "sed", "tee", "ln", "install", "truncate", "chmod", "unlink", "dd", "patch", "perl", "awk"}
WRAPPERS = {"command", "time", "nohup", "sudo", "xargs", "exec", "nice", "env", "timeout"}


def rel(path, cwd):
    root = os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()
    p = os.path.normpath(os.path.join(cwd or root, path))
    try:
        r = os.path.relpath(p, root)
    except ValueError:
        return path
    return r.replace(os.sep, "/")


def protected(r):
    """Reason string if a project-relative path must not be written, else None."""
    if r == ".ralph/STOP":
        return None
    if r.startswith(".ralph/") or r == ".ralph":
        return ".ralph/ holds the loop's hooks, config and logs. Only .ralph/STOP may be written."
    if LOOP_FILES.search(r):
        return f"{r} drives the loop. Change it as a human, not from inside the loop."
    if MODE == "plan" and r != PLAN:
        return f"Plan mode may only edit {PLAN}."
    if MODE != "plan" and (r == "specs" or r.startswith("specs/")):
        return "specs/ is the source of truth. If a spec looks wrong, add a question to the plan or write .ralph/STOP."
    return None


def check_edit(tool, ti, cwd):
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if not path:
        return None
    r = rel(path, cwd)
    why = protected(r)
    if why:
        return why
    new = ti.get("new_string", "") or ti.get("content", "") or ti.get("new_source", "")
    for e in ti.get("edits", []) or []:
        new += "\n" + (e.get("new_string") or "")
    old = ti.get("old_string", "") or ""
    if TEST_FILE.search(r) and SKIP_MARKERS.search(new) and not SKIP_MARKERS.search(old):
        return "Skipping a test is blocked. Fix the cause, or write the blocker to .ralph/STOP."
    return None


def split_segments(cmd):
    segs, cur, quote, i = [], [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif cmd.startswith("&&", i) or cmd.startswith("||", i):
            segs.append("".join(cur)); cur = []; i += 1
        elif ch in ";|\n":
            segs.append("".join(cur)); cur = []
        else:
            cur.append(ch)
        i += 1
    segs.append("".join(cur))
    return [s.strip().lstrip("({").rstrip(")}").strip() for s in segs if s.strip()]


def short_flags(args):
    return {c for a in args if a.startswith("-") and not a.startswith("--") for c in a[1:]}


def redirect_targets(seg):
    return re.findall(r">>?\s*['\"]?([^\s'\"]+)", seg)


def check_segment(seg, cwd, depth=0):
    for target in redirect_targets(seg):
        if target != "/dev/null":
            why = protected(rel(target, cwd))
            if why:
                return why
    try:
        argv = shlex.split(seg, posix=True)
    except ValueError:
        argv = seg.split()
    while argv and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]) or os.path.basename(argv[0]) in WRAPPERS):
        argv = argv[1:]
    if not argv:
        return None
    head, args = os.path.basename(argv[0]), argv[1:]

    if head in ("sh", "bash", "zsh") and "-c" in args and depth < 3:
        i = args.index("-c")
        return check_command(args[i + 1], cwd, depth + 1) if i + 1 < len(args) else None
    if head == "eval" and depth < 3:
        return check_command(" ".join(args), cwd, depth + 1)

    if head == "rm":
        f = short_flags(args)
        if ("r" in f or "R" in f or "--recursive" in args) and ("f" in f or "--force" in args):
            return "rm -rf is blocked inside the loop. Delete specific files instead."
    if head in WRITERS:
        paths = [a for a in args if not a.startswith("-")]
        # cp/mv/ln/install write to the last path; the rest write to every path they name
        targets = paths[-1:] if head in ("cp", "mv", "ln", "install") else paths
        if head == "sed" and "-i" not in " ".join(args) and "i" not in short_flags(args):
            targets = []
        for p in targets:
            why = protected(rel(p, cwd))
            if why:
                return why
        if head in ("rm", "unlink") or (head == "mv"):
            for p in paths if head != "mv" else paths[:-1]:
                if TEST_FILE.search(rel(p, cwd)):
                    return "Deleting or moving away a test file is blocked. Fix the code, or write the blocker to .ralph/STOP."

    if head == "git" and args:
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in ("-C", "-c") else 1
        sub, rest = (args[i], args[i + 1:]) if i < len(args) else ("", [])
        if any(a.startswith("--no-ve") for a in rest) or (sub == "commit" and "n" in short_flags(rest)):
            return "Skipping git hooks is blocked. Fix the failing check."
        if sub == "push" and ("--force" in rest or "f" in short_flags(rest) or any(a.startswith("+") for a in rest)):
            return "Force push is blocked inside the loop."
        if sub == "reset" and "--hard" in rest:
            return "git reset --hard is blocked inside the loop. It throws away work."
        if sub == "clean" and ("f" in short_flags(rest) or "--force" in rest):
            return "git clean -f is blocked inside the loop."
        if sub == "rm":
            for p in rest:
                if not p.startswith("-"):
                    why = protected(rel(p, cwd))
                    if why:
                        return why
                    if TEST_FILE.search(rel(p, cwd)):
                        return "Deleting a test file is blocked. Fix the code, or write the blocker to .ralph/STOP."
    return None


def check_command(cmd, cwd, depth=0):
    for seg in split_segments(cmd):
        why = check_segment(seg, cwd, depth)
        if why:
            return why
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # fail open on bad input; the loop's own check still runs
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    cwd = data.get("cwd")
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        why = check_edit(tool, ti, cwd)
    elif tool == "Bash":
        why = check_command(ti.get("command", ""), cwd)
    else:
        why = None
    if why:
        sys.stderr.write(f"ralph guard blocked this ({MODE} mode). {why}\n")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
