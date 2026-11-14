#!/bin/bash
# Loop behaviour with a fake agent. Installs the real assets with ralph.py into a scratch repo.
HERE="$(cd "$(dirname "$0")" && pwd)"
RALPH="$HERE/../skills/ralph-loop/scripts/ralph.py"
STUB="$HERE/stub-claude"
WORK=$(mktemp -d)
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export CLAUDE_BIN="$STUB"
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL $1: expected [$2] got [$3]"; fi; }
args() { tr '\n' ' ' < .ralph/state/last-args | sed 's/ $//'; }

newproj() {  # $1 = check command
  rm -rf "$WORK/p"; mkdir -p "$WORK/p"; cd "$WORK/p" || exit 1
  git init -q -b work
  python3 "$RALPH" apply --check "${1:-true}" >/dev/null || { echo "apply failed"; exit 1; }
  git add -A && git commit -qm init
}
items() {  # $1 = number of open items
  { printf '# Plan\n## Tasks\n'; for n in $(seq 1 "$1"); do printf -- '- [ ] task %s — verify: true\n' "$n"; done; printf -- '- [x] old\n'; } > IMPLEMENTATION_PLAN.md
  git add -A; git commit -qm plan
}

# --- happy path
newproj; items 3; out=$(STUB_MODE=tick ./loop.sh build 10 2>&1); rc=$?
check "complete exits 0" 0 $rc
check "3 iterations" 3 "$(echo "$out" | grep -c '] iteration [0-9]')"
check "check ran each iteration" 3 "$(echo "$out" | grep -c 'check passed')"
check "no open items" 0 "$(grep -c '\[ \]' IMPLEMENTATION_PLAN.md)"
check "prompt on stdin" "You are in BUILD mode. You get one task this iteration. Your memory does not carry" "$(cat .ralph/state/last-stdin)"
check "default args from config" "-p --permission-mode acceptEdits --allowedTools Bash(git *),Bash(ls *),Bash(mkdir *),Bash(cat *),Bash(true *) --settings .ralph/settings.json --max-budget-usd 5" "$(args)"
check "env exported to hooks" "RALPH_MODE=build RALPH_CHECK=true RALPH_GATE_MAX=3" "$(tr '\n' ' ' < .ralph/state/last-env | sed 's/ $//')"
check "tree clean (logs/state ignored)" "" "$(git status --porcelain)"
check "3 logs" 3 "$(find .ralph/logs -name '*.log' | wc -l | tr -d ' ')"

# --- stop conditions
newproj; items 3; STUB_MODE=tick ./loop.sh build 2 >/dev/null 2>&1; check "max iterations exits 1" 1 $?
newproj; items 3; out=$(STUB_MODE=noop ./loop.sh build 10 2>&1); rc=$?
check "stall exits 4" 4 $rc; check "stalled after 3" 3 "$(echo "$out" | grep -c '] iteration [0-9]')"
newproj; items 3; STUB_MODE=stop ./loop.sh build 10 >/dev/null 2>&1; check "STOP exits 3" 3 $?
./loop.sh build 10 >/dev/null 2>&1; check "existing STOP refuses to start" 2 $?
newproj; items 3; out=$(STUB_MODE=fail ./loop.sh build 10 2>&1); rc=$?
check "agent failures exit 5" 5 $rc; check "exit code logged" 1 "$(echo "$out" | grep -c 'agent exited 7 (3/3)')"

# --- the loop's own check
newproj 'test ! -f BROKEN'; items 5; out=$(STUB_MODE='break' ./loop.sh build 10 2>&1); rc=$?
check "red checks exit 6" 6 $rc
check "red 3 times" 3 "$(echo "$out" | grep -c 'check FAILED')"
check "CHECK_FAILED written" 1 "$(grep -c 'RALPH_CHECK failed' .ralph/CHECK_FAILED)"
check "CHECK_FAILED ignored by git" "" "$(git status --porcelain)"
newproj 'test ! -f BROKEN'; items 1; out=$(STUB_MODE=breakonce ./loop.sh build 10 2>&1); rc=$?
check "red then fixed exits 0" 0 $rc
check "not done while red: 2 iterations" 2 "$(echo "$out" | grep -c '] iteration [0-9]')"
check "CHECK_FAILED cleared" "no" "$([ -f .ralph/CHECK_FAILED ] && echo yes || echo no)"
newproj 'test ! -f BROKEN'; items 1; touch BROKEN; git add -A; git commit -qm b
STUB_MODE=tick ./loop.sh build 1 >/dev/null 2>&1; check "items done but red is not finished" 1 $?

# --- modes and args
newproj; out=$(./loop.sh build 2>&1); check "empty plan refuses build" 2 $?
newproj; out=$(STUB_MODE=noop ./loop.sh plan 2>&1); rc=$?
check "plan mode exits 0" 0 $rc; check "plan mode 1 iteration" 1 "$(echo "$out" | grep -c '] iteration [0-9]')"
check "plan prompt" "You are in PLANNING mode. Do not implement anything." "$(cat .ralph/state/last-stdin)"
check "plan mode exported" "RALPH_MODE=plan" "$(head -1 .ralph/state/last-env)"
newproj; items 3; STUB_MODE=tick RALPH_YOLO=1 RALPH_MODEL=claude-opus-5-5 RALPH_STREAM=1 RALPH_HOOKS=0 RALPH_BUDGET_USD=9 ./loop.sh build 1 >/dev/null 2>&1
check "env overrides config" "-p --model claude-opus-5-5 --dangerously-skip-permissions --max-budget-usd 9 --output-format stream-json --verbose" "$(args)"
newproj; ./loop.sh bogus >/dev/null 2>&1; check "bad mode" 2 $?
./loop.sh build 0 >/dev/null 2>&1; check "max 0" 2 $?
./loop.sh build x >/dev/null 2>&1; check "max x" 2 $?
CLAUDE_BIN=nope-not-here ./loop.sh plan >/dev/null 2>&1; check "missing CLI" 2 $?

rm -rf "$WORK"
echo "loop: $pass passed, $fail failed"; [ "$fail" -eq 0 ]
