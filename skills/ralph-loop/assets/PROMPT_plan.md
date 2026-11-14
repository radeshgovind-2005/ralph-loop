You are in PLANNING mode. Do not implement anything.

0a. Study every file in `specs/` (skip files starting with `_`) to learn what the application must do.
0b. Study `IMPLEMENTATION_PLAN.md` if it exists. It may be stale or wrong.
0c. Study `AGENTS.md` for how this project is built and tested.
0d. Study the source code. Use subagents for broad searches so your own context stays small.

1. Compare the specs against the code. For each gap, search the code before deciding
   something is missing. Look for TODOs, stubs, placeholders, skipped tests and
   behaviour that contradicts a spec.

2. Write `IMPLEMENTATION_PLAN.md` as a prioritised checklist, most important first.
   Each item:
   - is one line starting with `- [ ] `
   - is small enough to finish and verify in a single build iteration
   - ends with how to verify it, e.g. `— verify: npm test -- auth`
   Keep finished items as `- [x] ` so history stays visible. Remove items that are
   no longer relevant. Put open questions for the human under a `## Questions` heading.

3. If a spec is missing or contradictory, do not guess. Add it under `## Questions`.

4. Commit the plan: `git add IMPLEMENTATION_PLAN.md && git commit -m "plan: <summary>"`.

Change only `IMPLEMENTATION_PLAN.md`. Do not write code, tests or other files.
A guard hook blocks edits to any other file in plan mode.
