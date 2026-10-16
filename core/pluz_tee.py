"""
pluz_tee.py -- runs a command, shows its output live AND saves it to
logs/allstar_debug_<timestamp>.log. Used by PLUZ-AllStar in debug mode.
Secrets (GH_TOKEN and the sign-in header built from it) are masked in both.

usage: pluz_tee.py <command> [args...]      exit code = the command's exit code
"""
import base64
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pluz_common import repo_root, load_env  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("usage: pluz_tee.py <command> [args...]")
        return 2
    root = repo_root()
    env = load_env(root)
    secrets = []
    token, user = env.get("GH_TOKEN", ""), env.get("GH_USER", "")
    if token:
        secrets.append(token)
        if user:
            secrets.append(base64.b64encode(f"{user}:{token}".encode()).decode())
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    log_path = logs / f"allstar_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    print(f"[DEBUG] saving everything to {log_path}", flush=True)

    p = subprocess.Popen(sys.argv[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    with log_path.open("wb") as f:
        for raw in iter(lambda: p.stdout.readline(), b""):
            line = raw
            for s in secrets:
                line = line.replace(s.encode(), b"***")
            f.write(line)
            f.flush()
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
    p.wait()
    print(f"[DEBUG] log saved: {log_path}", flush=True)
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
