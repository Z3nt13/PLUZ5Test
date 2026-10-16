"""
plz_cleanup.py -- backs up the repo (always, not optional on --apply), then
wipes payloads/ and manifests/ for a genuine from-scratch rebuild.
Also sweeps leftover .tmp files and orphaned extraction directories.

Dry-run by default.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pluz_common import repo_root, load_config, create_backup_zip, timestamp, Log  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="plz cleanup")
    ap.add_argument("--apply", action="store_true", help="Actually back up and wipe (default: dry-run)")
    args = ap.parse_args(argv)

    root = repo_root()
    log = Log(root, "pluz_cleanup")
    cfg = load_config(root)

    mode = "APPLY" if args.apply else "DRY-RUN"
    log.line(f"PLUZ cleanup -- mode: {mode}")
    log.line("=" * 60)

    backups_dir = root / cfg["settings"]["paths"].get("backups", "_backups")
    backup_name = f"PLUZ-ps5_BACKUP_{timestamp()}"
    backup_target = backups_dir / backup_name

    log.line(f"[PLAN] backup entire repo -> {backups_dir / (backup_name + '.zip')}")
    if args.apply:
        backups_dir.mkdir(parents=True, exist_ok=True)
        written = create_backup_zip(root, backup_target)
        log.line(f"[DONE] backup written: {written}")

    payloads_dir = root / cfg["settings"]["paths"]["payloads"]
    manifests_dir = root / cfg["settings"]["paths"]["manifests"]
    split_dir = root / cfg["settings"]["paths"]["split_manifests"]

    payload_files = [p for p in payloads_dir.glob("*") if p.is_file() and p.name != ".gitkeep"] \
        if payloads_dir.is_dir() else []
    manifest_files = list(manifests_dir.glob("*.json")) if manifests_dir.is_dir() else []
    split_files = list(split_dir.glob("*.json")) if split_dir.is_dir() else []

    log.line(f"[PLAN] delete {len(payload_files)} file(s) from payloads/")
    log.line(f"[PLAN] delete {len(manifest_files)} manifest(s) from manifests/")
    log.line(f"[PLAN] delete {len(split_files)} category split(s) from manifests/split/")

    leftovers = list(root.glob("*.tmp")) + list(root.glob("pluz_extract_*")) + list(root.glob("pluz_backup_tmp_*"))
    log.line(f"[PLAN] sweep {len(leftovers)} leftover tmp/extraction item(s)")

    if args.apply:
        for f in payload_files + manifest_files + split_files:
            f.unlink()
        for item in leftovers:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        log.line("")
        log.line("Wipe complete. payloads/ and manifests/ are clean. "
                 "configs/ registries were NOT touched.")
    else:
        log.line("")
        log.line("This was a DRY RUN. Nothing was backed up or deleted. Re-run with --apply to execute.")

    log.close()
    print(f"\nLog written to: {log.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
