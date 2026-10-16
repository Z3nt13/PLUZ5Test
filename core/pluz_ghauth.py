"""
pluz_ghauth.py -- builds the HTTP header git needs to sign in to GitHub with
GH_USER + GH_TOKEN from .env (or the environment).

  python pluz_ghauth.py            -> prints the header, or nothing without a token
  python pluz_ghauth.py <file>     -> writes `set "GHAUTH=<header>"` to <file> (for .bat)

The AllStar scripts pass it as `git -c "http.extraheader=<header>" push`, so
the token is never written into the remote URL or git's config on disk.
"""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pluz_common import load_env  # noqa: E402


def header(env=None):
    env = env if env is not None else load_env()
    user, token = env.get("GH_USER", ""), env.get("GH_TOKEN", "")
    if not (user and token):
        return ""
    pair = base64.b64encode(f"{user}:{token}".encode()).decode()
    return f"AUTHORIZATION: basic {pair}"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    h = header()
    if argv:
        if h:
            Path(argv[0]).write_text(f'set "GHAUTH={h}"\n', encoding="ascii")
    elif h:
        print(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
