"""
pluz_ghclean.py -- get a clean slate before (re)uploading PLUZ5 to GitHub.

  pluz ghclean [local|creds|repo|all] [--apply] [--yes]

Default is a PREVIEW: it lists what it would do and changes nothing.

  local  Remove junk: old logs, __pycache__, *.tmp, extraction leftovers.
  creds  Forget saved GitHub sign-ins so git stops showing the credential
         pop-up: credential.helper entries in your global git config and in the
         portable Git's own config, ~/.git-credentials, and (Windows) the
         GitHub entries in Credential Manager. System-wide Git config outside
         the portable folder is reported but never edited.
  repo   Start the repo's history fresh: the current .git folder is MOVED to
         _backups/ (never deleted), a new repo is created, everything is
         committed once and force-pushed to origin. If the push fails the old
         .git is put back. Needs GH_USER, GH_REPO and GH_TOKEN in .env.
         Asks you to type CLEAN first (skip with --yes).
  all    local + creds + repo.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pluz_common import repo_root, load_env  # noqa: E402
from pluz_ghauth import header  # noqa: E402


def say(msg=""):
    print(msg, flush=True)


def git_exe(env):
    return os.environ.get("PLUZ_GIT") or env.get("PLUZ_GIT") or "git"


def run(git, args, cwd, extra_env=None):
    e = dict(os.environ)
    e["GIT_TERMINAL_PROMPT"] = "0"
    e["GCM_INTERACTIVE"] = "never"
    if extra_env:
        e.update(extra_env)
    return subprocess.run([git, *args], cwd=cwd, capture_output=True, text=True, env=e)


def size_mb(path: Path) -> float:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total / (1024 * 1024)


# ---------------------------------------------------------------- local junk
def clean_local(root: Path, apply: bool) -> None:
    say("== local junk ==")
    targets = []
    logs = root / "logs"
    if logs.is_dir():
        targets += [p for p in logs.iterdir() if p.is_file() and p.name != ".gitkeep"]
    for p in root.rglob("__pycache__"):
        if ".git" not in p.parts and "_backups" not in p.parts:
            targets.append(p)
    targets += list(root.glob("*.tmp")) + list(root.glob("pluz_extract_*")) + list(root.glob("pluz_backup_tmp_*"))
    targets += [p for p in (root / "payloads").glob("temp_*")] if (root / "payloads").is_dir() else []
    if not targets:
        say("  nothing to clean")
        return
    for t in targets:
        say(f"  {'removing' if apply else 'would remove'}: {t.relative_to(root)}")
        if apply:
            shutil.rmtree(t, ignore_errors=True) if t.is_dir() else t.unlink(missing_ok=True)


# ------------------------------------------------------------- saved sign-ins
def portable_git_dir(git: str) -> Path | None:
    p = Path(git)
    if p.is_absolute() or p.exists():
        try:
            return p.resolve().parents[1]
        except IndexError:
            return None
    found = shutil.which(git)
    return Path(found).resolve().parents[1] if found else None


def helper_entries(git: str, root: Path):
    """[(config file, key)] for every credential*.helper setting git can see."""
    r = run(git, ["config", "--show-origin", "--get-regexp", r"^credential\..*helper$"], root)
    rows = []
    for line in r.stdout.splitlines():
        m = re.match(r"file:(.+?)\t(\S+)\s", line + " ")
        if m:
            rows.append((Path(m.group(1)), m.group(2)))
    return rows


def clean_creds(root: Path, env: dict, apply: bool) -> None:
    say("== saved GitHub sign-ins ==")
    git = git_exe(env)
    pdir = portable_git_dir(git)
    glob_cfg = Path.home() / ".gitconfig"
    mine = lambda f: (f == glob_cfg) or (pdir is not None and str(f).lower().startswith(str(pdir).lower()))  # noqa: E731
    seen = False
    for f, key in helper_entries(git, root):
        seen = True
        if mine(f):
            say(f"  {'removing' if apply else 'would remove'}: {key} in {f}")
            if apply:
                run(git, ["config", "--file", str(f), "--unset-all", key], root)
        else:
            say(f"  left alone (system-wide, not yours to edit here): {key} in {f}")
    if not seen:
        say("  no credential.helper settings found")

    cred_file = Path.home() / ".git-credentials"
    if cred_file.exists():
        lines = cred_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        keep = [l for l in lines if "github.com" not in l]
        if len(keep) != len(lines):
            say(f"  {'cleaning' if apply else 'would clean'}: github.com lines in {cred_file}")
            if apply:
                if keep:
                    cred_file.write_text("\n".join(keep) + "\n", encoding="utf-8")
                else:
                    cred_file.unlink()

    if os.name == "nt":
        r = subprocess.run(["cmdkey", "/list"], capture_output=True, text=True)
        targets = []
        for line in r.stdout.splitlines():
            m = re.search(r"[Tt]arget:\s*(?:\w+:)?(?:target=)?(.+)$", line)
            if m and "github.com" in m.group(1).lower() and "git:" in m.group(1).lower():
                targets.append(m.group(1).strip())
        if not targets:
            say("  no GitHub entries in Windows Credential Manager")
        for t in targets:
            say(f"  {'deleting' if apply else 'would delete'} Credential Manager entry: {t}")
            if apply:
                subprocess.run(["cmdkey", f"/delete:{t}"], capture_output=True, text=True)
    else:
        say("  (Windows Credential Manager: not applicable here)")


# -------------------------------------------------------------- repo history
def reset_repo(root: Path, env: dict, apply: bool, yes: bool) -> int:
    say("== repo history ==")
    user, repo = env.get("GH_USER", ""), env.get("GH_REPO", "")
    branch = env.get("GH_BRANCH") or "main"
    url = os.environ.get("PLUZ_REMOTE_URL") or (f"https://github.com/{user}/{repo}.git" if user and repo else "")
    git = git_exe(env)
    old = root / ".git"
    say(f"  remote:  {url or '(GH_USER / GH_REPO not set in .env)'}")
    say(f"  branch:  {branch}")
    say(f"  current .git: {'%.1f MB' % size_mb(old) if old.exists() else 'none'}")
    say("  plan: move .git to _backups/, git init, commit everything once, force-push to origin")
    if not apply:
        say("  (preview only -- nothing changed)")
        return 0
    if not url:
        say("[FAIL] Set GH_USER and GH_REPO in .env first.")
        return 1
    hdr = header(env)
    if url.startswith("https://github.com/") and not hdr:
        say("[FAIL] GH_TOKEN is missing in .env -- the push could not sign in.")
        return 1
    if not yes:
        say("")
        say("  This REPLACES the repo's history on GitHub with one fresh commit.")
        if input("  Type CLEAN to continue: ").strip() != "CLEAN":
            say("  cancelled -- nothing changed")
            return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = root / "_backups" / f"git_old_{stamp}"
    moved = False
    if old.exists():
        backup.parent.mkdir(exist_ok=True)
        shutil.move(str(old), str(backup))
        moved = True
        say(f"  old .git moved to {backup.relative_to(root)}")

    def restore(why: str) -> int:
        say(f"[FAIL] {why}")
        shutil.rmtree(root / ".git", ignore_errors=True)
        if moved:
            shutil.move(str(backup), str(old))
            say("  old .git put back -- nothing was lost")
        return 1

    steps = [
        ["init", "-q", "-b", branch],
        ["config", "user.name", user or "pluz"],
        ["config", "user.email", f"{user or 'pluz'}@users.noreply.github.com"],
        ["remote", "add", "origin", url],
        ["add", "-A"],
        ["commit", "-q", "-m", "PLUZ5 clean upload"],
    ]
    for s in steps:
        r = run(git, s, root)
        if r.returncode != 0:
            return restore(f"git {' '.join(s[:2])} failed: {(r.stderr or r.stdout).strip()[:300]}")
    push = ["-c", "credential.helper="]
    if hdr:
        push += ["-c", f"http.extraheader={hdr}"]
    push += ["push", "--force", "-u", "origin", branch]
    say("  pushing (this can take a minute)...")
    r = run(git, push, root)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()
        hint = ""
        if "workflow" in msg.lower():
            hint = " -- the token needs the 'Workflows: Read and write' permission (classic token: 'workflow' scope)"
        return restore(f"push failed: {msg[-400:]}{hint}")
    say("  done: GitHub now has one clean commit")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pluz ghclean", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="?", default="all", choices=["local", "creds", "repo", "all"])
    ap.add_argument("--apply", action="store_true", help="really do it (default: preview)")
    ap.add_argument("--yes", action="store_true", help="skip the type-CLEAN confirmation for 'repo'")
    a = ap.parse_args(argv)

    root = repo_root()
    env = load_env(root)
    say(f"PLUZ GHclean -- {'APPLY' if a.apply else 'PREVIEW (nothing will change)'}")
    rc = 0
    if a.what in ("local", "all"):
        clean_local(root, a.apply)
    if a.what in ("creds", "all"):
        clean_creds(root, env, a.apply)
    if a.what in ("repo", "all"):
        rc = reset_repo(root, env, a.apply, a.yes)
    if not a.apply:
        say("\nTo do it for real, run again with --apply (or pick the matching menu number).")
    return rc


if __name__ == "__main__":
    sys.exit(main())
