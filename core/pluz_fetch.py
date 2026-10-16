"""
pluz_fetch.py -- downloads new upstream release assets into payloads/.

This is the only PLUZ step that touches the network. It is ADD-ONLY: it
never deletes or overwrites a file. Default is dry-run; --apply downloads.

For every registry variant with a GitHub source_repo it:
  1. picks a release by the variant's `channel` (stable / beta / alpha);
  2. picks exactly ONE asset: `asset_pattern` (optional registry field,
     fnmatch against the asset name) or, without it, the only asset with
     the right extension (.elf/.bin);
  3. names it by the PLUZ convention {payload}[-{variant}]_v{version}.{ext};
  4. downloads it (ELF magic check, 100 MB cap) unless that file exists.

"Unknown is better than wrong": no release for the channel, zero or several
candidate assets, or a name that would not resolve back to the registry
identity means SKIP and report -- never a guess. Fix a skipped entry by
adding `asset_pattern` (asset name) or `tag_pattern` (release tag, fnmatch)
to its registry variant. Set `"fetch": false` on a
variant to exclude it.

Auth: GH_TOKEN (.env or environment) or GITHUB_TOKEN, used only for the
API calls -- never sent to download hosts.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pluz_common import (  # noqa: E402
    repo_root, load_env, load_config, parse_filename_raw, resolve_identity, Log,
    get_mode, resolved_path, load_json, sha256_file,
)

MAX_BYTES = 100 * 1024 * 1024
UA = "PLUZ5-fetch"
GH_RE = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s#?]+?)(?:\.git)?/?$")
SKIP_SUFFIXES = (".sha256", ".sha256sum", ".sig", ".asc", ".txt", ".md", ".json")


def http_json(url: str, token: str | None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def http_download(url: str, dest: Path, max_bytes: int = MAX_BYTES) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    total = 0
    with urllib.request.urlopen(req, timeout=120) as r, dest.open("wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"larger than {max_bytes // (1024 * 1024)} MB")
            f.write(chunk)


def pick_release(releases: list, channel: str, tag_pattern: str | None = None):
    live = [r for r in releases if not r.get("draft")]
    if tag_pattern:
        for r in live:
            if fnmatch.fnmatch(r.get("tag_name", ""), tag_pattern):
                return r
        return None
    ch = (channel or "stable").lower()
    if ch in ("alpha", "beta"):
        for r in live:
            label = f"{r.get('tag_name', '')} {r.get('name', '')}".lower()
            if r.get("prerelease") and ch in label:
                return r
        return None
    for r in live:
        if not r.get("prerelease"):
            return r
    return None


def clean_version(tag: str) -> str:
    v = re.sub(r"^[vV](?=\d)", "", tag or "")
    return re.sub(r"[^A-Za-z0-9.\-]", "-", v).strip("-.")


def pick_assets(assets: list, pattern: str | None, exts: set):
    names = [a for a in assets if not a["name"].lower().endswith(SKIP_SUFFIXES)]
    if pattern:
        return [a for a in names if fnmatch.fnmatch(a["name"], pattern)], False
    direct = [a for a in names if a["name"].rsplit(".", 1)[-1].lower() in exts]
    if direct:
        return direct, False
    zips = [a for a in names if a["name"].lower().endswith(".zip")]
    return zips, True


def resolve_source(label, asset, rel, version, filename, ctx, log, stats, apply):
    """SOURCE mode: record where the asset lives upstream (no file is stored here).
    The SHA-256 comes from GitHub's own asset digest; if GitHub has none we download
    the asset once into a temp file just to hash it, and never keep it."""
    prev = ctx["prev"].get(label) or {}
    sha = None
    digest = asset.get("digest") or ""
    if digest.startswith("sha256:") and len(digest) == 71:
        sha = digest[7:].lower()
    elif prev.get("url") == asset["browser_download_url"] and prev.get("size") == asset.get("size") and prev.get("sha256"):
        sha = prev["sha256"]
    elif asset.get("size", 0) > MAX_BYTES:
        stats["skipped"] += 1
        log.line(f"[SKIP] {label}: {asset['name']} exceeds 100 MB")
        return
    elif not apply:
        stats["new"] += 1
        log.line(f"[WOULD RESOLVE] {label}: {asset['name']} ({rel['tag_name']}) -- would hash by downloading once")
        return
    else:
        with tempfile.TemporaryDirectory(prefix="pluz_hash_") as td:
            tmp = Path(td) / asset["name"]
            try:
                http_download(asset["browser_download_url"], tmp)
            except (urllib.error.URLError, ValueError, OSError) as e:
                stats["errors"] += 1
                if prev:
                    ctx["resolved"][label] = prev
                log.line(f"[ERROR] {label}: could not hash asset ({e})")
                return
            if asset["name"].lower().endswith(".elf"):
                with tmp.open("rb") as fh:
                    if fh.read(4) != b"\x7fELF":
                        stats["errors"] += 1
                        log.line(f"[REJECTED] {label}: {asset['name']} is not an ELF")
                        return
            sha = sha256_file(tmp)
    rec = {"filename": filename, "version": clean_version(rel["tag_name"]), "tag": rel["tag_name"],
           "url": asset["browser_download_url"], "size": asset.get("size"), "sha256": sha}
    ctx["resolved"][label] = rec
    if prev == rec:
        stats["current"] += 1
    else:
        stats["new"] += 1
        log.line(f"[RESOLVED] {label}: {asset['name']} ({rel['tag_name']})" + ("" if not prev else f"  was {prev.get('tag')}"))


def recent_hint(releases: list) -> str:
    """One line listing the newest releases, so a skip tells you what to put in tag_pattern."""
    bits = []
    for r in [x for x in releases if not x.get("draft")][:4]:
        files = ", ".join(a["name"] for a in r.get("assets", [])[:4]) or "no files"
        bits.append(f"{r.get('tag_name')} ({'pre' if r.get('prerelease') else 'stable'}: {files})")
    return "    recent releases: " + ("; ".join(bits) if bits else "none")


def process(kind, identity, variant, reg, registry, exts, outdir, token, cache, apply, log, stats, ctx):
    label = f"{identity}/{variant}"
    if reg.get("fetch") is False:
        return
    if ctx["mode"] == "source":
        ctx["resolved"].pop(label, None)
    m = GH_RE.match(str(reg.get("source_repo") or ""))
    if not m:
        stats["skipped"] += 1
        log.line(f"[SKIP] {label}: source_repo is not a plain GitHub repo URL")
        return
    owner, repo = m.group(1), m.group(2)
    key = f"{owner}/{repo}"
    if key not in cache:
        try:
            cache[key] = http_json(f"https://api.github.com/repos/{key}/releases?per_page=30", token)
        except (urllib.error.URLError, ValueError, OSError) as e:
            cache[key] = None
            log.line(f"[WARN] {key}: could not read releases ({e})")
    releases = cache[key]
    if releases is None:
        stats["errors"] += 1
        if ctx["mode"] == "source" and label in ctx["prev"]:
            ctx["resolved"][label] = ctx["prev"][label]   # transient error: keep what we had
        return
    rel = pick_release(releases, reg.get("channel", "stable"), reg.get("tag_pattern"))
    if rel is None:
        stats["skipped"] += 1
        log.line(f"[SKIP] {label}: no '{reg.get('channel', 'stable')}' release in {key} (add tag_pattern to the registry if tags don't say alpha/beta)")
        log.line(recent_hint(releases))
        return
    cands, from_zip = pick_assets(rel.get("assets", []), reg.get("asset_pattern"), exts)
    if len(cands) != 1:
        stats["skipped"] += 1
        found = ", ".join(a["name"] for a in cands) or "none"
        log.line(f"[SKIP] {label}: {len(cands)} candidate assets ({found}) -- add asset_pattern to the registry")
        log.line(recent_hint(releases))
        return
    asset = cands[0]
    version = clean_version(rel["tag_name"])
    if not version:
        stats["skipped"] += 1
        log.line(f"[SKIP] {label}: unusable tag '{rel['tag_name']}'")
        return
    ext = asset["name"].rsplit(".", 1)[-1].lower()
    if from_zip:
        ext = sorted(exts)[0]  # provisional; real ext decided after extraction
    base = identity if variant == "default" else f"{identity}-{variant}"
    # A single-variant identity resolves from its bare name; only use that
    # form if the registry says so, otherwise keep the explicit variant.
    filename = f"{base}_v{version}.{ext}"
    if not from_zip:
        parsed = parse_filename_raw(filename)
        ok = parsed and resolve_identity(parsed["name_part"], registry) == (identity, variant)
        if not ok:
            stats["skipped"] += 1
            log.line(f"[SKIP] {label}: '{filename}' would not resolve back to this identity")
            return
    if ctx["mode"] == "source":
        if from_zip:
            stats["skipped"] += 1
            log.line(f"[SKIP] {label}: only a .zip asset ({asset['name']}) -- source mode needs a direct .elf/.bin; use mode 'hosted' or add asset_pattern")
            return
        resolve_source(label, asset, rel, version, filename, ctx, log, stats, apply)
        return
    existing = [f for f in (outdir.iterdir() if outdir.exists() else [])
                if (pf := parse_filename_raw(f.name)) and pf["name_part"] == base and pf["version"] == version]
    if existing:
        stats["current"] += 1
        return
    if asset.get("size", 0) > MAX_BYTES:
        stats["skipped"] += 1
        log.line(f"[SKIP] {label}: {asset['name']} exceeds 100 MB")
        return
    if not apply:
        stats["new"] += 1
        log.line(f"[WOULD FETCH] {label}: {asset['name']} ({rel['tag_name']}) -> {filename}")
        return

    outdir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pluz_fetch_") as td:
        tmp = Path(td) / asset["name"]
        try:
            http_download(asset["browser_download_url"], tmp)
        except (urllib.error.URLError, ValueError, OSError) as e:
            stats["errors"] += 1
            log.line(f"[ERROR] {label}: download failed ({e})")
            return
        src = tmp
        if from_zip:
            try:
                with zipfile.ZipFile(tmp) as z:
                    inner = [n for n in z.namelist()
                             if n.rsplit(".", 1)[-1].lower() in exts and not n.endswith("/")]
                    if len(inner) != 1:
                        stats["skipped"] += 1
                        log.line(f"[SKIP] {label}: zip holds {len(inner)} matching files -- add asset_pattern")
                        return
                    z.extract(inner[0], td)
                    src = Path(td) / inner[0]
            except zipfile.BadZipFile:
                stats["errors"] += 1
                log.line(f"[ERROR] {label}: bad zip")
                return
            ext = src.suffix.lstrip(".").lower()
            filename = f"{base}_v{version}.{ext}"
            parsed = parse_filename_raw(filename)
            if not (parsed and resolve_identity(parsed["name_part"], registry) == (identity, variant)):
                stats["skipped"] += 1
                log.line(f"[SKIP] {label}: '{filename}' would not resolve back to this identity")
                return
        if ext == "elf":
            with src.open("rb") as f:
                if f.read(4) != b"\x7fELF":
                    stats["errors"] += 1
                    log.line(f"[REJECTED] {label}: {asset['name']} is not an ELF")
                    return
        dest = outdir / filename
        if dest.exists():
            stats["current"] += 1
            return
        shutil.move(str(src), str(dest))
    stats["new"] += 1
    log.line(f"[FETCHED] {label}: {filename} ({rel['tag_name']})")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pluz fetch")
    ap.add_argument("--apply", action="store_true", help="Actually download (default: dry-run)")
    ap.add_argument("--only", help="Only this identity (e.g. etaHEN)")
    args = ap.parse_args(argv)

    root = repo_root()
    env = load_env(root)
    token = env.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or None
    cfg = load_config(root)
    mode = get_mode(cfg, env)
    rp = resolved_path(root)
    prev = load_json(rp) if rp.exists() else {}
    in_registry = {f"{i}/{v}" for i, e in cfg["registry"].get("payloads", {}).items() for v in e.get("variants", {})}
    ctx = {"mode": mode, "prev": prev, "resolved": {k: v for k, v in prev.items() if k in in_registry}}
    paths = cfg["settings"]["paths"]
    stats = {"new": 0, "current": 0, "skipped": 0, "errors": 0}
    cache: dict = {}

    jobs = [
        ("payload", cfg["registry"].get("payloads", {}), {"elf", "bin"}, root / paths["payloads"]),
    ]
    with Log(root, "pluz_fetch") as log:
        log.line(f"pluz fetch -- mode={mode} -- {'APPLY' if args.apply else 'DRY-RUN'}"
                 f"{'' if token else ' (no token: low GitHub API rate limit)'}")
        for kind, registry, exts, outdir in jobs:
            for identity, entry in registry.items():
                if args.only and identity != args.only:
                    continue
                for variant, reg in entry.get("variants", {}).items():
                    process(kind, identity, variant, reg, registry, exts, outdir,
                            token, cache, args.apply, log, stats, ctx)
        if mode == "source" and args.apply:
            body = json.dumps(dict(sorted(ctx["resolved"].items())), indent=2) + "\n"
            rp.parent.mkdir(parents=True, exist_ok=True)
            if not rp.exists() or rp.read_text(encoding="utf-8") != body:
                rp.write_text(body, encoding="utf-8")
                log.line(f"wrote {rp.relative_to(root)} ({len(ctx['resolved'])} entries)")
        log.line(f"Done: {stats['new']} {'fetched' if args.apply else 'to fetch'}, "
                 f"{stats['current']} already current, {stats['skipped']} skipped, {stats['errors']} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
