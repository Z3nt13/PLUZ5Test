"""
pluz_common.py -- shared helpers for the PLUZ-ps5 script family.

SECURITY NOTE: this module makes no network calls and imports nothing
outside the Python standard library. Every function either reads local
data or returns a plan; callers decide whether to act on it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BINARY_EXTS = {"elf", "bin"}
EXTRACTABLE_EXTS = {"zip"}


def repo_root() -> Path:
    """When running as core/pluz_common.py directly on disk, the repo root
    is one level up. When running from inside PLUZ.pyz (a zipapp),
    __file__ is a virtual in-archive path, not a real filesystem path, so
    that lookup silently fails -- in that case fall back to the current
    working directory. This means PLUZ.pyz must be run from inside the
    repo you want it to act on (cd into it first)."""
    this_file = Path(__file__)
    if this_file.exists():
        candidate = this_file.resolve().parent.parent
        if (candidate / "configs" / "settings.json").exists():
            return candidate
    return Path.cwd()


def load_env(root: Path | None = None) -> dict:
    root = root or repo_root()
    env_path = root / ".env"
    values = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip()
    for key in ("GH_TOKEN", "GH_USER", "GH_REPO", "GH_BRANCH", "PLUZ_MODE"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def get_mode(cfg: dict, env: dict | None = None) -> str:
    """'source' (default): manifests link to the upstream release asset, nothing is
    stored in this repo.  'hosted': binaries are copied into payloads/ and served
    from this repo.  .env PLUZ_MODE (or the PLUZ_MODE environment variable) overrides settings.json."""
    mode = ((env or {}).get("PLUZ_MODE") or os.environ.get("PLUZ_MODE")
            or cfg["settings"].get("mode") or "source").strip().lower()
    return mode if mode in ("source", "hosted") else "source"


def resolved_path(root: Path) -> Path:
    return root / "manifests" / "resolved.json"


def require_env(values: dict, keys: list[str]) -> list[str]:
    return [k for k in keys if not values.get(k)]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_config(root: Path | None = None) -> dict:
    root = root or repo_root()
    cfg_dir = root / "configs"
    return {
        "settings": load_json(cfg_dir / "settings.json"),
        "categories": load_json(cfg_dir / "categories.json") if (cfg_dir / "categories.json").exists() else {},
        "registry": load_json(cfg_dir / "payload_registry.json"),
    }


NAME_VERSION_RE = re.compile(
    r"^(?P<name_part>[A-Za-z0-9][A-Za-z0-9\-]*?)"
    r"_v(?P<version>[A-Za-z0-9.\-]+?)"
    r"(?:_Expi(?P<expiry>\d{8}))?"
    r"\.(?P<ext>elf|bin)$"
)


def parse_filename_raw(filename: str) -> dict | None:
    """Pure format check -- extracts name_part/version/expiry/ext with NO
    registry knowledge. name_part may itself contain hyphens (e.g.
    'ps5-self-decrypter-full-system' or 'etaHEN-Zecoxao') -- splitting
    that into payload+variant is resolve_identity()'s job, not this
    function's, because doing it with a fixed regex broke on any
    multi-hyphen identity (this was a real, previously-shipped bug --
    'ps5-self-decrypter-full-system_v0.5.2.elf' silently failed to parse
    under the old single-hyphen-only regex, even though it was correctly
    registered). Returns None if the filename doesn't match the
    convention at all -- that's still 'needs manual review', never
    guessed."""
    m = NAME_VERSION_RE.match(filename)
    if not m:
        return None
    return m.groupdict()


def resolve_identity(name_part: str, registry: dict) -> tuple[str, str] | None:
    """Resolves a name_part (e.g. 'etaHEN-Zecoxao', 'fan-target-70c',
    'zftp') against a registry shaped {payload: {"variants": {variant: {...}}}}.

    Tries, in order:
      1. name_part IS the payload, variant is literally 'default'
      2. name_part IS the payload, and it has exactly one variant defined
         (covers e.g. zftp's only variant being 'itsPLK', not 'default')
      3. split on a hyphen: everything before is the payload,
         everything after is the variant (any hyphen, if exactly one split matches) (covers 'etaHEN-Zecoxao',
         'ShadowMountPlus-Beta', 'CheatRunner-RDX')

    Returns (payload, variant) or None. Never guesses beyond what the
    registry actually contains -- if none of these resolve, the caller
    should flag it for manual review, not fall back to anything fuzzier."""
    entry = registry.get(name_part)
    if entry is not None:
        variants = entry.get("variants", {})
        if "default" in variants:
            return name_part, "default"
        if len(variants) == 1:
            return name_part, next(iter(variants))

    # Try every hyphen as the payload/variant boundary (variants may contain
    # hyphens too, e.g. 'ftpsrv-ps5-payload' = ftpsrv + 'ps5-payload'). Both
    # sides must exist in the registry. If more than one split matches, the
    # name is ambiguous and is NOT guessed.
    matches = []
    for i, ch in enumerate(name_part):
        if ch != "-":
            continue
        payload, variant = name_part[:i], name_part[i + 1:]
        entry = registry.get(payload)
        if entry is not None and variant in entry.get("variants", {}):
            matches.append((payload, variant))
    if len(matches) == 1:
        return matches[0]

    return None


def split_name_best_effort(name_part: str) -> tuple[str, str]:
    """Registry-free best-effort split, used only when bootstrapping a
    registry from scratch (pluz_migrate.py) where there's nothing to look
    up against yet. Splits on the last hyphen if present, else the whole
    name_part is the payload with variant 'default'. This is a starting
    guess for a human to review in the generated registry entry -- not
    used anywhere that treats it as final."""
    if "-" in name_part:
        payload, variant = name_part.rsplit("-", 1)
        return payload, variant
    return name_part, "default"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def version_sort_key(version: str):
    nums = re.findall(r"\d+", version)
    numeric_part = tuple(int(n) for n in nums) if nums else (0,)
    return (numeric_part, version.lower())


def create_backup_zip(source_dir: Path, dest_zip_no_ext: Path) -> Path:
    """Zips source_dir using shutil (stdlib zipfile under the hood -- no
    external 7z/zip binary required on any platform).

    IMPORTANT: writes to a temp file OUTSIDE source_dir first, then moves
    it into place. If dest_zip_no_ext lives inside source_dir, zipping
    directly to that path would include the growing zip file in its own
    directory walk -- runaway self-inclusion that fills the disk. This
    was caught by testing, not assumed safe."""
    dest_zip = dest_zip_no_ext.with_suffix(dest_zip_no_ext.suffix + ".zip") \
        if dest_zip_no_ext.suffix != ".zip" else dest_zip_no_ext
    with tempfile.TemporaryDirectory(prefix="pluz_backup_tmp_") as tmp:
        tmp_target = Path(tmp) / dest_zip.name
        result = shutil.make_archive(str(tmp_target.with_suffix("")), "zip", root_dir=str(source_dir))
        dest_zip.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(result, dest_zip)
    return dest_zip


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def get_logger_path(root: Path, script_name: str) -> Path:
    logs_dir = root / "logs"
    logs_dir.mkdir(exist_ok=True)
    return logs_dir / f"{script_name}_{timestamp()}.log"


class Log:
    def __init__(self, root: Path, script_name: str):
        self.path = get_logger_path(root, script_name)
        self._fh = self.path.open("w", encoding="utf-8")

    def line(self, msg: str, also_print: bool = True):
        stamped = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
        self._fh.write(stamped + "\n")
        self._fh.flush()
        if also_print:
            print(stamped)

    def close(self):
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
