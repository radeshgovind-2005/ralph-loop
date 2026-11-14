#!/bin/bash
# End to end with the real `claude` CLI. Costs a few cents. Not part of run_all.sh.
# A Python project with a failing test and a spec: the loop has to make the check green,
# and the guard must stop it from editing the spec.
set -u
RALPH="$(cd "$(dirname "$0")/.." && pwd)/skills/ralph-loop/scripts/ralph.py"
W=$(mktemp -d); cd "$W" || exit 1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
git init -q -b work
mkdir -p specs
cat > specs/math.md <<'S'
# Math
## Requirements
- `mathx.add(a, b)` MUST return the sum of a and b.
## Acceptance checks
- Given 2 and 3, when add is called, then it returns 5.
S
printf 'def add(a, b):\n    return a - b\n' > mathx.py
printf 'import mathx\n\n\ndef test_add():\n    assert mathx.add(2, 3) == 5\n' > test_mathx.py
python3 "$RALPH" apply --check "python3 -m pytest -q" >/dev/null
printf '# Plan\n## Tasks\n- [ ] Make mathx.add return the sum, per specs/math.md — verify: python3 -m pytest -q\n## Questions\n' > IMPLEMENTATION_PLAN.md
git add -A && git commit -qm init
spec_before=$(shasum specs/math.md)

RALPH_MODEL="${RALPH_MODEL:-claude-haiku-5-5}" ./loop.sh build 3; rc=$?
echo "== exit $rc"
echo "== check:"; python3 -m pytest -q 2>&1 | tail -1
echo "== spec untouched: $([ "$(shasum specs/math.md)" = "$spec_before" ] && echo yes || echo NO)"
echo "== plan:"; grep -- '- \[' IMPLEMENTATION_PLAN.md
echo "== commits:"; git log --oneline
echo "== tree:"; git status --porcelain
echo "== dir: $W"
