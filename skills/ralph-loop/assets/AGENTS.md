<!-- ralph:start -->
## Ralph loop

Loaded by every Ralph iteration. Keep this section short and operational: how to build,
run and check the project. Not a changelog. Not a plan.

### Build & run

```bash
# e.g. npm install && npm run build
```

### Checks

The command that proves the work is `RALPH_CHECK` in `.ralph/config`. Run it before every
commit. The loop and its stop gate run it too, so a red check is never "done".

### Codebase patterns

- e.g. Shared utilities live in `src/lib/`. Reuse them; don't duplicate.

### Operational notes

<!-- The agent adds one-line learnings here, e.g. "Tests need DB_URL=sqlite::memory:" -->
<!-- ralph:end -->
