"""
pluz_debug.py -- prints (and saves to logs/allstar_debug_<time>.txt) everything
needed to diagnose a failing AllStar run: tool paths and versions, which .env
keys are set (values hidden, token shown only as a length), the git remote,
every credential/http/user git setting with the file it comes from, and the
repo's state. Run by PLUZ-AllStar when debug is on (PLUZ_DEBUG=1 or `debug`).
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pluz_common import repo_root, load_env  # noqa: E402

KEYS = ("GH_USER", "GH_REPO", "GH_BRANCH", "GH_TOKEN", "PLUZ_PY_DIR", "PLUZ_PYTHON",
        "PLUZ_GIT_DIR", "PLUZ_GIT", "PLUZ_DEBUG", "PLUZ_ALLOW_PROMPT")


def git(root, git_exe, *args):
    try:
        r = subprocess.run([git_exe, *args], cwd=root, capture_output=True, text=True, timeout=60)
        return (r.stdout + r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return f"(could not run: {e})"


def main():
    root = repo_root()
    env = load_env(root)
    git_exe = os.environ.get("PLUZ_GIT") or env.get("PLUZ_GIT") or "git"
    out = []
    add = out.append
    add(f"PLUZ debug report -- {datetime.now().isoformat(timespec='seconds')}")
    add(f"folder:  {root}")
    add(f"python:  {sys.executable}  ({sys.version.split()[0]})")
    add(f"git:     {git_exe}  ->  {git(root, git_exe, '--version')}")
    add("")
    add(".env / environment (token hidden):")
    for k in KEYS:
        v = env.get(k) or os.environ.get(k)
        if not v:
            add(f"  {k:18} (not set)")
        elif k == "GH_TOKEN":
            add(f"  {k:18} set, {len(v)} characters")
        else:
            add(f"  {k:18} {v}")
    add(f"  .env file present: {(root / '.env').exists()}")
    add("")
    add("git repo:")
    add(f"  inside work tree: {git(root, git_exe, 'rev-parse', '--is-inside-work-tree')}")
    add(f"  remote:           {git(root, git_exe, 'remote', '-v').replace(chr(10), ' | ')}")
    add(f"  branch:           {git(root, git_exe, 'branch', '--show-current')}")
    add(f"  ahead/behind:     {git(root, git_exe, 'rev-list', '--left-right', '--count', 'HEAD...@{u}')}")
    add(f"  changed files:    {len([l for l in git(root, git_exe, 'status', '--short').splitlines() if l.strip()])}")
    add("  last commits:")
    for line in git(root, git_exe, "log", "--oneline", "-n", "3").splitlines():
        add(f"    {line}")
    add("")
    add("git settings that affect sign-in (file : key = value):")
    cfg = git(root, git_exe, "config", "--show-origin", "--get-regexp", r"^(credential\.|http\.|user\.|core\.askpass|url\.)")
    for line in (cfg.splitlines() or ["(none)"]):
        add(f"  {line}")
    add("")
    flags = ", ".join(f"{k}={os.environ[k]}" for k in ("GIT_TERMINAL_PROMPT", "GCM_INTERACTIVE", "GIT_ASKPASS", "SSH_ASKPASS") if os.environ.get(k))
    add("sign-in environment: " + (flags or "(nothing set)"))
    text = "\n".join(out)
    print(text)
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    f = logs / f"allstar_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    f.write_text(text + "\n", encoding="utf-8")
    print(f"\nSaved: {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
