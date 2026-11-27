#!/usr/bin/env python3
"""Opt-in adapter for the separately maintained AMDNR-Linux GPL-3.0+ bridge.

No third-party source is copied into this repository. A checksum-pinned published
release is downloaded only on explicit Prepare. Its unmodified setup/manage CLI
does the staging and installation with its own backup and recovery records.

This module never writes Steam settings, Proton configurations or game files
without a separate --approve-bridge-install / --approve-bridge-remove action.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

VERSION = "0.3.7"
ARCHIVE = f"AMDNR-Linux-v{VERSION}.tar.gz"
URL = f"https://github.com/hassanm0301/AMDNR-Linux/releases/download/linux-v{VERSION}/{ARCHIVE}"
SHA256 = "7e4ddb01a352a824bbf6009cfd8a1c0728267679e4a170d33fc8e01f91b84423"
PROJECT = "https://github.com/hassanm0301/AMDNR-Linux"
SOURCE_ROOT = f"AMDNR-Linux-v{VERSION}"
MAX_ARCHIVE_BYTES = 90 * 1024 * 1024
MAX_UNPACKED_BYTES = 450 * 1024 * 1024
OWN_RECORD = ".amdnr-linux-install.json"  # used by both installers, with incompatible formats


def cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "amdnr-linux" / "community-bridge" / VERSION


def file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def source_path() -> Path:
    return cache_dir() / "source" / SOURCE_ROOT


def prepared_path() -> Path:
    return cache_dir() / "package"


def _game_directory(exe: Path) -> Path:
    if not exe.is_file() or exe.is_symlink() or exe.suffix.casefold() != ".exe":
        raise ValueError("Select an existing, regular Windows game executable.")
    return exe.resolve().parent


def game_conflicts(exe: Path) -> list[str]:
    """Fail closed for our installations, existing ReShade and unmanaged hooks."""
    target = _game_directory(exe)
    problems = []
    # Our own recorded installations can be at the top-level Steam launcher,
    # even when the real Unreal executable is in a nested Win64 directory.
    ancestor = target
    for _ in range(7):
        marker = ancestor / OWN_RECORD
        if marker.exists() or marker.is_symlink():
            problems.append(f"Existing AMDNR installation record: {marker}")
        backup = ancestor / "AMDNR_backup"
        if backup.exists() or backup.is_symlink():
            problems.append(f"Existing launcher backup: {backup}")
        if ancestor.name.lower() == "common" or ancestor == ancestor.parent:
            break
        ancestor = ancestor.parent
    if (target / "amdnr-linux").exists() or (target / ".amdnr-linux-backup").exists():
        problems.append("An existing community bridge installation or backup is present.")
    # Existing ReShade is especially relevant to Subnautica 2. Do not mix hooks.
    for item in ("ReShade.ini", "ReShade.log", "ReShadePreset.ini", "dxgi.dll",
                 "winmm.dll", "version.dll", "dbghelp.dll", "wininet.dll", "winhttp.dll",
                 "d3d12.dll", "d3d12core.dll", "OptiScaler.ini"):
        if (target / item).exists() or (target / item).is_symlink():
            problems.append(f"Existing game DLL/mod configuration: {item}")
    return problems


def status(exe: Path | None = None) -> dict:
    src = source_path()
    package = prepared_path()
    archive = cache_dir() / ARCHIVE
    report = {
        "provider": "hassanm0301/AMDNR-Linux",
        "source": PROJECT,
        "version": VERSION,
        "license": "GPL-3.0-or-later; LGPL vkd3d; upstream third-party notices",
        "archive_sha256": SHA256,
        "release_verified": archive.is_file() and not archive.is_symlink()
            and file_hash(archive) == SHA256,
        "source_ready": (src / "RELEASE-MANIFEST.json").is_file()
            and (src / "linux/setup.py").is_file(),
        "prepared": (package / "amdnr-linux/run.sh").is_file()
            and (package / "d3d12.dll").is_file(),
        "required_proton": "Wine 11-based Proton (tested GE-Proton11-9)",
        "tested_gpu": "RX 9070 XT; other GPUs not validated",
        "steam_options_unchanged": True,
    }
    if exe is not None:
        report["exe"] = str(exe)
        report["community_installed"] = (exe.parent / "amdnr-linux/run.sh").is_file()
        if not exe.is_file():
            report["conflicts"] = ["Selected Windows executable is missing."]
        else:
            report["conflicts"] = game_conflicts(exe)
        report["can_install"] = report["prepared"] and not report["conflicts"]
    return report


def safe_extract(archive: Path, destination: Path) -> Path:
    """Whitelist regular entries beneath the single expected source root."""
    if destination.exists():
        raise ValueError("Source destination already exists. Refusing to overwrite it.")
    entries = []
    total = 0
    with tarfile.open(archive, "r:gz") as opened:
        for member in opened:
            name = PurePosixPath(member.name)
            if (name.is_absolute() or ".." in name.parts or
                    not name.parts or name.parts[0] != SOURCE_ROOT or
                    not (member.isfile() or member.isdir())):
                raise ValueError(f"Unsafe or unsupported archive entry: {member.name}")
            if member.isfile():
                total += member.size
                if total > MAX_UNPACKED_BYTES or member.size < 0:
                    raise ValueError("Community release expands beyond safe size limit.")
            entries.append(member)
        if not any(member.name == SOURCE_ROOT + "/RELEASE-MANIFEST.json"
                   for member in entries):
            raise ValueError("Expected community release manifest is missing.")
        destination.mkdir(parents=True)
        for member in entries:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with opened.extractfile(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                # The release's CLI may include executable shell scripts.
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    return destination / SOURCE_ROOT


def fetch_verified() -> Path:
    destination = cache_dir()
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / ARCHIVE
    if archive.is_file() and not archive.is_symlink() and file_hash(archive) == SHA256:
        return archive
    if archive.exists() or archive.is_symlink():
        raise ValueError("Cached community release failed SHA-256; inspect/remove it manually.")
    handle, tmp = tempfile.mkstemp(prefix=".download-", dir=destination)
    try:
        with os.fdopen(handle, "wb") as file, urllib.request.urlopen(URL, timeout=40) as response:
            if response.geturl().split("/")[0] not in ("https:",):
                raise ValueError("Unexpected insecure download redirect.")
            size = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                if size > MAX_ARCHIVE_BYTES:
                    raise ValueError("Community release download exceeds size limit.")
                file.write(block)
        if file_hash(Path(tmp)) != SHA256:
            raise ValueError("Pinned community release SHA-256 mismatch.")
        os.replace(tmp, archive)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return archive


def prepare(compiler: Path) -> dict:
    if sys.version_info < (3, 12):
        raise ValueError("Community bridge preparation requires Python 3.12 or newer.")
    if not compiler.is_file() or compiler.is_symlink() or compiler.name.lower() != "d3dcompiler_47.dll":
        raise ValueError("Choose your own native x64 Microsoft d3dcompiler_47.dll.")
    if prepared_path().exists():
        raise ValueError("Community package already exists. Review it instead of overwriting.")
    archive = fetch_verified()
    src = source_path()
    if not src.exists():
        safe_extract(archive, src.parent)
    if not (src / "linux/setup.py").is_file() or not (src / "RELEASE-MANIFEST.json").is_file():
        raise ValueError("Downloaded release does not have the expected source layout.")
    manifest = json.loads((src / "RELEASE-MANIFEST.json").read_text())
    if manifest.get("release") != "linux-v" + VERSION:
        raise ValueError("Community release manifest identifies a different release.")
    command = [sys.executable, str(src / "linux/setup.py"), "prepare",
               "--compiler", str(compiler.resolve()),
               "--output", str(prepared_path()),
               "--cache", str(cache_dir() / "upstream-cache")]
    # Running third-party GPL setup code requires the user's separate Prepare
    # click. It fetches pinned upstream AMDNR/ROCm assets into our private cache.
    finished = subprocess.run(command, cwd=src, text=True, capture_output=True,
                              timeout=2400, check=False)
    if finished.returncode:
        raise ValueError("Community setup failed (exit %d): %s" %
                         (finished.returncode, (finished.stdout + "\n" + finished.stderr)[-5000:]))
    if not status()["prepared"]:
        raise ValueError("Community setup completed without the expected staged package.")
    return {"prepared": True, "package": str(prepared_path()),
            "provider": PROJECT, "output": finished.stdout[-1500:]}


def install(exe: Path, approved: bool) -> dict:
    if not approved:
        raise ValueError("Bridge installation requires explicit user approval.")
    folder = _game_directory(exe)
    report = status(exe)
    if not report["prepared"]:
        raise ValueError("Prepare the checksum-verified community package first.")
    if report["conflicts"]:
        raise ValueError("Refusing to overwrite an existing AMDNR/ReShade setup:\n" +
                         "\n".join(report["conflicts"]))
    manager = source_path() / "linux/manage.py"
    if not manager.is_file():
        raise ValueError("Verified community management tool is missing.")
    # Recheck just before writing, preventing stale UI decisions.
    if game_conflicts(exe):
        raise ValueError("Files changed since preview. Reopen compatibility checks.")
    command = [sys.executable, str(manager), "install", str(prepared_path()),
               str(folder), "--exe", str(exe.resolve()), "--proxy", "auto"]
    finished = subprocess.run(command, cwd=source_path(), text=True,
                              capture_output=True, timeout=300, check=False)
    if finished.returncode:
        raise ValueError("Community manager refused installation:\n" +
                         (finished.stdout + "\n" + finished.stderr)[-4000:])
    wrapper = folder / "amdnr-linux/run.sh"
    return {"installed": True, "exe": str(exe), "manager": PROJECT,
            "launch_option_preview": f'"{wrapper}" %command%',
            "steam_modified": False,
            "warning": "Copy launch option manually. On first game launch the wrapper "
                       "will modify the existing Proton prefix with journaled HIP/compiler files. "
                       "Preserve the community installation folder and backups.",
            "output": finished.stdout[-1600:]}


def remove(exe: Path, approved: bool) -> dict:
    if not approved:
        raise ValueError("Community bridge removal requires explicit consent.")
    folder = _game_directory(exe)
    if not (folder / "amdnr-linux/run.sh").is_file():
        raise ValueError("No community bridge wrapper; refusing removal.")
    record = folder / OWN_RECORD
    if not record.is_file() or record.is_symlink():
        raise ValueError("No trusted community installation record; refusing removal.")
    data = json.loads(record.read_text())
    if not isinstance(data.get("launcher"), dict):
        raise ValueError("Record is not a community-managed installation; refusing removal.")
    manager = source_path() / "linux/manage.py"
    if not manager.is_file():
        raise ValueError("Original community manager missing; cannot restore backups.")
    finished = subprocess.run([sys.executable, str(manager), "uninstall", str(folder)],
                              cwd=source_path(), text=True, capture_output=True, timeout=300)
    if finished.returncode:
        raise ValueError("Uninstall stopped; inspect changed files before retrying: " +
                         (finished.stdout + "\n" + finished.stderr)[-4000:])
    return {"removed": True, "steam_modified": False,
            "warning": "Remove the bridge wrapper from your Steam launch options manually.",
            "output": finished.stdout[-1000:]}
