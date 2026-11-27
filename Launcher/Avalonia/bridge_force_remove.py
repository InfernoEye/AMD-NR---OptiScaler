"""Preserve changed community-bridge managed files before reviewed upstream force removal.

No guessed file names, no Steam edits, and no symlink traversal. The upstream
manager retains responsibility for restoring game and Proton-prefix backups.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import uuid

MAX_RECORD_BYTES = 4 * 1024 * 1024


def _safe_member(folder: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or "\\x00" in name:
        raise ValueError("Invalid bridge record path")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or any(
            ":" in part for part in path.parts):
        raise ValueError("Unsafe bridge record path")
    target = folder
    for part in path.parts:
        target = target / part
        if target.is_symlink():
            raise ValueError("Refusing symlinked bridge path")
    return target


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preserve_changed_bridge_files(folder: Path, record: dict) -> dict:
    """Archive modified owned files before upstream uninstall --force.

    Missing files don't need copies. The snapshot is external to the game's
    install folder, and is retained even when the upstream manager fails.
    """
    if not isinstance(record, dict) or record.get("version") != 1 or not isinstance(
            record.get("launcher"), dict):
        raise ValueError("Not a reviewed community bridge record")
    entries = record.get("files")
    installed = record.get("installed")
    if not isinstance(entries, list) or not isinstance(installed, list) or len(entries) > 20000:
        raise ValueError("Invalid community bridge file manifest")
    names = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid community bridge entry")
        name, digest = entry.get("path"), entry.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or not all(
                c in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid community bridge checksum")
        _safe_member(folder, name)
        if name in names:
            raise ValueError("Duplicate community bridge path")
        names[name] = digest
    if len(installed) != len(set(installed)) or not all(
            isinstance(name, str) and name in names for name in installed):
        raise ValueError("Invalid installed bridge file list")
    changed = []
    missing = []
    for name in installed:
        path = _safe_member(folder, name)
        if not path.exists():
            missing.append(name)
        elif not path.is_file():
            raise ValueError("Unexpected bridge-owned directory: " + name)
        elif _sha(path) != names[name]:
            changed.append(name)
    if not changed:
        return {"snapshot": None, "preserved": [], "missing": missing}
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    key = hashlib.sha256(str(folder.resolve()).encode()).hexdigest()
    archive_root = base / "amdnr" / "bridge-force-recovery" / key
    for ancestor in (archive_root, archive_root.parent, archive_root.parent.parent):
        if ancestor.is_symlink():
            raise ValueError("Unsafe recovery path")
    archive_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    snapshot = archive_root / uuid.uuid4().hex
    snapshot.mkdir(mode=0o700)
    preserved = []
    for name in changed:
        source = _safe_member(folder, name)
        destination = _safe_member(snapshot, name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        before = _sha(source)
        with source.open("rb") as input_file, destination.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file)
            output_file.flush()
            os.fsync(output_file.fileno())
        if _sha(source) != before or _sha(destination) != before:
            raise ValueError("Bridge file changed while being preserved: " + name)
        preserved.append({"path": name, "sha256": before})
    receipt = {"version": 1, "game_folder": str(folder), "files": preserved,
               "missing": missing, "reason": "force bridge removal"}
    with (snapshot / "manifest.json").open("x", encoding="utf-8") as file:
        json.dump(receipt, file, indent=2)
        file.flush()
        os.fsync(file.fileno())
    return {"snapshot": str(snapshot), "preserved": [x["path"] for x in preserved],
            "missing": missing}
