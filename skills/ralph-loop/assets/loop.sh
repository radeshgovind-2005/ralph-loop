#!/usr/bin/env bash
# Ralph loop: feed the same prompt to a fresh Claude Code context, again and again.
# State lives in files (specs/, IMPLEMENTATION_PLAN.md, AGENTS.md) and git, never in the context window.
#
# Usage: ./loop.sh [plan|build] [max_iterations]
#   ./loop.sh plan          gap analysis -> IMPLEMENTATION_PLAN.md (default 1 iteration)
#   ./loop.sh build         one plan item per iteration until none are open (default 20)
#   ./loop.sh build 50
#
# Exit codes: 0 done   1 hit max iterations   2 usage/setup error
#             3 stopped via .ralph/STOP   4 stalled (no new commits)   5 agent kept failing
#             6 checks stayed red
#
# Stop it gracefully from another shell:  echo "reason" > .ralph/STOP

set -uo pipefail

# ---- config: .ralph/config, then env vars win over it, then these defaults ----
load_config() {
  local k v
  [ -f .ralph/config ] || return 0
  while IFS='=' read -r k v || [ -n "$k" ]; do
    case "$k" in RALPH_*|CLAUDE_BIN) ;; *) continue ;; esac
    v="${v%\"}"; v="${v#\"}"
    if [ -z "${!k+x}" ]; then printf -v "$k" '%s' "$v"; fi
  done < .ralph/config
}
load_config

CLAUDE_BIN="${CLAUDE_BIN:-claude}"
RALPH_MODEL="${RALPH_MODEL:-}"               # e.g. claude-opus-5-5; empty = CLI default
RALPH_PLAN="${RALPH_PLAN:-IMPLEMENTATION_PLAN.md}"
RALPH_CHECK="${RALPH_CHECK:-}"               # the command that proves the work: tests, types, lint
RALPH_ALLOWED_TOOLS="${RALPH_ALLOWED_TOOLS:-Bash(git *),Bash(ls *),Bash(mkdir *)}"
RALPH_HOOKS="${RALPH_HOOKS:-1}"              # 1 = load .ralph/settings.json (guard + test gate)
RALPH_BUDGET_USD="${RALPH_BUDGET_USD:-}"     # per-iteration spend cap; empty = none
RALPH_PUSH="${RALPH_PUSH:-0}"                # 1 = git push after every iteration
RALPH_MAX_STALLS="${RALPH_MAX_STALLS:-3}"    # build: stop after N iterations with no new commit
RALPH_MAX_FAILS="${RALPH_MAX_FAILS:-3}"      # stop after N consecutive non-zero agent exits
RALPH_MAX_RED="${RALPH_MAX_RED:-3}"          # stop after N consecutive iterations with red checks
RALPH_GATE_MAX="${RALPH_GATE_MAX:-3}"        # times the test gate may send the agent back per iteration
RALPH_STREAM="${RALPH_STREAM:-0}"            # 1 = log the full stream-json trace
RALPH_YOLO="${RALPH_YOLO:-0}"                # 1 = --dangerously-skip-permissions. Sandbox/VM only.
# -------------------------------------------------------------------------------

D=.ralph
STOP_FILE="$D/STOP"
RED_FILE="$D/CHECK_FAILED"
die() { printf 'ralph: %s\n' "$*" >&2; exit 2; }
log() { printf '[ralph %s] %s\n' "$(date +%H:%M:%S)" "$*"; }

MODE="${1:-build}"
case "$MODE" in
  plan)      DEFAULT_MAX=1 ;;
  build)     DEFAULT_MAX=20 ;;
  -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
  *)         die "unknown mode '$MODE' (use plan or build)" ;;
esac
MAX="${2:-$DEFAULT_MAX}"
case "$MAX" in ''|*[!0-9]*) die "max_iterations must be a positive integer" ;; esac
[ "$MAX" -ge 1 ] || die "max_iterations must be a positive integer"

PROMPT_FILE="PROMPT_${MODE}.md"
[ -f "$PROMPT_FILE" ] || die "missing $PROMPT_FILE (run loop.sh from the project root)"
command -v "$CLAUDE_BIN" >/dev/null 2>&1 || die "'$CLAUDE_BIN' not found on PATH"

mkdir -p "$D/logs" "$D/state" || die "cannot create $D/logs"
[ -f "$D/.gitignore" ] || printf 'logs/\nstate/\nSTOP\nCHECK_FAILED\n' > "$D/.gitignore"
[ ! -f "$STOP_FILE" ] || die "$STOP_FILE exists ($(cat "$STOP_FILE")). Delete it to run again."

