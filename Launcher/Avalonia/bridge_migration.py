"""Opt-in migration of conflicting AMDNR/ReShade files to a recoverable snapshot.

Only named entries in the selected game's executable folder and AMDNR-managed
records/backups in its ancestors are moved. Nothing in the Proton prefix or
Steam configuration is modified. Never overwrite an existing destination while
rolling back. Recovery is deliberately explicit if interrupted.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import uuid

SNAPSHOTS = ".amdnr-bridge-migrations"
MANIFEST = "manifest.json"
HOOKS = (
    "ReShade.ini", "ReShade.log", "ReShadePreset.ini", "dxgi.dll",
    "winmm.dll", "version.dll", "dbghelp.dll", "wininet.dll",
    "winhttp.dll", "d3d12.dll", "d3d12core.dll", "OptiScaler.ini",
)
MANAGED = (
    ".amdnr-linux-install.json", "AMDNR_backup",
    ".amdnr-linux-backup", "amdnr-linux", ".amdnr-linux-transaction.json",
    ".amdnr-maintenance-staging",
)


def game_root(executable: Path) -> Path:
    if not executable.is_file() or executable.is_symlink() or executable.suffix.lower() != ".exe":
        raise ValueError("Select an existing, regular Windows game executable.")
    folder = executable.absolute().parent
    for ancestor in (folder, *folder.parents):
        if ancestor.parent.name == "common" and ancestor.parent.parent.name == "steamapps":
            return ancestor
    return folder


def _folders(executable: Path) -> tuple[Path, list[Path]]:
    folder = executable.absolute().parent
    root = game_root(executable)
    ancestors = []
    current = folder
    while True:
        ancestors.append(current)
        if current == root:
            break
        if current == current.parent:
            raise ValueError("Selected game folder is outside its root.")
        current = current.parent
    return root, ancestors


def candidates(executable: Path) -> tuple[Path, list[str]]:
    root, folders = _folders(executable)
    paths: list[str] = []
    for folder in folders:
        names = MANAGED + (HOOKS if folder == folders[0] else ())
        for name in names:
            target = folder / name
            if target.exists() or target.is_symlink():
                if target.is_symlink() or not (target.is_file() or target.is_dir()):
                    raise ValueError(f"Unsafe existing game path: {target}")
                paths.append(target.relative_to(root).as_posix())
    return root, sorted(set(paths))


def _manifest(snapshot: Path, document: dict) -> None:
    fd, pending_name = tempfile.mkstemp(prefix=".migration-", dir=snapshot)
    pending = Path(pending_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(document, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(pending, snapshot / MANIFEST)
    finally:
        pending.unlink(missing_ok=True)


def snapshot_existing(executable: Path) -> dict:
    root, paths = candidates(executable)
    if not paths:
        return {"snapshot": None, "files": [], "status": "nothing_to_move"}
    base = root / SNAPSHOTS
    if base.is_symlink() or (base.exists() and not base.is_dir()):
        raise ValueError("Unsafe bridge migration snapshot directory.")
    base.mkdir(mode=0o700, exist_ok=True)
    # Do not begin a second migration while a prior one is unresolved.
    for folder in base.iterdir():
        record = folder / MANIFEST
        if not record.is_file() or record.is_symlink():
            raise ValueError("Unrecognized prior migration snapshot; inspect before replacing.")
        state = json.loads(record.read_text(encoding="utf-8")).get("status")
        if state not in ("installed", "restored"):
            raise ValueError("Interrupted migration exists; recover it before retrying.")
    snapshot = base / uuid.uuid4().hex
    snapshot.mkdir(mode=0o700)
    doc = {"format": 1, "status": "moving", "files": paths, "root": str(root)}
    _manifest(snapshot, doc)
    try:
        for relative in paths:
            src = root / relative
            dst = snapshot / "original" / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_symlink() or not (src.is_file() or src.is_dir()):
                raise ValueError(f"Migration source changed: {src}")
            if dst.exists() or dst.is_symlink():
                raise ValueError(f"Migration snapshot collision: {dst}")
            os.replace(src, dst)
        doc["status"] = "backed_up"
        _manifest(snapshot, doc)
        return {"snapshot": str(snapshot), "files": paths, "status": "backed_up"}
    except Exception:
        restore_snapshot(snapshot)
        raise


def mark_installed(snapshot: Path) -> None:
    doc = json.loads((snapshot / MANIFEST).read_text(encoding="utf-8"))
    if doc.get("status") != "backed_up":
        raise ValueError("Unexpected migration state before bridge installation.")
    doc["status"] = "installed"
    _manifest(snapshot, doc)


def latest_installed_snapshot(executable: Path) -> Path | None:
    root = game_root(executable)
    base = root / SNAPSHOTS
    if not base.exists():
        return None
    if base.is_symlink() or not base.is_dir():
        raise ValueError("Unsafe migration history directory.")
    installed = []
    for folder in base.iterdir():
        record = folder / MANIFEST
        if folder.is_symlink() or not record.is_file() or record.is_symlink():
            raise ValueError("Unknown migration history entry; inspect manually.")
        document = json.loads(record.read_text(encoding="utf-8"))
        if document.get("status") == "installed":
            installed.append(folder)
    if len(installed) > 1:
        raise ValueError("Several installed snapshots exist; select recovery manually.")
    return installed[0] if installed else None


def pending_snapshot(executable: Path) -> Path | None:
    root = game_root(executable)
    base = root / SNAPSHOTS
    if not base.exists():
        return None
    if base.is_symlink() or not base.is_dir():
        raise ValueError("Unsafe migration history directory.")
    pending = []
    for folder in base.iterdir():
        record = folder / MANIFEST
        if folder.is_symlink() or not record.is_file() or record.is_symlink():
            raise ValueError("Unknown migration history entry.")
        state = json.loads(record.read_text(encoding="utf-8")).get("status")
        if state in ("moving", "backed_up", "needs_recovery"):
            pending.append(folder)
    if len(pending) > 1:
        raise ValueError("Multiple interrupted migration snapshots exist.")
    return pending[0] if pending else None


def recover_pending(executable: Path) -> dict:
    snapshot = pending_snapshot(executable)
    if snapshot is None:
        return {"status": "nothing_to_restore", "restored": [], "blocked": []}
    target = executable.absolute().parent
    if ((target / "amdnr-linux/run.sh").exists() or
            (target / ".amdnr-linux-install.json").exists()):
        raise ValueError("A bridge installation is present; remove it with its manager first.")
    return restore_snapshot(snapshot)


def restore_snapshot(snapshot: Path) -> dict:
    """Restore only paths which are absent; never overwrite another installation.

    Requires that any partly installed bridge be removed by its own manager
    before recovering original hooks. Incomplete restoration remains recorded.
    """
    if snapshot.is_symlink() or not (snapshot / MANIFEST).is_file():
        raise ValueError("Missing or unsafe migration manifest.")
    doc = json.loads((snapshot / MANIFEST).read_text(encoding="utf-8"))
    root = Path(doc["root"])
    if (doc.get("format") != 1 or snapshot.parent.resolve() != (root / SNAPSHOTS).resolve()
            or not isinstance(doc.get("files"), list)):
        raise ValueError("Unrecognized migration manifest.")
    blocked = []
    restored = []
    for relative in reversed(doc["files"]):
        if not isinstance(relative, str) or relative.startswith("/") or ".." in Path(relative).parts:
            raise ValueError("Unsafe migration record path.")
        src = snapshot / "original" / relative
        dest = root / relative
        if not src.exists():
            if dest.exists():
                continue
            blocked.append(relative + " (snapshot missing)")
            continue
        if src.is_symlink() or dest.exists() or dest.is_symlink():
            blocked.append(relative + " (destination occupied or unsafe)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dest)
        restored.append(relative)
    doc["status"] = "restored" if not blocked else "needs_recovery"
    _manifest(snapshot, doc)
    return {"restored": restored, "blocked": blocked, "snapshot": str(snapshot)}
