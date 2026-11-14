#!/bin/bash
# Run every check. Needs: git, python3, shellcheck.
cd "$(dirname "$0")/.." || exit 1
rc=0
echo "== validate";   python3 tests/validate.py || rc=1
echo "== shellcheck"; shellcheck skills/ralph-loop/assets/loop.sh tests/stub-claude tests/test_loop.sh tests/run_all.sh tests/e2e_real.sh && echo "clean" || rc=1
echo "== py compile"; python3 -m py_compile skills/ralph-loop/scripts/ralph.py skills/ralph-loop/assets/.ralph/hooks/*.py && echo "ok" || rc=1
echo "== hooks";      python3 tests/test_hooks.py || rc=1
echo "== install";    python3 tests/test_install.py || rc=1
echo "== loop";       bash tests/test_loop.sh || rc=1
[ $rc -eq 0 ] && echo "ALL GREEN" || echo "FAILURES"
exit $rc
