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


def quarantine_recorded_bridge(folder: Path, record: dict) -> dict:
    """Last-resort file-level cleanup when reviewed upstream --force fails.

    Only bridge-owned recorded files, its own backup directory and record are
    quarantined. Backed-up original game files are restored when available.
    Does NOT pretend to repair an interrupted Proton-prefix journal.
    """
    if not isinstance(record, dict) or record.get("version") != 1 or not isinstance(
            record.get("launcher"), dict):
        raise ValueError("Untrusted bridge installation record")
    entries = record.get("files")
    installed = record.get("installed")
    if not isinstance(entries, list) or not isinstance(installed, list) or len(entries) > 20000:
        raise ValueError("Invalid bridge manifest")
    by_name = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("existed"), bool):
            raise ValueError("Invalid bridge file entry")
        name, digest = entry.get("path"), entry.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or not all(
                c in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid bridge file digest")
        _safe_member(folder, name)
        if name in by_name:
            raise ValueError("Duplicate bridge file entry")
        by_name[name] = entry
    if len(installed) != len(set(installed)) or not all(
            isinstance(name, str) and name in by_name for name in installed):
        raise ValueError("Invalid bridge installed entries")
    # Reject any symlink traversals before moving a single item.
    for name in installed:
        _safe_member(folder, name)
    for name in (".amdnr-linux-backup", ".amdnr-linux-install.json", "amdnr-linux"):
        _safe_member(folder, name)
    backup = folder / ".amdnr-linux-backup"
    record_path = folder / ".amdnr-linux-install.json"
    if record_path.is_symlink() or not record_path.is_file():
        raise ValueError("Bridge record disappeared; inspect before forced cleanup.")
    base = folder / ".amdnr-force-removals"
    if base.is_symlink() or (base.exists() and not base.is_dir()):
        raise ValueError("Unsafe bridge quarantine directory")
    base.mkdir(mode=0o700, exist_ok=True)
    snapshot = base / uuid.uuid4().hex
    snapshot.mkdir(mode=0o700)
    doc = {"format": 1, "state": "moving", "files": list(installed),
           "game": str(folder), "restored_originals": [],
           "missing_originals": [], "prefix_recovery": "requires_review"}
    def write_manifest():
        pending = snapshot / ".pending-manifest"
        with pending.open("w", encoding="utf-8") as file:
            json.dump(doc, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(pending, snapshot / "manifest.json")
    write_manifest()
    # Quarantine installed files exactly as listed, leaving unrelated files.
    # Move whole bridge runtime folder to retain any unlisted internal logs.
    move_names = [name for name in installed
                  if not name.startswith("amdnr-linux/") and name != "amdnr-linux"]
    move_names += ["amdnr-linux", ".amdnr-linux-backup", ".amdnr-linux-install.json"]
    moved = []
    try:
        for name in move_names:
            src = _safe_member(folder, name)
            if not src.exists():
                continue
            destination = _safe_member(snapshot / "original", name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                raise ValueError("Recovery snapshot destination occupied: " + name)
            os.replace(src, destination)
            moved.append(name)
            doc["moved"] = list(moved)
            write_manifest()
        saved_backups = snapshot / "original/.amdnr-linux-backup"
        for name in installed:
            entry = by_name[name]
            if not entry["existed"]:
                continue
            restored_source = _safe_member(saved_backups, name)
            target = _safe_member(folder, name)
            if target.exists() or target.is_symlink():
                raise ValueError("Original bridge replacement path is occupied: " + name)
            if restored_source.is_file() and not restored_source.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                # Retain immutable snapshot of the original backup.
                shutil.copy2(restored_source, target)
                doc["restored_originals"].append(name)
            else:
                doc["missing_originals"].append(name)
            write_manifest()
        doc["state"] = "quarantined"
        write_manifest()
    except Exception:
        doc["state"] = "needs_recovery"
        write_manifest()
        raise
    return {"forced_quarantine": str(snapshot), "moved": moved,
            "restored_originals": doc["restored_originals"],
            "missing_originals": doc["missing_originals"],
            "prefix_recovery": "requires_review"}
