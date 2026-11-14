# ralph-loop

A Claude Code skill that sets up a Ralph loop for you by asking questions, then helps you run
and fix it.

A Ralph loop runs the same prompt through a fresh `claude -p` session over and over. Each
iteration does one item from a plan, proves it with your checks and commits. Nothing carries
over but files and git, so the context never fills up with old work.

```
you brainstorm ──► specs/*.md ──► ./loop.sh plan ──► IMPLEMENTATION_PLAN.md ──► ./loop.sh build
                                                                                  │
                         one item ─► guard ─► stop gate (checks) ─► commit ─► loop's own check ─┘
```

## Use it

Say "set up a ralph loop" in a project. The skill:

1. detects your stack and check command,
2. interviews you one question at a time and writes `specs/` from your answers,
3. installs the loop files (never overwriting yours) and runs `doctor` to prove they work,
4. hands you `./loop.sh plan`, reviews the plan with you, then hands you `./loop.sh build`.

Later: "how's the loop doing?" (status) or "the loop is stuck" (tune).

## What gets installed

| Path | Purpose |
|---|---|
| `loop.sh` | The loop. Reads `.ralph/config`; env vars override it. |
| `PROMPT_plan.md`, `PROMPT_build.md` | The two prompts. |
| `specs/` | What to build. You own it; the agent can't edit it in build mode. |
| `IMPLEMENTATION_PLAN.md` | The agent's checklist. Build ends when nothing is open and checks are green. |
| `AGENTS.md` (Ralph section) | How to build and test. Loaded every iteration. |
| `.ralph/config` | `RALPH_CHECK`, allowed tools, model, budget. Yours after install. |
| `.ralph/settings.json`, `.ralph/hooks/` | Hooks, loaded only by `loop.sh` via `--settings`. Your normal sessions don't see them. |

## The three layers of checking

1. **Guard** (PreToolUse hook). Blocks edits to `specs/`, the loop's own files and `.ralph/`;
   deleting or skipping tests; force push, `reset --hard`, `rm -rf`. In plan mode, it blocks
   every edit except the plan.
2. **Stop gate** (Stop hook). When the agent tries to finish, it runs `RALPH_CHECK`. If it fails,
   the agent is sent back with the output, up to 3 times per iteration.
3. **The loop's own check.** After every iteration `loop.sh` runs `RALPH_CHECK` itself. Red
   writes `.ralph/CHECK_FAILED`, and the next iteration must fix it before anything else. Three
   red iterations in a row stop the loop.

The hooks are text guards. They stop lazy and accidental shortcuts, not determined ones. Layer 3
doesn't depend on the agent at all.

## Stop conditions

| Exit | Why |
|---|---|
| 0 | No open items and checks green (build), or plan finished |
| 1 | Hit the iteration cap |
| 2 | Setup error |
| 3 | `.ralph/STOP` exists: the agent needs you, or you asked it to pause |
| 4 | No new commit for 3 iterations |
| 5 | The `claude` CLI failed 3 times in a row |
| 6 | Checks red for 3 iterations in a row |

## Safety

- By default the agent may edit files and run only the commands in `RALPH_ALLOWED_TOOLS`.
- `RALPH_YOLO=1` skips all permission checks. Use it only in a container or VM.
- `RALPH_BUDGET_USD` caps spend per iteration (default 5).
- Work on a branch. The loop commits every iteration.

## Develop

```bash
bash tests/run_all.sh
```
