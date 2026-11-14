#!/usr/bin/env python3
"""Guard and stop-gate hooks, fed hook JSON on stdin the way Claude Code does."""
import json
import os
import subprocess
import sys
import tempfile

HOOKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "ralph-loop", "assets", ".ralph", "hooks")
GUARD, GATE = os.path.join(HOOKS, "guard.py"), os.path.join(HOOKS, "gate.py")
ROOT = tempfile.mkdtemp()
passed = failed = 0


def hook(script, payload, **env):
    e = dict(os.environ, CLAUDE_PROJECT_DIR=ROOT)
    for k in ("RALPH_MODE", "RALPH_CHECK", "RALPH_PLAN", "RALPH_GATE_MAX"):
        e.pop(k, None)
    e.update(env)
    return subprocess.run([sys.executable, script], input=json.dumps(payload), capture_output=True, text=True, env=e)


def expect(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


def edit(path, new="x", old="", tool="Edit"):
    return {"tool_name": tool, "tool_input": {"file_path": os.path.join(ROOT, path), "old_string": old, "new_string": new}, "cwd": ROOT}


def write(path, content="x"):
    return {"tool_name": "Write", "tool_input": {"file_path": os.path.join(ROOT, path), "content": content}, "cwd": ROOT}


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": ROOT}


# (name, mode, payload, should_block)
GUARD_CASES = [
    ("edit src in build", "build", edit("src/app.py"), False),
    ("edit spec in build", "build", edit("specs/auth.md"), True),
    ("write new spec in build", "build", write("specs/new.md"), True),
    ("edit loop.sh", "build", edit("loop.sh"), True),
    ("edit build prompt", "build", edit("PROMPT_build.md"), True),
    ("edit .ralph/config", "build", edit(".ralph/config"), True),
    ("edit guard itself", "build", edit(".ralph/hooks/guard.py"), True),
    ("edit claude settings", "build", edit(".claude/settings.json"), True),
    ("write .ralph/STOP", "build", write(".ralph/STOP", "need creds"), False),
    ("edit plan in build", "build", edit("IMPLEMENTATION_PLAN.md"), False),
    ("edit AGENTS.md in build", "build", edit("AGENTS.md"), False),
    ("plan mode: edit plan", "plan", edit("IMPLEMENTATION_PLAN.md"), False),
    ("plan mode: edit src", "plan", edit("src/app.py"), True),
    ("plan mode: redirect into src", "plan", bash("echo x > src/app.py"), True),
    ("plan mode: edit spec", "plan", edit("specs/a.md"), True),
    ("add pytest skip", "build", edit("tests/test_a.py", new="@pytest.mark.skip\ndef test_a(): pass"), True),
    ("add it.skip", "build", edit("src/a.test.ts", new="it.skip('x', () => {})"), True),
    ("add xit", "build", edit("src/a.spec.js", new="xit('x', () => {})"), True),
    ("existing skip kept", "build", edit("tests/test_a.py", old="@pytest.mark.skip\n", new="@pytest.mark.skip\n# note"), False),
    ("skip word in non-test file", "build", edit("src/a.py", new="it.skip("), False),
    ("normal test edit", "build", edit("tests/test_a.py", new="def test_a(): assert f() == 2"), False),
    ("multiedit adds skip", "build", {"tool_name": "MultiEdit", "tool_input": {"file_path": os.path.join(ROOT, "tests/test_b.py"), "edits": [{"old_string": "a", "new_string": "@pytest.mark.skip"}]}, "cwd": ROOT}, True),
    ("bash: run tests", "build", bash("python3 -m pytest -q"), False),
    ("bash: git commit", "build", bash('git add -A && git commit -m "feat: x"'), False),
    ("bash: echo STOP", "build", bash('echo "need a decision" > .ralph/STOP'), False),
    ("bash: redirect into spec", "build", bash("echo x >> specs/a.md"), True),
    ("bash: sed -i spec", "build", bash("sed -i '' 's/a/b/' specs/a.md"), True),
    ("bash: sed read spec", "build", bash("sed -n 1,5p specs/a.md"), False),
    ("bash: cat spec", "build", bash("cat specs/a.md"), False),
    ("bash: cp over loop.sh", "build", bash("cp /tmp/x loop.sh"), True),
    ("bash: tee into .ralph/config", "build", bash("echo x | tee .ralph/config"), True),
    ("bash: rm test file", "build", bash("rm tests/test_a.py"), True),
    ("bash: git rm test file", "build", bash("git rm -q src/a.test.ts"), True),
    ("bash: mv test away", "build", bash("mv tests/test_a.py /tmp/"), True),
    ("bash: rm src file", "build", bash("rm src/old.py"), False),
    ("bash: rm -rf", "build", bash("rm -rf build"), True),
    ("bash: rm -r -f", "build", bash("rm -r -f build"), True),
    ("bash: force push", "build", bash("git push --force origin work"), True),
    ("bash: push -f", "build", bash("git push -f"), True),
    ("bash: + refspec", "build", bash("git push origin +work"), True),
    ("bash: normal push", "build", bash("git push -u origin HEAD"), False),
    ("bash: reset --hard", "build", bash("git reset --hard HEAD~1"), True),
    ("bash: clean -fd", "build", bash("git clean -fd"), True),
    ("bash: --no-verify", "build", bash("git commit --no-verify -m x"), True),
    ("bash: commit -n", "build", bash("git commit -nm x"), True),
    ("bash: commit -m with n in message", "build", bash('git commit -m "fix: n"'), False),
    ("bash: sh -c hides rm -rf", "build", bash("sh -c 'rm -rf src'"), True),
    ("bash: env wrapper", "build", bash("env FOO=1 git reset --hard"), True),
    ("bash: chained", "build", bash("ls && git reset --hard"), True),
    ("bash: quoted && not split", "build", bash("echo 'a && git reset --hard'"), False),
    ("read tool ignored", "build", {"tool_name": "Read", "tool_input": {"file_path": os.path.join(ROOT, "specs/a.md")}, "cwd": ROOT}, False),
    ("mode unset = build", None, edit("specs/a.md"), True),
]

for name, mode, payload, block in GUARD_CASES:
    env = {"RALPH_MODE": mode} if mode else {}
    r = hook(GUARD, payload, **env)
    expect(f"guard: {name}", (r.returncode == 2) == block, f"(exit {r.returncode}, stderr {r.stderr.strip()[:100]})")
    if block and r.returncode == 2:
        expect(f"guard: {name} explains", "ralph guard blocked" in r.stderr)

r = subprocess.run([sys.executable, GUARD], input="not json", capture_output=True, text=True)
expect("guard: bad input fails open", r.returncode == 0)

# ---- gate
stop = {"session_id": "s1", "stop_hook_active": False, "cwd": ROOT}
os.makedirs(os.path.join(ROOT, ".ralph"), exist_ok=True)


def decision(r):
    return json.loads(r.stdout)["decision"] if r.stdout.strip() else "allow"


r = hook(GATE, stop, RALPH_MODE="build")
expect("gate: no check allows", r.returncode == 0 and decision(r) == "allow")
r = hook(GATE, stop, RALPH_MODE="plan", RALPH_CHECK="false")
expect("gate: plan mode allows", decision(r) == "allow")
r = hook(GATE, stop, RALPH_MODE="build", RALPH_CHECK="true")
expect("gate: green allows", decision(r) == "allow")

for n in (1, 2, 3):
    r = hook(GATE, stop, RALPH_MODE="build", RALPH_CHECK="echo boom-output; exit 3", RALPH_GATE_MAX="3")
    expect(f"gate: red blocks ({n}/3)", decision(r) == "block", r.stdout)
    if n == 1:
        reason = json.loads(r.stdout)["reason"]
        expect("gate: reason has output", "boom-output" in reason and "Exit code: 3" in reason, reason)
        expect("gate: reason has counter", "gate 1/3" in reason, reason)
r = hook(GATE, stop, RALPH_MODE="build", RALPH_CHECK="exit 3", RALPH_GATE_MAX="3")
expect("gate: cap reached allows", decision(r) == "allow" and "still failing" in r.stderr)
r = hook(GATE, dict(stop, session_id="s2"), RALPH_MODE="build", RALPH_CHECK="exit 3")
expect("gate: counter is per session", decision(r) == "block")

open(os.path.join(ROOT, ".ralph", "STOP"), "w").write("need creds")
r = hook(GATE, dict(stop, session_id="s3"), RALPH_MODE="build", RALPH_CHECK="exit 3")
expect("gate: STOP file allows", decision(r) == "allow")
os.remove(os.path.join(ROOT, ".ralph", "STOP"))

r = hook(GATE, dict(stop, session_id="../../evil"), RALPH_MODE="build", RALPH_CHECK="exit 3")
expect("gate: session id can't escape state dir", os.path.exists(os.path.join(ROOT, ".ralph", "state", "gate-evil")))

print(f"hooks: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
