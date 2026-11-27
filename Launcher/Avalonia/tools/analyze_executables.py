#!/usr/bin/env python3
"""Read-only investigation of game executable layouts (Linux, Python 3.10+).

No installation, network requests, or game-name rules. All reported paths are
relative to the game directory. Never follows symlinks.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import stat
import struct
import sys


def load_backend():
    source = Path(__file__).resolve().parents[1] / "amdnr_launcher.py"
    spec = importlib.util.spec_from_file_location("amdnr_launcher", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sniff_binary(path: Path) -> str:
    """Distinguish PE executables/DLLs, ELF binaries and launch scripts."""
    try:
        with path.open("rb") as stream:
            header = stream.read(64)
            if header.startswith(b"\x7fELF"):
                return "ELF"
            if header.startswith(b"#!"):
                return "script"
            if header.startswith(b"MZ") and len(header) >= 64:
                offset = struct.unpack_from("<I", header, 0x3c)[0]
                if 64 <= offset <= 1024 * 1024:
                    stream.seek(offset)
                    pe = stream.read(24)
                    if len(pe) >= 24 and pe[:4] == b"PE\x00\x00":
                        flags = struct.unpack_from("<H", pe, 22)[0]
                        return "PE DLL" if flags & 0x2000 else "PE executable"
                return "MZ (unverified)"
    except OSError:
        return "unreadable"
    return "unknown"


def inspect_game(directory: Path, backend=None, max_files: int = 40000,
                 max_depth: int = 20, examples: int = 24) -> dict:
    """Inspect one game without modifying anything; return only relative paths."""
    if backend is None:
        backend = load_backend()
    if not directory.is_dir():
        return {"error": "directory missing", "game": directory.name}

    root = directory.resolve()
    scan = backend.executable_scan(root)
    detected = {str(Path(x["path"]).relative_to(root)) for x in scan["candidates"]}
    suspected = []
    suffixes = Counter()
    folder_counts = Counter()
    signatures = Counter()
    warnings = []
    count = 0
    symlinks = 0
    stack = [(root, 0)]

    while stack and count < max_files:
        folder, depth = stack.pop()
        try:
            with os.scandir(folder) as listing:
                children = sorted(list(listing), key=lambda x: x.name.casefold())
        except OSError:
            warnings.append("unreadable folder: " + str(folder.relative_to(root)))
            continue
        for item in children:
            if count >= max_files:
                break
            try:
                if item.is_symlink():
                    symlinks += 1
                    continue
                if item.is_dir(follow_symlinks=False):
                    if depth < max_depth:
                        stack.append((Path(item.path), depth + 1))
                    else:
                        warnings.append("depth limit: " + str(Path(item.path).relative_to(root)))
                    continue
                if not item.is_file(follow_symlinks=False):
                    continue
                count += 1
                path = Path(item.path)
                relative = path.relative_to(root)
                suffix = path.suffix.casefold() or "(none)"
                suffixes[suffix] += 1
                folder_counts[str(relative.parent)] += 1
                # Check possible executables, not every tiny asset or shader.
                st = item.stat(follow_symlinks=False)
                executable_flag = bool(st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
                maybe_binary = (
                    suffix in {".exe", ".dll", ".com", ".bin", ".x86", ".x86_64",
                               ".appimage", ".sh", ".bat", ".cmd", ".run", ".so"}
                    or (depth <= 5 and (executable_flag or suffix == "(none)"))
                    or (depth <= 2 and st.st_size >= 32 * 1024 and st.st_size <= 2 * 1024 * 1024 * 1024)
                )
                if not maybe_binary:
                    continue
                signature = sniff_binary(path)
                if signature == "unknown" and not executable_flag and suffix not in {".exe", ".bin", ".com"}:
                    continue
                signatures[signature] += 1
                suspicious_mismatch = (
                    signature in {"PE executable", "MZ (unverified)"} and
                    suffix != ".exe"
                )
                if signature in {"PE executable", "PE DLL", "MZ (unverified)", "ELF", "script"} or executable_flag or suffix == ".exe":
                    suspected.append({
                        "relative_path": str(relative),
                        "depth": len(relative.parts) - 1,
                        "extension": suffix,
                        "signature": signature,
                        "executable_bit": executable_flag,
                        "recognized_by_launcher": str(relative) in detected,
                        "possible_misnamed_pe": suspicious_mismatch,
                    })
            except OSError:
                warnings.append("unreadable file: " + str(Path(item.path).relative_to(root)))

    # Show potential false negatives first, then standard launchers. Never make
    # installation decisions from this report alone.
    suspected.sort(key=lambda x: (
        not x["possible_misnamed_pe"],
        x["recognized_by_launcher"],
        x["depth"],
        x["relative_path"].casefold(),
    ))
    if count >= max_files:
        warnings.append("file scan limit reached; report is incomplete")
    return {
        "game": directory.name,
        "launcher_reason": scan["reason"],
        "launcher_candidates": len(scan["candidates"]),
        "launcher_auto_selected": any(x["auto_select"] for x in scan["candidates"]),
        "launcher_partial_scan": scan["partial"],
        "files_examined": count,
        "symlinks_skipped": symlinks,
        "extension_counts": dict(suffixes.most_common(12)),
        "signature_counts": dict(signatures.most_common()),
        "common_directories": dict(folder_counts.most_common(8)),
        "potential_executable_count": len(suspected),
        "potential_executables": suspected[:examples],
        "warnings": warnings[:12],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--game", type=Path, action="append", metavar="DIRECTORY",
                      help="Inspect a game directory (repeatable)")
    mode.add_argument("--all", action="store_true",
                      help="Inspect every detected Steam entry")
    mode.add_argument("--missing-only", action="store_true",
                      help="Inspect games without an auto-selected or saved Windows EXE (default)")
    parser.add_argument("--examples", type=int, default=24,
                        help="Maximum possible executable paths per game (1–100)")
    parser.add_argument("--max-files", type=int, default=40000,
                        help="File limit per game (100–100000)")
    args = parser.parse_args(argv)
    if not 1 <= args.examples <= 100 or not 100 <= args.max_files <= 100000:
        parser.error("limits are outside supported ranges")

    backend = load_backend()
    games = [(path.name, path) for path in args.game] if args.game else backend.steam_games()
    reports = []
    for name, folder in games:
        # Keep names as returned by Steam, not derived from arbitrary game lists.
        if not args.game and not args.all:
            scan = backend.executable_scan(folder)
            if any(x["auto_select"] for x in scan["candidates"]) or backend.saved_executable(folder):
                continue
        report = inspect_game(folder, backend, max_files=args.max_files,
                              examples=args.examples)
        report["game"] = name
        reports.append(report)
    result = {
        "format": 1,
        "scope": "all" if args.all else "selected" if args.game else "unresolved",
        "read_only": True,
        "note": "Paths below are game-relative. This is diagnostic information, not a safe installation recommendation.",
        "games_examined": len(reports),
        "reports": reports,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
