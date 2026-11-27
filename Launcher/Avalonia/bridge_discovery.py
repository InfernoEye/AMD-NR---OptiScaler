"""Read-only, bounded host checks for the optional community ROCm bridge.

Never changes Steam launch options, game files, prefixes, system packages or GPUs.
Compiler candidates are x64 PE files, NOT claims of Microsoft provenance.
"""
from __future__ import annotations

import os
from pathlib import Path
import struct
import sys
import time

MAX_DIRS = 2800
MAX_FILES = 24000
MAX_SECONDS = 7.0
MAX_CANDIDATES = 16
MIN_COMPILER_BYTES = 64 * 1024
MAX_COMPILER_BYTES = 100 * 1024 * 1024


def _real_regular(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink()
    except OSError:
        return False


def is_x64_pe(path: Path) -> bool:
    """Parse only PE headers: matches architecture, NOT origin/authenticity."""
    try:
        if not _real_regular(path):
            return False
        length = path.stat().st_size
        if not MIN_COMPILER_BYTES <= length <= MAX_COMPILER_BYTES:
            return False
        with path.open("rb") as stream:
            header = stream.read(64)
            if len(header) < 64 or header[:2] != b"MZ":
                return False
            # The upstream bridge rejects Wine's builtin and placeholder DLLs.
            # These are commonly present in Steam's compatdata prefix.
            stream.seek(0)
            first = stream.read(512)
            if b"Wine builtin DLL" in first or b"Wine placeholder DLL" in first:
                return False
            pe_offset = struct.unpack_from("<I", header, 0x3c)[0]
            if pe_offset < 64 or pe_offset > min(length - 26, 1024 * 1024):
                return False
            stream.seek(pe_offset)
            pe = stream.read(26)
            if len(pe) < 26 or pe[:4] != b"PE\x00\x00":
                return False
            # Upstream also requires a sufficiently sized optional header
            # and the DLL image flag; a mere x64 PE marker isn't enough.
            optional_size, flags = struct.unpack_from("<HH", pe, 20)
            return (struct.unpack_from("<H", pe, 4)[0] == 0x8664 and
                    struct.unpack_from("<H", pe, 24)[0] == 0x20b and
                    optional_size >= 112 and bool(flags & 0x2000) and
                    pe_offset + 24 + optional_size <= length)
    except (OSError, ValueError, struct.error):
        return False


def compiler_is_candidate(path: Path) -> bool:
    return path.name.lower() == "d3dcompiler_47.dll" and is_x64_pe(path)


def _game_root(exe: Path) -> Path:
    """For Unreal targets, stop at Steam's steamapps/common/GameName folder."""
    selected = exe.resolve()
    parents = [selected.parent, *selected.parents]
    for folder in parents:
        if folder.parent.name.lower() == "common" and folder.parent.parent.name.lower() == "steamapps":
            return folder
    return selected.parent


def _library_common(exe: Path) -> Path | None:
    for folder in exe.resolve().parents:
        if folder.name.lower() == "common" and folder.parent.name.lower() == "steamapps":
            return folder
    return None


def find_compilers(exe: Path, *, include_library: bool = True) -> list[dict]:
    """Bounded, no-symlink traversal, preferring the selected game folder."""
    game = _game_root(exe)
    roots = [game]
    common = _library_common(exe) if include_library else None
    if common is not None and common != game:
        roots.append(common)

    seen: set[str] = set()
    results: list[dict] = []
    directories = 0
    files = 0
    deadline = time.monotonic() + MAX_SECONDS
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            continue
        for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
            if time.monotonic() >= deadline or directories >= MAX_DIRS or files >= MAX_FILES:
                return results
            directories += 1
            base = Path(current)
            # Ignore caches, downloads and mod dependencies; source game DLLs
            # are easier to inspect when these directories are excluded.
            dirs[:] = [item for item in dirs if not (base / item).is_symlink()
                       and item.casefold() not in {
                           ".git", "shadercache", "compatdata", "node_modules",
                           "pfx", "dosdevices",
                           "amdnr_backup", "amdnr-linux", "download", "downloads"
                       }
                       # Proton distributions bundle Wine-provided DLLs; they
                       # must not be suggested as user-owned Microsoft compilers.
                       and not (base == common and
                                ("proton" in item.casefold() or
                                 "wine" in item.casefold()))]
            for name in names:
                files += 1
                if files >= MAX_FILES:
                    return results
                if name.casefold() != "d3dcompiler_47.dll":
                    continue
                candidate = base / name
                key = str(candidate.absolute())
                if key in seen or not compiler_is_candidate(candidate):
                    continue
                seen.add(key)
                try:
                    size = candidate.stat().st_size
                except OSError:
                    continue
                results.append({
                    "path": str(candidate),
                    "size_bytes": size,
                    "source": "selected_game" if candidate.is_relative_to(game)
                              else "same_steam_library",
                    "verified": "PE x64 header only; publisher and redistributability not established",
                })
                if len(results) >= MAX_CANDIDATES:
                    return results
    return results


def _gpu_devices() -> list[dict]:
    devices = []
    root = Path("/sys/class/drm")
    try:
        entries = sorted(root.glob("card[0-9]*/device"))
    except OSError:
        return devices
    for item in entries[:12]:
        try:
            vendor = (item / "vendor").read_text().strip().lower()
            model = (item / "device").read_text().strip()
        except OSError:
            continue
        devices.append({"vendor": vendor, "device": model,
                        "amd": vendor == "0x1002"})
    return devices


def _proton_candidates(exe: Path) -> list[str]:
    """Installation names only; cannot establish what Steam actually launches."""
    home = Path.home()
    bases = [home / ".steam/root/compatibilitytools.d",
             home / ".local/share/Steam/compatibilitytools.d"]
    common = _library_common(exe)
    if common is not None:
        bases += [common.parent.parent / "compatibilitytools.d",
                  common.parent.parent / "steamapps/common"]
    results: list[str] = []
    for base in bases:
        try:
            if not base.is_dir() or base.is_symlink():
                continue
            for entry in sorted(base.iterdir()):
                if len(results) >= 20:
                    return results
                if not entry.is_dir() or entry.is_symlink():
                    continue
                name = entry.name
                if "proton" in name.lower() or "wine" in name.lower():
                    if name not in results:
                        results.append(name)
        except OSError:
            continue
    return results


def discover(exe: Path, *, include_library: bool = True) -> dict:
    from bridge_deps import host_library_status
    if not exe.is_file() or exe.is_symlink() or exe.suffix.casefold() != ".exe":
        raise ValueError("Select an existing, regular Windows game executable.")
    devices = _gpu_devices()
    candidates = find_compilers(exe, include_library=include_library)
    return {
        "selected_executable": str(exe.resolve()),
        "game_root": str(_game_root(exe)),
        "architecture": os.uname().machine if hasattr(os, "uname") else sys.platform,
        "gpu_devices": devices,
        "amd_gpu_detected": any(device["amd"] for device in devices),
        "kfd_present": Path("/dev/kfd").exists(),
        "render_nodes_present": any(Path("/dev/dri").glob("renderD*")),
        "proton_installations": _proton_candidates(exe),
        "proton_active": "unknown; Steam launch options and actual runtime were not read or modified",
        "compiler_candidates": candidates,
        "compiler_note": "Candidates passed x64 DLL structure and Wine-builtin checks, but publisher is unverified. Wine/Proton compatdata DLLs are not suitable. A native Microsoft DLL from any game you own can be used without editing that game.",
        "host_libraries": host_library_status(),
        "automatic_changes": False,
    }