count()      { local n; n=$(grep -cE "$1" "$RALPH_PLAN" 2>/dev/null) || true; echo "${n:-0}"; }
open_items() { count '^[[:space:]]*[-*] \[ \]'; }
all_items()  { count '^[[:space:]]*[-*] \[[ xX]\]'; }
in_git()     { git rev-parse --is-inside-work-tree >/dev/null 2>&1; }
head_sha()   { git rev-parse HEAD 2>/dev/null || echo none; }
finished()   { [ "$(open_items)" -eq 0 ] && [ ! -f "$RED_FILE" ]; }

# The loop's own check. The agent's word that tests pass is not evidence; this is.
run_check() {
  local out rc
  out=$(sh -c "$RALPH_CHECK" 2>&1); rc=$?
  if [ "$rc" -eq 0 ]; then rm -f "$RED_FILE"; return 0; fi
  { echo "RALPH_CHECK failed (exit $rc): $RALPH_CHECK"; echo; printf '%s\n' "$out" | tail -n 60; } > "$RED_FILE"
  return 1
}

if [ "$MODE" = build ]; then
  [ "$(all_items)" -gt 0 ] || die "$RALPH_PLAN has no checklist items. Run ./loop.sh plan first."
  in_git || log "warning: not a git repo, so no stall detection and no per-iteration history"
  [ -n "$RALPH_CHECK" ] || log "warning: RALPH_CHECK is empty, so nothing verifies the agent's work"
fi

ARGS=(-p)
if [ -n "$RALPH_MODEL" ]; then ARGS+=(--model "$RALPH_MODEL"); fi
if [ "$RALPH_YOLO" = 1 ]; then
  ARGS+=(--dangerously-skip-permissions)
else
  ARGS+=(--permission-mode acceptEdits --allowedTools "$RALPH_ALLOWED_TOOLS")
fi
if [ "$RALPH_HOOKS" = 1 ] && [ -f "$D/settings.json" ]; then ARGS+=(--settings "$D/settings.json"); fi
if [ -n "$RALPH_BUDGET_USD" ]; then ARGS+=(--max-budget-usd "$RALPH_BUDGET_USD"); fi
if [ "$RALPH_STREAM" = 1 ]; then ARGS+=(--output-format stream-json --verbose); fi

# The hooks read these.
export RALPH_MODE="$MODE" RALPH_PLAN RALPH_CHECK RALPH_GATE_MAX

trap 'echo; log "interrupted"; exit 130' INT TERM

log "mode=$MODE max=$MAX prompt=$PROMPT_FILE plan=$RALPH_PLAN hooks=$RALPH_HOOKS"
i=0; stalls=0; fails=0; reds=0
while [ "$i" -lt "$MAX" ]; do
  if [ "$MODE" = build ] && finished; then log "plan complete after $i iteration(s)"; exit 0; fi
  i=$((i + 1))
  logfile="$D/logs/$(date +%Y%m%d-%H%M%S)-$MODE-$i.log"
  before=$(head_sha)
  log "iteration $i/$MAX, open items: $(open_items), log: $logfile"

  # Fresh context every time: the prompt goes in on stdin, nothing carries over but the files.
  "$CLAUDE_BIN" "${ARGS[@]}" < "$PROMPT_FILE" 2>&1 | tee "$logfile"
  rc=${PIPESTATUS[0]}

  if [ "$rc" -ne 0 ]; then
    fails=$((fails + 1)); log "agent exited $rc ($fails/$RALPH_MAX_FAILS)"
    if [ "$fails" -ge "$RALPH_MAX_FAILS" ]; then log "too many consecutive failures"; exit 5; fi
  else
    fails=0
  fi

  if [ -f "$STOP_FILE" ]; then log "stopped: $(cat "$STOP_FILE")"; exit 3; fi

  if [ "$MODE" = build ] && [ -n "$RALPH_CHECK" ]; then
    if run_check; then
      reds=0; log "check passed"
    else
      reds=$((reds + 1)); log "check FAILED ($reds/$RALPH_MAX_RED); next iteration must fix it (see $RED_FILE)"
      if [ "$reds" -ge "$RALPH_MAX_RED" ]; then log "checks stayed red"; exit 6; fi
    fi
  fi

  if [ "$MODE" = build ] && in_git; then
    if [ "$(head_sha)" = "$before" ]; then
      stalls=$((stalls + 1)); log "no new commit ($stalls/$RALPH_MAX_STALLS)"
      if [ "$stalls" -ge "$RALPH_MAX_STALLS" ]; then log "stalled"; exit 4; fi
    else
      stalls=0
    fi
  fi

  if [ "$RALPH_PUSH" = 1 ] && in_git; then
    git push -u origin HEAD || log "push failed, continuing"
  fi
done

if [ "$MODE" = build ]; then
  if finished; then log "plan complete after $i iteration(s)"; exit 0; fi
  log "hit max iterations ($MAX): $(open_items) item(s) open$([ -f "$RED_FILE" ] && echo ', checks red')"; exit 1
fi
log "plan mode finished. Review $RALPH_PLAN, then run ./loop.sh build"
