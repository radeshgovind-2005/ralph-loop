---
name: ralph-loop
description: Set up, check on and tune a Ralph loop - a bash loop that runs Claude Code with a fresh context per iteration, one plan item per run, with a guard hook, a test gate and checks the loop runs itself. Use when the user says "ralph", "ralph loop", "set up a loop", "let it build overnight", "autonomous loop", "how's the loop doing", "the loop is stuck", or wants to brainstorm a project into specs for an agent to build.
---

# ralph-loop

A Ralph loop runs the same prompt through a fresh `claude -p` session again and again. Only files
and git carry over. The person's job is the inputs: specs, a check command, and reading the plan.
This skill does the rest, and asks questions instead of making them write things.

`<skill>` below means this skill's folder. Helper: `python3 <skill>/scripts/ralph.py plan|apply|doctor|status`.

Pick the mode from what they say: **setup** (no `loop.sh` yet, or "set up"), **status** ("how's it
going", "what did it do"), **tune** (stuck, stopped, red checks, bad output).

## Setup

1. **Preflight.** From the project root run `ralph.py plan`. It writes nothing. Note the detected
   stack and check command. If this isn't a git repo, or it's on `main`/`master`, say so and offer
   `git init` or a branch now. Don't continue on `main`.

2. **Brainstorm into specs.** Interview, one question per message. Use AskUserQuestion with 2-4
   options wherever a choice fits, so they can click instead of type. Order:
   1. What are we building, for whom, and what does "done" look like? (open answer)
   2. Propose 3-7 topics of concern from their answer (e.g. auth, storage, CLI). Let them pick
      and rename. One topic = one spec file.
   3. Per topic: what it MUST do, MUST NOT do, and what's out of scope. Offer your best guesses as
      options. They correct; you don't make them draft.
   4. Per topic: at least one acceptance check, "given / when / then", concrete enough to become
      a test. A topic with no testable check isn't finished. Keep asking.
   Stop when every topic has a check. Read the summary back once, then write
   `specs/<topic>.md` from `<skill>/assets/specs/_TEMPLATE.md` and show each file.

3. **The check command.** Show the detected `RALPH_CHECK`. Ask: right? If none was detected, ask
   for it. The loop is only as good as this command. No check, no loop: don't skip this step.

4. **Install.** `ralph.py apply --check "<cmd>"` (add `--allowed "<tools>"` if they need more
   commands). It never overwrites; for a CONFLICT, show the diff of `<file>.ralph-new` and merge
   with Edit only if they agree. Fill the "Build & run" part of the Ralph section in `AGENTS.md`
   from what you learned.

5. **Doctor.** `ralph.py doctor`. Show the output. Every FAIL must be fixed before going on.
   A WARN that the check is red means the first iterations will fix existing failures; say so.

6. **Plan.** The loop runs in a terminal, never inside this chat. Give them `./loop.sh plan`
   (if a terminal tool is available, offer to start it there). When it's done, read
   `IMPLEMENTATION_PLAN.md` with them: too-big items, wrong order, and every line under
   `## Questions`. Fix the specs, not the plan, then re-run plan if anything changed.

7. **Build.** Only after they say the plan looks right. Give `./loop.sh build 20`, suggest they
   watch the first two iterations, and remind them of `echo "reason" > .ralph/STOP` to pause.
   Offer to commit the setup on their branch first so iteration 1 starts clean.

## Status

Run `ralph.py status`. Tell them in a few plain lines: items done and left, what's next, whether
it's stopped or red and why, and any questions in the plan waiting for them. End with the one
thing they should do next, if any.

## Tune

The fix is almost always in the inputs. Read `.ralph/STOP`, `.ralph/CHECK_FAILED`, the last two
logs in `.ralph/logs/` and `git log -5`, then match:

| Symptom | Likely cause | Fix |
|---|---|---|
| Exit 3, STOP file | Agent needs a decision | Answer it in a spec or `AGENTS.md`, delete `.ralph/STOP` |
| Exit 4, no commits | Item too big or unclear | Split the item, sharpen its spec |
| Exit 6, checks red | Item broke something it can't fix, or a flaky check | Read `CHECK_FAILED`; fix the check or add a note to `AGENTS.md` |
| Exit 5, agent errors | CLI, auth, budget cap | Read the log tail; raise `RALPH_BUDGET_USD` if it hit the cap |
| Guard blocks in the log | Agent tried a forbidden edit | Usually fine. If it keeps hitting it, a spec is wrong: fix the spec |
| Same mistake every run | Missing knowledge | One line in `AGENTS.md` operational notes |
| Plan drifted | Plan went stale | Delete `IMPLEMENTATION_PLAN.md`, run `./loop.sh plan` |

Show the change you'd make and why before making it. Don't edit app code to rescue the loop
unless they ask; that hides the input problem and it comes back next run.

## Rules

- Never run `loop.sh` from this chat or a background shell. It's long-running and starts its own
  `claude` processes. Hand them the command.
- Never weaken the check, the guard or the gate to get a loop moving. Report the blocker instead.
- `RALPH_YOLO=1` only in a container or VM, and only if they ask.
- Exit codes: 0 done, 1 max iterations, 2 setup error, 3 STOP, 4 stalled, 5 agent failing, 6 checks red.
