"""Independent, safety-first Linux AMDNR maintenance helpers.

The existing install record is deliberately kept compatible. Operations refuse
unexpected files/symlinks and never delete originals whose hashes changed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import time
import uuid
import zipfile


JOURNAL_NAME = ".amdnr-linux-transaction.json"
TRANSACTION_DIR = "linux-maintenance-rollback"
MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_JOURNAL_BYTES = 4 * 1024 * 1024


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    member = PurePosixPath(relative.replace("\\", "/"))
    if (not relative or member.is_absolute() or ".." in member.parts or
            not member.parts or any(":" in p for p in member.parts) or
            "\x00" in relative or str(member) != relative.replace("\\", "/")):
        raise ValueError("Unsafe path in maintenance operation")
    path = root.joinpath(*member.parts)
    anchor = root.resolve()
    if not path.resolve().is_relative_to(anchor):
        raise ValueError("Path escapes game folder")
    return path


def write_json_atomic(path: Path, document: dict) -> None:
    data = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()
    if len(data) > MAX_JOURNAL_BYTES:
        raise ValueError("Maintenance record exceeds safety limit")
    fd, temp_name = tempfile.mkstemp(prefix=".amdnr-write-", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        # Persist the rename as well as file contents for power-loss recovery.
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp.unlink(missing_ok=True)


def valid_record(root: Path) -> dict:
    filename = root / ".amdnr-linux-install.json"
    if filename.is_symlink() or not filename.is_file() or filename.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError("No safe managed AMDNR installation record")
    state = json.loads(filename.read_text())
    if state.get("format") != 1 or not isinstance(state.get("files"), list):
        raise ValueError("Unsupported AMDNR installation record")
    seen = set()
    for entry in state["files"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid managed entry")
        name, sha = entry.get("path"), entry.get("sha256")
        if not isinstance(name, str) or not isinstance(sha, str) or len(sha) != 64:
            raise ValueError("Malformed tracked filename or digest")
        int(sha, 16)
        safe_path(root, name)
        if name.casefold() in seen:
            raise ValueError("Duplicate managed path")
        seen.add(name.casefold())
    return state


def status(executable: Path) -> dict:
    root = executable.resolve().parent
    journal = root / JOURNAL_NAME
    return {"interrupted": journal.exists() or journal.is_symlink(),
            "journal": str(journal),
            "recovery_available": journal.is_file() and not journal.is_symlink(),
            "note": "Do not run install/uninstall while an interrupted maintenance journal exists."}


def _ensure_not_running(executable: Path) -> None:
    try:
        from linux_environment import game_running
        report = game_running(executable)
        if report.get("running"):
            raise ValueError("Game appears to be running; quit it before changing AMDNR files")
    except ImportError:
        # Standalone backend imports can lack Linux-only diagnostics; this is
        # an advisory safety check rather than a GPU compatibility guarantee.
        pass


def _preflight(root: Path, state: dict) -> dict:
    if (root / JOURNAL_NAME).exists() or (root / JOURNAL_NAME).is_symlink():
        raise ValueError("Interrupted maintenance journal exists; recover first")
    files = {}
    for entry in state["files"]:
        path = safe_path(root, entry["path"])
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("Unsafe managed destination: " + entry["path"])
        files[entry["path"]] = entry
    return files


def _write_binary_atomic(source: Path, target: Path) -> None:
    if target.is_symlink():
        raise ValueError("Refusing symlink target")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".amdnr-install-", dir=target.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as dest, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, dest, length=1024 * 1024)
            dest.flush()
            os.fsync(dest.fileno())
        os.replace(tmp, target)
        directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        tmp.unlink(missing_ok=True)


def restore_transaction(executable: Path) -> dict:
    """Explicit, hash-guarded crash recovery. Never overwrites third-party edits."""
    root = executable.resolve().parent
    journal = root / JOURNAL_NAME
    if journal.is_symlink() or not journal.is_file() or journal.stat().st_size > MAX_JOURNAL_BYTES:
        raise ValueError("No safe recovery journal")
    doc = json.loads(journal.read_text())
    if not isinstance(doc, dict):
        raise ValueError("Invalid recovery journal")
    if doc.get("format") != 1 or not isinstance(doc.get("touched"), list):
        raise ValueError("Invalid recovery journal")
    snapshot = root / "AMDNR_backup" / TRANSACTION_DIR
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise ValueError("Rollback snapshot missing or unsafe")
    operations = []
    seen = set()
    for entry in doc["touched"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("Malformed recovery entry")
        name = entry["path"]
        if name.casefold() in seen:
            raise ValueError("Duplicate recovery entry")
        seen.add(name.casefold())
        target = safe_path(root, name)
        saved = safe_path(snapshot, name)
        if target.is_symlink():
            raise ValueError("Target changed to a symlink: " + name)
        old_sha = entry.get("previous_sha256")
        new_sha = entry.get("expected_sha256")
        if (old_sha is not None and (not isinstance(old_sha, str) or len(old_sha) != 64)) or (
                new_sha is not None and (not isinstance(new_sha, str) or len(new_sha) != 64)):
            raise ValueError("Malformed recovery entry")
        for value in (old_sha, new_sha):
            if value is not None:
                try:
                    int(value, 16)
                except ValueError as exc:
                    raise ValueError("Malformed recovery digest") from exc
        if target.exists() and not target.is_file():
            raise ValueError("Unsafe recovery destination: " + name)
        current = digest(target) if target.is_file() else None
        if current not in (old_sha, new_sha, None):
            raise ValueError("File changed independently; refusing rollback: " + name)
        if old_sha is not None and (saved.is_symlink() or not saved.is_file() or
                                    digest(saved) != old_sha):
            raise ValueError("Original recovery copy is missing or changed: " + name)
        if old_sha is None and current is None:
            continue
        if old_sha is not None and current is None:
            # Missing destination may have been deleted by another process.
            # Restoring it is safe because no file will be overwritten.
            pass
        operations.append((target, saved, old_sha, current))
    state_file = root / ".amdnr-linux-install.json"
    old_state_file = snapshot / "original-install.json"
    if old_state_file.is_symlink() or not old_state_file.is_file():
        raise ValueError("Original installation record snapshot missing")
    old_record_sha = doc.get("state_sha256")
    new_record_sha = doc.get("new_state_sha256")
    if state_file.is_symlink() or (state_file.exists() and not state_file.is_file()):
        raise ValueError("Unsafe installation record destination")
    if not isinstance(old_record_sha, str) or len(old_record_sha) != 64:
        raise ValueError("Malformed installation record checksum")
    if digest(old_state_file) != old_record_sha:
        raise ValueError("Installation record snapshot changed")
    current_state_sha = digest(state_file) if state_file.is_file() and not state_file.is_symlink() else None
    if current_state_sha not in (old_record_sha, new_record_sha):
        raise ValueError("Installation record changed; refusing rollback")
    # No game file is modified until every target and rollback copy validates.
    for target, saved, old_sha, current in operations:
        if current == old_sha:
            continue
        if old_sha is None:
            target.unlink(missing_ok=True)
        else:
            _write_binary_atomic(saved, target)
    _write_binary_atomic(old_state_file, state_file)
    journal.unlink()
    shutil.rmtree(snapshot)
    return {"status": "restored", "files_checked": len(doc["touched"])}


def repair_automatically(executable: Path, *, allow_modified: bool = False) -> dict:
    """Resolve the recorded official package without asking for a ZIP path."""
    import amdnr_launcher as core
    root = executable.resolve().parent
    state = valid_record(root)
    _preflight(root, state)
    asset = state.get("source_archive")
    expected = state.get("source_sha256")
    if (not isinstance(asset, str) or not asset.endswith(".zip") or
            not isinstance(expected, str) or len(expected) != 64):
        raise ValueError("This older installation has no verifiable package record; select a ZIP manually")
    candidates = []
    cache = core._release_cache_dir()
    if cache.is_dir():
        candidates = [p for p in list(cache.glob("*/" + asset))[:64]
                      if p.is_file() and not p.is_symlink()]
    for path in candidates:
        if digest(path) == expected:
            return repair_or_update(executable, path, allow_modified=allow_modified)
    # Official upstream release lookup only; no fork URLs or unverified copies.
    matches = [item for item in core.release_catalog(limit=30)
               if item.get("asset") == asset]
    for item in matches:
        downloaded = core.download_release(item["tag"], asset)
        if digest(downloaded) == expected:
            return repair_or_update(executable, downloaded, allow_modified=allow_modified)
    raise ValueError("Exact recorded package unavailable from verified cache or official recent releases; select the original ZIP manually")


def repair_or_update(executable: Path, archive: Path, *, update: bool = False,
                     allow_modified: bool = False, alias: str | None = None) -> dict:
    """Prepare a complete transaction and preserve a crash recovery journal.

    Files restored from missing/modified entries must match the package's
    installed checksums. Updates may add/remove paths only when they cannot
    destroy original user backups.
    """
    import amdnr_launcher as core
    if not executable.is_file() or executable.is_symlink() or executable.suffix.lower() != ".exe":
        raise ValueError("Select the Windows game executable")
    root = executable.resolve().parent
    _ensure_not_running(executable)
    state = valid_record(root)
    originals = _preflight(root, state)
    if not archive.is_file() or archive.is_symlink() or not zipfile.is_zipfile(archive):
        raise ValueError("Select a regular AMDNR ZIP")
    if not update and (not isinstance(state.get("source_sha256"), str) or
                       digest(archive) != state["source_sha256"]):
        raise ValueError("Repair requires the exact recorded package SHA-256")
    if alias is None:
        alias = state.get("alias")
    if alias != state.get("alias"):
        raise ValueError("Change the proxy separately before updating")
    staged_root = root / ".amdnr-maintenance-staging"
    if staged_root.exists() or staged_root.is_symlink():
        raise ValueError("Stale maintenance staging exists; inspect before retrying")
    try:
        staged_root.mkdir(mode=0o700)
        staged = core._package_files(archive, staged_root)
        candidates = {}
        for file in staged:
            name = file.relative_to(staged_root)
            if name.name.casefold() == "optiscaler.dll":
                name = name.with_name(alias)
            relative = name.as_posix()
            safe_path(root, relative)
            if relative.casefold() in (k.casefold() for k in candidates):
                raise ValueError("Archive has duplicate destination")
            candidates[relative] = file
        if not candidates:
            raise ValueError("Archive has no installable payload")
        existing = set(originals)
        new_names = set(candidates)
        changed = {}
        removed = sorted(existing - new_names)
        added = sorted(new_names - existing)
        for name, old_entry in originals.items():
            dest = safe_path(root, name)
            current = digest(dest) if dest.is_file() else None
            if (current != old_entry["sha256"] and not allow_modified
                    and current is not None):
                raise ValueError("Modified managed file; explicit backup approval required: " + name)
            if old_entry.get("backed_up"):
                old_backup = safe_path(root / "AMDNR_backup" / "linux-launcher", name)
                if old_backup.is_symlink() or not old_backup.is_file():
                    raise ValueError("Original backup missing: " + name)
            if name in removed and old_entry.get("backed_up"):
                raise ValueError("Update would orphan original backup: " + name)
        for name in added:
            dest = safe_path(root, name)
            if dest.exists() or dest.is_symlink():
                raise ValueError("Update would overwrite an unmanaged file: " + name)
        for name, source in candidates.items():
            previous = originals.get(name)
            actual_sha = digest(source)
            if previous is not None and not update and actual_sha != previous["sha256"]:
                raise ValueError("Repair ZIP differs from recorded installed payload: " + name)
            dest = safe_path(root, name)
            current = digest(dest) if dest.is_file() else None
            if current != actual_sha:
                changed[name] = (source, current, actual_sha)
        for name in removed:
            dest = safe_path(root, name)
            changed[name] = (None, digest(dest) if dest.is_file() else None, None)
        if not changed:
            return {"status": "already_healthy", "changed": 0}
        snapshot = root / "AMDNR_backup" / TRANSACTION_DIR
        if snapshot.exists() or snapshot.is_symlink():
            raise ValueError("Existing rollback snapshot must be resolved first")
        snapshot.mkdir(parents=True, mode=0o700)
        try:
            state_file = root / ".amdnr-linux-install.json"
            original_record = snapshot / "original-install.json"
            shutil.copy2(state_file, original_record)
            touched = []
            for name, (source, old_sha, new_sha) in changed.items():
                dest = safe_path(root, name)
                if old_sha is not None:
                    backup = safe_path(snapshot, name)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, backup)
                    if digest(backup) != old_sha or digest(dest) != old_sha:
                        raise ValueError("File changed during snapshot: " + name)
                touched.append({"path": name,
                                "previous_sha256": old_sha,
                                "expected_sha256": new_sha})
            new_record = {**state}
            new_record["source_archive"] = archive.name
            new_record["source_sha256"] = digest(archive)
            new_record["files"] = [
                {"path": name, "sha256": digest(source),
                 "backed_up": originals.get(name, {}).get("backed_up", False)}
                for name, source in candidates.items()
            ]
            new_bytes = (json.dumps(new_record, sort_keys=True, indent=2) + "\n").encode()
            write_json_atomic(root / JOURNAL_NAME, {
                "format": 1, "touched": touched, "state_sha256": digest(state_file),
                "new_state_sha256": hashlib.sha256(new_bytes).hexdigest(),
            })
            try:
                # The journal exists before the first destructive action.
                for name, (source, old_sha, _) in changed.items():
                    dest = safe_path(root, name)
                    current = digest(dest) if dest.is_file() else None
                    if current != old_sha:
                        raise ValueError("Destination changed after backup: " + name)
                    if source is None:
                        dest.unlink(missing_ok=True)
                    else:
                        _write_binary_atomic(source, dest)
                write_json_atomic(state_file, new_record)
            except Exception:
                restore_transaction(executable)
                raise
            # Retain user-modified files separately; never lose them during repair.
            if allow_modified:
                modified = [(name, before) for name, (_, before, _) in changed.items()
                            if name in originals and before not in (None, originals[name]["sha256"])]
                if modified:
                    preserved = root / "AMDNR_backup" / ("linux-repair-preserved-" + uuid.uuid4().hex)
                    for name, before in modified:
                        source = safe_path(snapshot, name)
                        target = safe_path(preserved, name)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
            (root / JOURNAL_NAME).unlink()
            shutil.rmtree(snapshot)
            return {"status": "updated" if update else "repaired",
                    "changed": len(changed), "removed": len(removed),
                    "added": len(added), "source_archive": archive.name}
        except Exception:
            # Before a journal exists it is safe to remove a partial snapshot.
            if not (root / JOURNAL_NAME).exists() and snapshot.exists():
                shutil.rmtree(snapshot)
            raise
    finally:
        if staged_root.is_dir() and not staged_root.is_symlink():
            shutil.rmtree(staged_root)


def next_proxy(executable: Path, aliases: tuple[str, ...]) -> dict:
    """Move only a clean launcher-owned proxy, never replace an existing DLL."""
    root = executable.resolve().parent
    _ensure_not_running(executable)
    state = valid_record(root)
    _preflight(root, state)
    current = state.get("alias")
    if current not in aliases or current.lower().endswith(".asi"):
        raise ValueError("Current proxy is not a switchable DLL")
    item = next((e for e in state["files"] if e["path"].casefold() == current.casefold()), None)
    if item is None or item.get("backed_up"):
        raise ValueError("Proxy with an original backup requires uninstall/restore before switching")
    source = safe_path(root, item["path"])
    if not source.is_file() or source.is_symlink() or digest(source) != item["sha256"]:
        raise ValueError("Current proxy modified; refusing to move it")
    tried = list(state.get("tried_proxies", []))
    if current not in tried:
        tried.append(current)
    order = [x for x in aliases if x.lower().endswith(".dll")]
    offset = order.index(current)
    candidate = None
    for i in range(1, len(order) + 1):
        possible = order[(offset + i) % len(order)]
        dest = safe_path(root, possible)
        if possible == current or dest.exists() or dest.is_symlink():
            continue
        candidate = possible
        break
    if candidate is None:
        raise ValueError("No unoccupied proxy DLL alias available")
    dest = safe_path(root, candidate)
    os.rename(source, dest)
    try:
        item["path"] = candidate
        state["alias"] = candidate
        state["tried_proxies"] = tried
        write_json_atomic(root / ".amdnr-linux-install.json", state)
    except Exception:
        if dest.exists() and not source.exists() and digest(dest) == item["sha256"]:
            os.rename(dest, source)
        raise
    return {"status": "proxy_switched", "alias": candidate, "previous": current,
            "tried": tried, "override": f'WINEDLLOVERRIDES="{candidate[:-4]}=n,b" %command%'}
