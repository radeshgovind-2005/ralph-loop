# ralph-loop plugin

One skill, `skills/ralph-loop`. Everything it installs into a project lives in
`skills/ralph-loop/assets/`; `scripts/ralph.py` installs, checks and reports on it.

## Checks

Run before every commit. All must pass.

```bash
bash tests/run_all.sh
```

It runs: manifest and frontmatter validation, shellcheck on `loop.sh`, the loop tests with a
fake `claude`, the hook tests, and the installer tests. It needs `python3`, `git`, `shellcheck`.

`tests/e2e_real.sh` runs the loop with the real `claude` CLI (costs a few cents, a few minutes).
Run it after changing `loop.sh`, the hooks or the prompts. It's not part of `run_all.sh`.

## Rules

- `loop.sh` must run on macOS `/bin/bash` 3.2: no `mapfile`, no `${x,,}`, no associative arrays,
  and guard empty arrays under `set -u`.
- Hooks are stdlib-only Python 3 and fail open on bad input; the loop's own check is the real gate.
- Never weaken a test to get a pass.

<!-- vc:start -->
## Version control rules

- Never commit on `main`. Work on a `type/short-slug` branch.
- Commit titles only: `type(scope): description`. 72 characters or fewer, imperative, no period.
- Never skip a check. No `--no-verify`, `HUSKY=0`, `LEFTHOOK=0`. Do not edit `.githooks/`, CI files,
  or `core.hooksPath` to make a change pass. Fix the cause, or stop and report the blocker.
- PRs are squash-merged. The PR title becomes the commit on `main`. A merge to `main` publishes a release.
- Say "version control" to start the `vc` skill. It shows a plan and waits for your answer.
<!-- vc:end -->
