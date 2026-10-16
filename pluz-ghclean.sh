#!/usr/bin/env bash
# Clean slate before uploading to GitHub. Preview by default; add --apply to do it.
#   ./pluz-ghclean.sh [local|creds|repo|all] [--apply] [--yes]
cd "$(dirname "${BASH_SOURCE[0]}")"
. ./pluz-env.sh
"$PY" core/pluz_ghclean.py "$@"
