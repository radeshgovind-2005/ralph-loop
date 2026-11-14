#!/usr/bin/env python3
"""ralph gate: Stop hook, loaded only for loop runs.

When the agent tries to end a build iteration, run RALPH_CHECK. If it fails, block the stop and
hand the failure back, so the agent fixes it in the same context. After RALPH_GATE_MAX blocks in
one session, let it stop; loop.sh runs the check again and the next iteration has to fix it.

Allows the stop (exit 0, no output) when: not build mode, no RALPH_CHECK, .ralph/STOP exists
(the agent asked for a human), the check passes, or the retry cap is reached.
"""
import json
import os
import re
import subprocess
import sys

TAIL = 60


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    check = os.environ.get("RALPH_CHECK", "").strip()
    if os.environ.get("RALPH_MODE", "build") != "build" or not check:
        sys.exit(0)
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    if os.path.exists(os.path.join(root, ".ralph", "STOP")):
        sys.exit(0)

    try:
        cap = int(os.environ.get("RALPH_GATE_MAX", "3"))
    except ValueError:
        cap = 3
    sid = re.sub(r"[^A-Za-z0-9_-]", "", str(data.get("session_id", "nosession")))[:64] or "nosession"
    state_dir = os.path.join(root, ".ralph", "state")
    os.makedirs(state_dir, exist_ok=True)
    counter = os.path.join(state_dir, f"gate-{sid}")
    try:
        blocks = int(open(counter).read().strip() or 0)
    except (OSError, ValueError):
        blocks = 0

    proc = subprocess.run(["sh", "-c", check], cwd=root, capture_output=True, text=True)
    if proc.returncode == 0:
        sys.exit(0)
    if blocks >= cap:
        sys.stderr.write(f"ralph gate: checks still failing after {cap} retries; letting the loop handle it.\n")
        sys.exit(0)

    with open(counter, "w") as f:
        f.write(str(blocks + 1))
    out = (proc.stdout + proc.stderr).strip().splitlines()[-TAIL:]
    reason = (
        f"The project checks fail, so this iteration is not done (gate {blocks + 1}/{cap}).\n"
        f"Command: {check}\nExit code: {proc.returncode}\nLast output:\n" + "\n".join(out) + "\n\n"
        "Fix the cause and commit. Don't skip or weaken tests. "
        "If you can't fix it without a human, write one line to .ralph/STOP and end."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


if __name__ == "__main__":
    main()
