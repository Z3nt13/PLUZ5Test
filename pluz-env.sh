# pluz-env.sh -- sourced by every PLUZ launcher. Reads .env (never `source`s it)
# and sets PY and GIT. Only .env is ever edited; nothing personal lives here.
#   PLUZ_PYTHON / PLUZ_GIT  full paths (optional); unset = python3 / git on PATH
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$_here/.env" ]; then
    while IFS='=' read -r _k _v; do
        case "$_k" in ''|\#*) continue;; esac
        _v="${_v%\"}"; _v="${_v#\"}"; _v="${_v%\'}"; _v="${_v#\'}"
        case "$_k" in PLUZ_PYTHON|PLUZ_GIT) export "$_k=$_v";; esac
    done < "$_here/.env"
fi
PY="${PLUZ_PYTHON:-python3}"
GIT="${PLUZ_GIT:-git}"
export PLUZ_GIT="$GIT" PLUZ_PYTHON="$PY"
