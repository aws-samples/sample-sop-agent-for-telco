#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Pre-commit guard: lockfiles must be regenerated when pyproject.toml deps change
# ---------------------------------------------------------------------------
# Why: the Brazil/Peru build runs hatch-pip-compile OFFLINE (PIP_COMPILE_DISABLE).
# If the committed requirements*.txt lockfiles drift from pyproject.toml's
# declared dependencies, the build cannot recompile and aborts the dry-run with:
#   HatchPipCompileError: hatch-pip-compile is disabled but attempted to run a
#   lockfile update.
#
# This guard catches that mistake locally (pure git, no hatch needed, instant):
# if pyproject.toml's dependency lines changed but no requirements*.txt is in the
# same commit, fail with the one-line fix.
#
# Bypass (rarely needed): SKIP=lockfile-sync git commit ...
# ---------------------------------------------------------------------------
set -euo pipefail

staged="$(git diff --cached --name-only)"

# Only relevant when pyproject.toml itself is part of this commit.
echo "${staged}" | grep -qx 'pyproject.toml' || exit 0

# Did any DEPENDENCY-bearing line change? (version specifiers or the deps arrays)
# Strip diff headers, look at added/removed content lines only.
dep_change="$(
  git diff --cached -U0 -- pyproject.toml \
    | grep -E '^[+-]' \
    | grep -vE '^(\+\+\+|---)' \
    | grep -E '(^[+-]dependencies|>=|==|~=|!=|<[0-9]|"[a-zA-Z0-9_.-]+")' || true
)"

[ -z "${dep_change}" ] && exit 0  # pyproject changed, but not its dependencies

# Dependencies changed — a regenerated lockfile must ride along.
if echo "${staged}" | grep -qE '^requirements(/.*|\.txt)$'; then
  echo "✓ lockfile-sync: pyproject deps changed and requirements*.txt staged together"
  exit 0
fi

cat >&2 <<'EOF'
❌ lockfile-sync: pyproject.toml dependencies changed but no requirements*.txt
   was regenerated in this commit.

   The OFFLINE CI build (PIP_COMPILE_DISABLE) cannot recompile the lock and will
   FAIL the dry-run build.

   Fix:
       hatch run update            # regenerates all requirements*.txt locks
       git add requirements*.txt requirements/
       git commit --amend --no-edit   # (or include in this commit)

   Override (only if you know the lock is already current):
       SKIP=lockfile-sync git commit ...
EOF
exit 1
