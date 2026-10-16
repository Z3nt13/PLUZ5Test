"""
pluz_validate.py -- checks the pldmgr manifest schema (main, hosted, split) and scans
payloads/ for filenames that will not parse.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pluz_common import repo_root, load_config, load_env, get_mode, parse_filename_raw, sha256_file, Log  # noqa: E402


HW_TARGETS = {None, "P5", "P5P", "P5U"}


def check_hw(entry, path: Path, log: Log) -> bool:
    if entry.get("hw_target") not in HW_TARGETS:
        log.line(f"[FAIL] {path.name} -- '{entry.get('filename', '?')}' has invalid hw_target '{entry.get('hw_target')}' (use P5, P5P, P5U or leave unset)")
        return False
    return True


def validate_pldmgr_manifest(path: Path, log: Log) -> bool:
    if not path.exists():
        log.line(f"[FAIL] {path.name} -- file does not exist (run 'update' first)")
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.line(f"[FAIL] {path.name} -- invalid JSON: {e}")
        return False

    ok = True
    keys = list(data.keys())
    if keys[:2] != ["name", "payloads"]:
        log.line(f"[FAIL] {path.name} -- top-level keys must be ['name','payloads'] in that order, got {keys}")
        ok = False

    for entry in data.get("payloads", []):
        fn = entry.get("filename", "?")
        if not isinstance(entry.get("url"), str):
            log.line(f"[FAIL] {path.name} -- '{fn}' has non-string url (pldmgr requires a single string)")
            ok = False
        bu = entry.get("backup_url")
        if bu is not None and not isinstance(bu, str):
            log.line(f"[FAIL] {path.name} -- '{fn}' has non-string backup_url (must be a string or null)")
            ok = False
        if not entry.get("checksum"):
            log.line(f"[FAIL] {path.name} -- '{fn}' missing checksum")
            ok = False
        ok &= check_hw(entry, path, log)
        if entry.get("category") == "Unknown":
            log.line(f"[WARN] {path.name} -- '{fn}' still has category Unknown")

    if ok:
        log.line(f"[OK  ] {path.name} -- schema valid ({len(data.get('payloads', []))} entries)")
    return ok


def scan_dir_for_issues(payloads_dir: Path, label: str, log: Log):
    files = [p for p in payloads_dir.iterdir() if p.is_file() and p.name != ".gitkeep"] \
        if payloads_dir.is_dir() else []
    unparseable = [f.name for f in files if parse_filename_raw(f.name) is None]
    if unparseable:
        log.line(f"[WARN] {len(unparseable)} filename(s) in {label}/ won't parse -- see docs/rename-map.md:")
        for n in unparseable:
            log.line(f"    {n}")
    else:
        log.line(f"[OK  ] every filename in {label}/ parses cleanly")

    by_hash = defaultdict(list)
    for f in files:
        by_hash[sha256_file(f)].append(f.name)
    collisions = {h: names for h, names in by_hash.items() if len(names) > 1}
    if collisions:
        log.line(f"[WARN] {len(collisions)} SHA-256 collision group(s) in {label}/ -- run 'dedupe' for detail")
    else:
        log.line(f"[OK  ] no SHA-256 collisions in {label}/")


def main(argv=None):
    root = repo_root()
    log = Log(root, "pluz_validate")
    cfg = load_config(root)

    log.line("PLUZ validate")
    log.line("=" * 60)

    all_ok = True
    all_ok &= validate_pldmgr_manifest(root / cfg["settings"]["manifest_files"]["main"], log)
    if get_mode(cfg, load_env(root)) == "hosted":
        all_ok &= validate_pldmgr_manifest(root / cfg["settings"]["manifest_files"]["hosted"], log)

    split_dir = root / cfg["settings"]["paths"]["split_manifests"]
    if split_dir.is_dir():
        for p in sorted(split_dir.glob("*.json")):
            all_ok &= validate_pldmgr_manifest(p, log)

    log.line("")
    log.line("Scanning payloads/ for issues...")
    scan_dir_for_issues(root / cfg["settings"]["paths"]["payloads"], "payloads", log)

    log.line("=" * 60)
    log.line("VALIDATION PASSED." if all_ok else "VALIDATION FAILED -- see FAIL lines above.")
    log.close()
    print(f"\nLog written to: {log.path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
