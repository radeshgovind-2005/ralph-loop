#!/usr/bin/env python3
"""ralph.py: plan writes nothing, apply never overwrites, detection, doctor, status."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RALPH = Path(__file__).resolve().parent.parent / "skills" / "ralph-loop" / "scripts" / "ralph.py"
passed = failed = 0
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def expect(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


def ralph(t, *args, env=None):
    return subprocess.run([sys.executable, str(RALPH), *args, "--target", str(t)], capture_output=True, text=True, env=env or GIT_ENV)


def proj(branch="work"):
    t = Path(tempfile.mkdtemp())
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=t, check=True)
    return t


INSTALLED = ["loop.sh", "PROMPT_plan.md", "PROMPT_build.md", "IMPLEMENTATION_PLAN.md", "specs/_TEMPLATE.md",
             "AGENTS.md", ".ralph/config", ".ralph/settings.json", ".ralph/hooks/guard.py", ".ralph/hooks/gate.py", ".ralph/.gitignore"]

# plan writes nothing
t = proj()
r = ralph(t, "plan")
expect("plan exits 0", r.returncode == 0, r.stderr)
expect("plan writes nothing", [p.name for p in t.iterdir()] == [".git"], str(list(t.iterdir())))
expect("plan lists creates", r.stdout.count("CREATE") == len(INSTALLED), r.stdout)

# apply creates everything; executables are executable
r = ralph(t, "apply", "--check", "true")
expect("apply exits 0", r.returncode == 0, r.stderr)
for rel in INSTALLED:
    expect(f"installed {rel}", (t / rel).exists())
for rel in ("loop.sh", ".ralph/hooks/guard.py", ".ralph/hooks/gate.py"):
    expect(f"{rel} executable", os.access(t / rel, os.X_OK))
expect("config has check", 'RALPH_CHECK="true"' in (t / ".ralph/config").read_text())

# second apply: all SKIP
r = ralph(t, "apply", "--check", "true")
expect("second apply all skip", "CREATE" not in r.stdout and "CONFLICT" not in r.stdout and "MERGE" not in r.stdout, r.stdout)

# a changed file is never overwritten
(t / "loop.sh").write_text("# my version\n")
(t / ".ralph/config").write_text('RALPH_CHECK="mine"\n')
r = ralph(t, "apply")
expect("conflict reported", "CONFLICT loop.sh" in r.stdout, r.stdout)
expect("original kept", (t / "loop.sh").read_text() == "# my version\n")
expect("new version beside it", (t / "loop.sh.ralph-new").exists() and os.access(t / "loop.sh.ralph-new", os.X_OK))
expect("config is yours", (t / ".ralph/config").read_text() == 'RALPH_CHECK="mine"\n')

# existing AGENTS.md is merged, not replaced
t = proj()
(t / "AGENTS.md").write_text("# Mine\n\nkeep me\n")
r = ralph(t, "apply", "--check", "true")
text = (t / "AGENTS.md").read_text()
expect("AGENTS merge", "MERGE    AGENTS.md" in r.stdout and text.startswith("# Mine\n\nkeep me\n") and "<!-- ralph:start -->" in text, r.stdout)
r = ralph(t, "apply")
expect("AGENTS second run skips", "SKIP     AGENTS.md" in r.stdout, r.stdout)

# detection
t = proj()
(t / "package.json").write_text(json.dumps({"scripts": {"test": "jest", "lint": "eslint .", "build": "tsc"}}))
r = ralph(t, "plan")
expect("node detected", "stack: node (npm)" in r.stdout and "check: npm run lint && npm run test" in r.stdout, r.stdout)
expect("node tools", "Bash(npm *)" in r.stdout, r.stdout)
t = proj()
(t / "package.json").write_text(json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}))
expect("npm placeholder test ignored", "check: (none detected" in ralph(t, "plan").stdout)
t = proj()
(t / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
r = ralph(t, "plan")
expect("python + ruff detected", "check: ruff check . && python3 -m pytest -q" in r.stdout, r.stdout)
t = proj()
(t / "go.mod").write_text("module x\n")
expect("go detected", "check: go vet ./... && go test ./..." in ralph(t, "plan").stdout)
t = proj()
expect("unknown stack has no check", "check: (none detected" in ralph(t, "plan").stdout)
r = ralph(t, "apply", "--check", 'npm test -- --grep "x"')
expect("double quotes rejected", r.returncode != 0 and "single quotes" in r.stderr, r.stderr)

# regression (found by e2e_real.sh): the agent must be allowed to run the check, whatever the stack
t = proj()
ralph(t, "apply", "--check", "python3 -m pytest -q")
cfg = (t / ".ralph/config").read_text()
expect("check command allowed on unknown stack", "Bash(python3 *)" in cfg, cfg)
expect("doctor: check runnable by agent", "PASS agent may run the check" in ralph(t, "doctor").stdout)
t = proj()
ralph(t, "apply", "--check", "ruff check . && CI=1 npm test", "--allowed", "Bash(git *)")
cfg = (t / ".ralph/config").read_text()
expect("--allowed still gets check tools", 'RALPH_ALLOWED_TOOLS="Bash(git *),Bash(ruff *),Bash(npm *)"' in cfg, cfg)
t = proj()
ralph(t, "apply", "--check", "true")
(t / ".ralph/config").write_text('RALPH_CHECK="python3 -m pytest -q"\nRALPH_ALLOWED_TOOLS="Bash(git *)"\n')
r = ralph(t, "doctor")
expect("doctor fails when agent can't run the check", r.returncode == 1 and "FAIL agent may run the check" in r.stdout and "Bash(python3 *)" in r.stdout, r.stdout)
env = dict(GIT_ENV, RALPH_YOLO="1")
expect("doctor: yolo covers it", "PASS agent may run the check" in ralph(t, "doctor", env=env).stdout)

# doctor
t = proj()
ralph(t, "apply", "--check", "true")
r = ralph(t, "doctor")
expect("doctor passes on good setup", r.returncode == 0 and "0 fail" in r.stdout, r.stdout)
expect("doctor proves guard", "PASS guard blocks a spec edit" in r.stdout, r.stdout)
t = proj()
ralph(t, "apply", "--check", "")
r = ralph(t, "doctor")
expect("doctor fails with no check", r.returncode == 1 and "FAIL RALPH_CHECK set" in r.stdout, r.stdout)
t = proj()
ralph(t, "apply", "--check", "definitely-not-a-command-xyz")
r = ralph(t, "doctor")
expect("doctor fails on missing command", r.returncode == 1 and "command not found" in r.stdout, r.stdout)
t = proj()
ralph(t, "apply", "--check", "false")
r = ralph(t, "doctor")
expect("doctor warns on red check", r.returncode == 0 and "WARN RALPH_CHECK" in r.stdout, r.stdout)
t = proj(branch="main")
ralph(t, "apply", "--check", "true")
expect("doctor warns on main", "WARN working branch" in ralph(t, "doctor").stdout)
t = Path(tempfile.mkdtemp())
expect("doctor fails before apply", ralph(t, "doctor").returncode == 1)

# status
t = proj()
ralph(t, "apply", "--check", "true")
(t / "IMPLEMENTATION_PLAN.md").write_text("# Plan\n## Tasks\n- [x] a\n- [ ] b\n- [ ] c\n\n## Questions\n- Which DB?\n")
(t / ".ralph/STOP").write_text("need creds\n")
(t / ".ralph/logs/20261114-000000-build-1.log").write_text("did b\nlast line here\n")
r = ralph(t, "status")
out = r.stdout
expect("status counts", "plan: 1 done, 2 open" in out, out)
expect("status next", "next: b" in out, out)
expect("status questions", "Which DB?" in out, out)
expect("status stop", "STOPPED: need creds" in out, out)
expect("status log tail", "last line here" in out, out)

print(f"install: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
