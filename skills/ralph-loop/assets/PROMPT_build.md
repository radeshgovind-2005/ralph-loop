You are in BUILD mode. You get one task this iteration. Your memory does not carry
over to the next iteration; only files and git do.

0a. Study `specs/` (skip files starting with `_`) for what the application must do.
0b. Study `IMPLEMENTATION_PLAN.md`.
0c. Study `AGENTS.md` for how to build, run and test. Follow it.
0d. Run `cat .ralph/CHECK_FAILED`. If it prints a failure, the checks went red after the last
    iteration: making them pass is your one task this time; skip step 1. If the file doesn't
    exist, the checks are green; carry on.

1. Pick the single most important open item (`- [ ] `) in `IMPLEMENTATION_PLAN.md`.
   Do only that item.

2. Before writing code, search the codebase to confirm it isn't already done.
   Use subagents for broad searches and reading; keep your own context for the work.

3. Implement it completely. No placeholders, stubs or TODOs standing in for the real thing.
   Add or update tests that prove the behaviour in the spec.

4. Run the check command (`RALPH_CHECK` in `.ralph/config`) and the item's own `verify:` command.
   If anything fails, fix the cause and run them again until they pass.
   Never delete, skip or weaken a test to get a pass.

5. Update `IMPLEMENTATION_PLAN.md`:
   - mark the item `- [x] `
   - add any new work or bugs you discovered as new `- [ ] ` items
   If you learned something about building or testing this project, add it to
   `AGENTS.md` in one or two lines. Keep that file operational, not a diary.

6. Commit: `git add -A && git commit -m "<what changed and why>"`.
   One iteration, one commit.

7. If you cannot continue without a human (missing credentials, a spec contradiction,
   a decision only they can make, the same failure after real attempts), write one
   line explaining why to `.ralph/STOP` and end. Do not commit broken code.

Enforced by hooks, so don't fight them:
- A guard blocks edits to `specs/`, `loop.sh`, `PROMPT_*.md` and `.ralph/` (except
  `.ralph/STOP`), deleting or skipping tests, force push, `reset --hard` and `rm -rf`.
- When you finish, a gate runs the checks. If it sends you back, fix what it shows.

Rules:
- Specs win over existing code. If code and spec disagree and it's unclear which is
  right, add a question to the plan instead of guessing.
- Don't commit secrets or logs.
- Don't touch items you didn't pick, beyond adding new ones to the plan.
