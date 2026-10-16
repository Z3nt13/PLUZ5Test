"""
pluz_update.py -- regenerates the pldmgr-compatible ELF/BIN manifests from
whatever is currently in payloads/, re-verifies every on-disk SHA-256, and
(with --push) commits + pushes using your LOCAL git auth if anything changed.


No network access happens in this script itself -- `git push` is a local
git subprocess call that uses whatever credential helper/SSH key you
already have configured; no token is ever read from .env and embedded
into a URL here.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pluz_common import (  # noqa: E402
    repo_root, load_env, load_config, parse_filename_raw, resolve_identity, sha256_file,
    version_sort_key, Log, get_mode, resolved_path, load_json,
)


def build_url(gh_user: str, gh_repo: str, gh_branch: str, subdir: str, filename: str) -> str:
    return f"https://raw.githubusercontent.com/{gh_user}/{gh_repo}/{gh_branch}/{subdir}/{filename}"


def make_manifest_entry(payload_name: str, variant: str, artifact: dict, reg: dict, env: dict, subdir: str) -> dict:
    url = artifact.get("url") or build_url(env["GH_USER"], env["GH_REPO"], env["GH_BRANCH"], subdir, artifact["filename"])
    display_name = reg.get("display_name", payload_name if variant == "default" else f"{payload_name} ({variant})")

    desc_bits = []
    fw_min, fw_max = reg.get("fw_min"), reg.get("fw_max")
    if fw_min or fw_max:
        desc_bits.append(f"FW {fw_min or '?'}-{fw_max or '?'}")
    if reg.get("port"):
        desc_bits.append(f"port {reg['port']}")
    if artifact["expiry"]:
        e = artifact["expiry"]
        desc_bits.append(f"expires {e[:4]}-{e[4:6]}-{e[6:]}")
    if reg.get("note") and not desc_bits:
        desc_bits.append(reg["note"])
    description = " -- ".join(desc_bits) if desc_bits else ""

    return {
        "name": display_name,
        "filename": artifact["filename"],
        "url": url,
        "backup_url": reg.get("backup_url"),
        "description": description,
        "version": artifact["version"],
        "fw_min": reg.get("fw_min"),
        "fw_max": reg.get("fw_max"),
        "platform": reg.get("platform", "ps5"),
        "hw_target": reg.get("hw_target"),
        "category": reg.get("category", "Unknown"),
        "author": reg.get("author"),
        "author_url": reg.get("author_url"),
        "checksum": artifact["sha256"],
    }


def run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pluz update")
    ap.add_argument("--push", action="store_true", help="git add/commit/push manifests if anything changed")
    args = ap.parse_args(argv)

    root = repo_root()
    log = Log(root, "pluz_update")
    cfg = load_config(root)
    env = load_env(root)

    missing_env = [k for k in ("GH_USER", "GH_REPO", "GH_BRANCH") if not env.get(k)]
    if missing_env:
        log.line(f"[ERROR] missing required .env values: {', '.join(missing_env)}")
        log.line("Run 'check' and fill in .env before generating manifests.")
        return 1

    payloads_dir = root / cfg["settings"]["paths"]["payloads"]
    registry = cfg["registry"]["payloads"]
    retention = cfg["settings"]["retention"]
    main_keep, hosted_keep = retention["main_keep"], retention["hosted_keep"]

    mode = get_mode(cfg, env)
    groups = defaultdict(list)
    unresolved = []
    if mode == "source":
        rp = resolved_path(root)
        resolved = load_json(rp) if rp.exists() else {}
        log.line(f"mode=source: building from {rp.name} ({len(resolved)} resolved upstream assets)")
        for key in sorted(resolved):
            ident, _, variant = key.partition("/")
            reg_entry = registry.get(ident, {}).get("variants", {}).get(variant)
            if reg_entry is None:
                continue                                  # removed from the registry
            rec = resolved[key]
            groups[(ident, variant)].append({
                "filename": rec["filename"], "version": rec["version"], "expiry": None,
                "sha256": rec["sha256"], "url": rec["url"], "registry": reg_entry})
        files = []
    else:
        files = [p for p in payloads_dir.iterdir()
                 if p.is_file() and p.suffix.lstrip(".").lower() in {"elf", "bin"}] \
            if payloads_dir.is_dir() else []
        log.line(f"mode=hosted: scanning {len(files)} files in {payloads_dir}")

    for f in sorted(files, key=lambda p: p.name):
        parsed = parse_filename_raw(f.name)
        if parsed is None:
            unresolved.append((f.name, "does not match naming convention"))
            continue
        resolved = resolve_identity(parsed["name_part"], registry)
        if resolved is None:
            unresolved.append((f.name, f"'{parsed['name_part']}' does not resolve to any "
                               f"registered payload/variant in payload_registry.json"))
            continue
        payload_name, variant = resolved
        reg_entry = registry[payload_name]["variants"][variant]
        groups[(payload_name, variant)].append({
            "filename": f.name,
            "version": parsed["version"],
            "expiry": parsed["expiry"],
            "sha256": sha256_file(f),
            "registry": reg_entry,
        })

    if unresolved:
        log.line("")
        log.line(f"{len(unresolved)} file(s) excluded from manifests -- need manual attention:")
        for name, reason in unresolved:
            log.line(f"  [SKIP] {name} -- {reason}")

    main_entries, hosted_entries = [], []
    split_buckets = defaultdict(list)
    retention_labels = ["current", "previous", "previous-2", "previous-3", "previous-4"]

    subdir = cfg["settings"]["paths"]["payloads"]

    for (payload_name, variant), artifacts in groups.items():
        artifacts.sort(key=lambda a: version_sort_key(a["version"]), reverse=True)
        reg_entry = artifacts[0]["registry"]
        is_protected = reg_entry.get("protected_fallback", False)
        effective_keep = max(hosted_keep, len(artifacts)) if is_protected else hosted_keep

        for i, artifact in enumerate(artifacts[:effective_keep]):
            tag = retention_labels[i] if i < len(retention_labels) else f"previous-{i}"
            entry = make_manifest_entry(payload_name, variant, artifact, reg_entry, env, subdir)
            entry["retention"] = tag
            if i == 0:
                # Main manifest gets latest only, no retention tag
                main_entry = {k: v for k, v in entry.items() if k != "retention"}
                main_entries.append(main_entry)
                split_buckets[reg_entry.get("category", "Unknown")].append(main_entry)
            hosted_entries.append(entry)

    # pldmgr shape: {"name": ..., "payloads": [...]} -- 'name' first, no per-run
    # timestamp (a changing timestamp would make every run produce a git diff).
    main_manifest = {"name": "Z3nT1's PLUZ5 -- Source", "payloads": main_entries}
    hosted_manifest = {"name": "Z3nT1's PLUZ5 -- Hosted", "payloads": hosted_entries}

    (root / cfg["settings"]["manifest_files"]["main"]).parent.mkdir(parents=True, exist_ok=True)
    (root / cfg["settings"]["manifest_files"]["main"]).write_text(json.dumps(main_manifest, indent=2), encoding="utf-8")
    hosted_path = root / cfg["settings"]["manifest_files"]["hosted"]
    if mode == "hosted":
        hosted_path.write_text(json.dumps(hosted_manifest, indent=2), encoding="utf-8")
    elif hosted_path.exists():
        hosted_path.unlink()                              # source mode has no hosted builds

    split_dir = root / cfg["settings"]["paths"]["split_manifests"]
    split_dir.mkdir(parents=True, exist_ok=True)
    for old in split_dir.glob("ps5_*.json"):             # drop categories that are now empty
        old.unlink()
    for category, entries in split_buckets.items():
        safe_name = category.lower().replace(" ", "_").replace("&", "and")
        out = {"name": f"Z3nT1's PLUZ5 -- {category}", "payloads": entries}
        (split_dir / f"ps5_{safe_name}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    log.line(f"Category splits written: {len(split_buckets)}")
    log.line(f"Wrote {len(main_entries)} entries to {cfg['settings']['manifest_files']['main']}")
    if mode == "hosted":
        log.line(f"Wrote {len(hosted_entries)} entries to {cfg['settings']['manifest_files']['hosted']}")

    if unresolved:
        log.line(f"[WARN] {len(unresolved)} files skipped -- see log for details")

    if args.push:
        rc, out = run_git(["add", cfg["settings"]["manifest_files"]["main"],
                           cfg["settings"]["manifest_files"]["hosted"]], root)
        log.line(f"git add: {out}")
        if rc == 0:
            rc, out = run_git(["commit", "-m", "chore(manifests): regenerate payload manifests [pluz update]"], root)
            log.line(f"git commit: {out}")
            if rc == 0:
                rc, out = run_git(["push"], root)
                log.line(f"git push: {out}")

    log.close()
    return 0 if not unresolved else 1


if __name__ == "__main__":
    sys.exit(main())
