"""
plz_dedupe.py -- standalone SHA-256 collision report across payloads/ AND
. Settles "are these the same file?" with a hash instead of a guess.
Read-only, no network access -- reports only, never deletes anything.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pluz_common import repo_root, load_config, sha256_file, Log  # noqa: E402


def report_dir(dir_path: Path, label: str, log: Log):
    files = [p for p in dir_path.iterdir() if p.is_file() and p.name != ".gitkeep"] \
        if dir_path.is_dir() else []
    log.line(f"Hashing {len(files)} file(s) in {dir_path}")
    by_hash = defaultdict(list)
    for f in files:
        by_hash[sha256_file(f)].append(f.name)
    collisions = {h: names for h, names in by_hash.items() if len(names) > 1}

    if not collisions:
        log.line(f"No SHA-256 collisions found in {label}/.")
    else:
        log.line(f"{len(collisions)} collision group(s) found in {label}/ -- byte-identical files:")
        for h, names in collisions.items():
            log.line(f"  {h[:16]}...")
            for n in names:
                log.line(f"    - {n}")
            log.line("    -> SAME file under different names. Safe to delete all but one, "
                     "or keep intentionally if you want both names available.")


def main(argv=None):
    root = repo_root()
    log = Log(root, "pluz_dedupe")
    cfg = load_config(root)

    report_dir(root / cfg["settings"]["paths"]["payloads"], "payloads", log)

    log.close()
    print(f"\nLog written to: {log.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
