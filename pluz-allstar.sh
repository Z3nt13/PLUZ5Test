#!/usr/bin/env bash
# pluz-allstar.sh -- Linux/Mac companion to PLUZ-AllStar.bat.
# sync -> check -> fetch -> build -> validate -> commit/push.
# Stops at the first failing step. Repo name, token and tool paths come from .env.
# Debug mode (off by default): PLUZ_DEBUG=1 in .env, or run with debug / nodebug.
# On: diagnostic report (token hidden), git tracing, full output saved to
# logs/allstar_debug_<time>.log. Stuck sign-ins? Run ./pluz-ghclean.sh
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
. ./pluz-env.sh
envval() { sed -n "s/^$1=//p" .env 2>/dev/null | head -1 | tr -d '"' | tr -d "'"; }
PLUZ_DEBUG="${PLUZ_DEBUG:-$(envval PLUZ_DEBUG)}"; PLUZ_DEBUG="${PLUZ_DEBUG:-0}"
for a in "$@"; do
    case "$a" in debug|--debug) PLUZ_DEBUG=1;; nodebug|--nodebug) PLUZ_DEBUG=0;; esac
done
if [ "$PLUZ_DEBUG" = "1" ] && [ -z "${PLUZ_INNER:-}" ]; then
    export PLUZ_INNER=1 PLUZ_DEBUG
    exec "$PY" core/pluz_tee.py bash "$0" "$@"
fi
GH_USER="${GH_USER:-$(envval GH_USER)}"
GH_REPO="${GH_REPO:-$(envval GH_REPO)}"
GH_BRANCH="${GH_BRANCH:-$(envval GH_BRANCH)}"; GH_BRANCH="${GH_BRANCH:-main}"
PLUZ_ALLOW_PROMPT="${PLUZ_ALLOW_PROMPT:-$(envval PLUZ_ALLOW_PROMPT)}"
COMMIT_MSG="auto: PLUZ-AllStar pipeline run"
mkdir -p logs

# Never let git open a sign-in prompt or wait for typing: fail with a message.
NOHELP=()
if [ "${PLUZ_ALLOW_PROMPT:-0}" != "1" ]; then
    export GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never
    NOHELP=(-c "credential.helper=")
fi

fail() { echo; echo "[FAIL] $1"; exit 1; }
run_step() {
    local label="$1"; shift
    echo; echo "==================== ${label} ===================="
    "$@" || fail "${label} failed -- stopping. The newest file in logs/ has the details."
}

echo "Python: $PY"; echo "Git:    $GIT"
if [ "$PLUZ_DEBUG" = "1" ]; then
    echo; echo "[DEBUG] ON  -  turn off with: ./pluz-allstar.sh nodebug"
    "$PY" core/pluz_debug.py
    export GIT_TRACE=1 GIT_CURL_VERBOSE=1 GIT_TRACE_REDACT=1
fi

GHAUTH="$("$PY" core/pluz_ghauth.py)"
if [ -n "$GHAUTH" ]; then echo "Signing in to GitHub with GH_TOKEN from .env"; else echo "No GH_TOKEN could be read from .env"; fi
echo; echo "==================== [0/5] sync with GitHub ===================="
if ! "$GIT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    [ -n "$GH_USER" ] && [ -n "$GH_REPO" ] || fail "Not a git repo and GH_USER / GH_REPO are not set in .env."
    echo "This folder is not a git repo yet. Connecting it to https://github.com/$GH_USER/$GH_REPO"
    "$GIT" init -b "$GH_BRANCH"
    "$GIT" remote add origin "https://github.com/$GH_USER/$GH_REPO.git"
    "$GIT" "${NOHELP[@]}" -c "http.extraheader=$GHAUTH" fetch origin \
        || echo "[WARN] Could not read the GitHub repo yet -- will try to push anyway. Check GH_USER / GH_REPO / GH_TOKEN in .env."
    "$GIT" reset "origin/$GH_BRANCH" >/dev/null 2>&1 || true
fi
"$GIT" remote get-url origin >/dev/null 2>&1 || fail "No remote named origin."
"$GIT" "${NOHELP[@]}" -c "http.extraheader=$GHAUTH" pull --rebase --autostash origin "$GH_BRANCH" \
    || echo "[WARN] Could not pull the latest from GitHub -- continuing. If the push fails, run again with: debug"

run_step "[1/5] pluz-check"    "$PY" core/pluz_check.py
run_step "[2/5] pluz-fetch"    "$PY" core/pluz_fetch.py --apply
run_step "[3/5] pluz-update"   "$PY" core/pluz_update.py
run_step "[4/5] pluz-validate" "$PY" core/pluz_validate.py

echo; echo "==================== [5/5] git add / commit / push ===================="
[ -n "$GHAUTH" ] || [ "${PLUZ_ALLOW_PROMPT:-0}" = "1" ] \
    || fail "GH_TOKEN is missing or was not read from .env, so the push cannot sign in (try: ./pluz-allstar.sh debug)."
"$GIT" add -A || fail "git add failed."
if "$GIT" diff --cached --quiet; then
    echo "Nothing new to commit -- pushing any earlier commits that are still waiting."
else
    CFG=()
    [ -n "$("$GIT" config user.name 2>/dev/null)" ] || CFG=(-c "user.name=$GH_USER" -c "user.email=$GH_USER@users.noreply.github.com")
    "$GIT" "${CFG[@]}" commit -m "$COMMIT_MSG" || fail "git commit failed."
fi
"$GIT" "${NOHELP[@]}" -c "http.extraheader=$GHAUTH" push -u origin "$GH_BRANCH" \
    || fail "git push failed -- check GH_TOKEN in .env (this repo, Contents AND Workflows: read and write), or run ./pluz-ghclean.sh"
echo "Pushed."
[ "$PLUZ_DEBUG" = "1" ] && "$GIT" log --oneline -3
echo; echo "==================== AllStar finished ===================="
