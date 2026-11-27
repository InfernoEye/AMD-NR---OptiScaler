#!/usr/bin/env python3
"""Independent, native Linux front end for installing AMDNR into Proton games.

Uses only the Python standard library. The Windows WPF launcher is not imported.
This installs files; it does not make Windows-only neural runtimes Linux-compatible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
import zipfile

ALIASES = ("dxgi.dll", "version.dll", "winmm.dll", "winhttp.dll",
           "wininet.dll", "dbghelp.dll", "d3d12.dll", "OptiScaler.asi")
STATE_NAME = ".amdnr-linux-install.json"
BACKUP_NAME = "AMDNR_backup"
VDF_FIELD = re.compile(r'"([^"]+)"\s+"((?:\\.|[^"\\])*)"')


def vdf_value(text: str, key: str) -> str | None:
    for found_key, value in VDF_FIELD.findall(text):
        if found_key.lower() == key.lower():
            return value.replace(r"\\", "\\").replace(r"\"", '"')
    return None


def steam_roots() -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".steam/root",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    ]
    roots: list[Path] = []
    for path in candidates:
        try:
            resolved = path.resolve()
            if (resolved / "steamapps").is_dir() and resolved not in roots:
                roots.append(resolved)
        except OSError:
            pass
    return roots


def steam_libraries() -> list[Path]:
    result: list[Path] = []
    for root in steam_roots():
        library_file = root / "steamapps/libraryfolders.vdf"
        paths = [root]
        try:
            content = library_file.read_text(encoding="utf-8-sig", errors="replace")
            # Only 'path' values identify library folders in the modern VDF format.
            paths.extend(Path(p.replace(r"\\", "\\")) for k, p in VDF_FIELD.findall(content)
                         if k.lower() == "path")
        except OSError:
            pass
        for path in paths:
            try:
                resolved = path.expanduser().resolve()
                if (resolved / "steamapps").is_dir() and resolved not in result:
                    result.append(resolved)
            except OSError:
                continue
    return result


def steam_games() -> list[tuple[str, Path]]:
    games: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for library in steam_libraries():
        for manifest in sorted((library / "steamapps").glob("appmanifest_*.acf")):
            try:
                text = manifest.read_text(encoding="utf-8-sig", errors="replace")
                name, directory = vdf_value(text, "name"), vdf_value(text, "installdir")
                if not name or not directory:
                    continue
                # A manifest must never be allowed to point outside steamapps/common.
                if directory in (".", "..") or not re.fullmatch(r"[^/\\:]+", directory):
                    continue
                candidate = (library / "steamapps/common" / directory).resolve()
                common = (library / "steamapps/common").resolve()
                if not candidate.is_relative_to(common) or not candidate.is_dir():
                    continue
                if candidate not in seen:
                    games.append((name, candidate))
                    seen.add(candidate)
            except (OSError, ValueError):
                continue
    return sorted(games, key=lambda g: g[0].casefold())


def steam_game_details() -> list[dict[str, str | None]]:
    """Find locally cached Steam artwork without downloading or guessing game IDs."""
    details: list[dict[str, str | None]] = []
    roots = steam_roots()
    for name, folder in steam_games():
        appid = None
        # The authoritative app ID is in a manifest belonging to this library.
        manifest_dir = folder.parent.parent
        for manifest in manifest_dir.glob("appmanifest_*.acf"):
            try:
                content = manifest.read_text(encoding="utf-8-sig", errors="replace")
                if vdf_value(content, "installdir") == folder.name:
                    appid = vdf_value(content, "appid") or manifest.stem.removeprefix("appmanifest_")
                    break
            except OSError:
                continue
        artwork = None
        if appid and appid.isdecimal():
            for root in roots:
                cache = root / "appcache/librarycache"
                for art in (
                    cache / f"{appid}_library_600x900.jpg",
                    cache / appid / "library_600x900.jpg",
                    cache / f"{appid}_header.jpg",
                    cache / appid / "header.jpg",
                ):
                    if art.is_file():
                        artwork = str(art)
                        break
                if artwork:
                    break
        details.append({"name": name, "folder": str(folder), "artwork": artwork})
    return details


def guess_executable(directory: Path) -> Path | None:
    options: list[Path] = []
    try:
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix.lower() != ".exe":
                continue
            relative = path.relative_to(directory)
            if len(relative.parts) > 6:
                continue
            bad = ("unins", "setup", "crash", "redist", "vcredist", "unitycrash",
                   "easyanticheat", "benchmark", "updater")
            if any(word in path.name.lower() for word in bad):
                continue
            options.append(path)
    except OSError:
        return None
    return min(options, key=lambda p: (len(p.relative_to(directory).parts),
                                      "shipping" not in p.name.lower(),
                                      len(p.name))) if options else None


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _safe_member(name: str) -> bool:
    # ZIP entries always use / regardless of the host filesystem.
    path = PurePosixPath(name.replace("\\", "/"))
    return bool(name) and not path.is_absolute() and ".." not in path.parts \
        and not any(":" in part for part in path.parts) and "\0" not in name


def _package_files(archive: Path, destination: Path) -> list[Path]:
    with zipfile.ZipFile(archive) as source:
        entries = [item for item in source.infolist() if not item.is_dir()]
        for item in entries:
            if not _safe_member(item.filename):
                raise ValueError(f"Unsafe archive path: {item.filename}")
            # Refuse symlinks, which can escape the extraction root.
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"Symlink in archive: {item.filename}")
        matches = [item for item in entries
                   if PurePosixPath(item.filename).name.lower() == "optiscaler.dll"]
        if len(matches) != 1:
            raise ValueError("ZIP must contain exactly one OptiScaler.dll")
        prefix = PurePosixPath(matches[0].filename).parent
        extracted: list[Path] = []
        total_size = 0
        for item in entries:
            member = PurePosixPath(item.filename)
            if not member.is_relative_to(prefix):
                continue
            relative = member.relative_to(prefix)
            if not relative.parts or relative.name in (STATE_NAME,):
                continue
            if relative.parts[0].lower() == BACKUP_NAME.lower():
                continue
            # Only install game payloads; do not copy executables or shell scripts.
            if relative.suffix.lower() not in {
                ".dll", ".asi", ".ini", ".json", ".dat", ".bin", ".pak",
                ".cso", ".fx", ".hlsl", ".slang", ".cfg", ".txt"
            }:
                continue
            total_size += item.file_size
            if total_size > 2 * 1024 * 1024 * 1024:
                raise ValueError("Archive payload exceeds 2 GiB limit")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(item) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(target)
        return extracted


def _check_destination(target: Path, root: Path) -> None:
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Destination escapes game directory: {target}")


def install(archive: Path, executable: Path, alias: str) -> str:
    if alias not in ALIASES:
        raise ValueError(f"Unsupported DLL alias: {alias}")
    if not executable.is_file() or executable.suffix.lower() != ".exe":
        raise ValueError("Choose the game's actual Windows .exe file")
    root = executable.resolve().parent
    state_file = root / STATE_NAME
    if state_file.exists():
        raise ValueError("An installation is already recorded here; uninstall it first")
    with tempfile.TemporaryDirectory(prefix="amdnr-linux-") as work:
        staging = Path(work)
        staged = _package_files(archive, staging)
        replacements = []
        for source in staged:
            relative = source.relative_to(staging)
            if relative.name.lower() == "optiscaler.dll":
                relative = relative.with_name(alias)
            target = root / relative
            _check_destination(target, root)
            replacements.append((source, target, str(relative)))
        if not replacements:
            raise ValueError("No compatible files found in archive")
        if len({str(t).casefold() for _, t, _ in replacements}) != len(replacements):
            raise ValueError("Package contains colliding filenames")
        backup = root / BACKUP_NAME / "linux-launcher"
        if backup.exists():
            raise ValueError(f"Existing backup directory: {backup}; resolve it first")
        records = []
        written: list[Path] = []
        moved: list[tuple[Path, Path]] = []
        try:
            for source, target, relative in replacements:
                target.parent.mkdir(parents=True, exist_ok=True)
                previous = target.exists()
                backup_target = backup / relative
                if previous:
                    if not target.is_file() or target.is_symlink():
                        raise ValueError(f"Refusing non-regular destination: {target}")
                    backup_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(backup_target))
                    moved.append((backup_target, target))
                shutil.copy2(source, target)
                written.append(target)
                records.append({"path": relative, "sha256": _digest(target),
                                "backed_up": previous})
            state_file.write_text(json.dumps({"format": 1, "alias": alias,
                                             "files": records}, indent=2) + "\n",
                                  encoding="utf-8")
        except Exception:
            for target in reversed(written):
                target.unlink(missing_ok=True)
            for original, target in reversed(moved):
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(original), str(target))
            if backup.exists():
                shutil.rmtree(backup)
            raise
    if alias.lower().endswith(".asi"):
        return "ASI plugins require a compatible ASI loader in the game prefix (no Wine DLL override)."
    override = alias.rsplit(".", 1)[0].lower()
    return f'WINEDLLOVERRIDES="{override}=n,b" %command%'


def uninstall(executable: Path) -> tuple[int, list[str]]:
    root = executable.resolve().parent
    state_file = root / STATE_NAME
    state = json.loads(state_file.read_text(encoding="utf-8"))
    if state.get("format") != 1 or not isinstance(state.get("files"), list):
        raise ValueError("Unrecognized installation record")
    backup = root / BACKUP_NAME / "linux-launcher"
    warnings: list[str] = []
    restored = 0
    remaining = []
    for entry in state["files"]:
        relative = entry["path"]
        if not _safe_member(relative):
            raise ValueError("Unsafe path in installation record")
        target = root / relative
        _check_destination(target, root)
        old_file = backup / relative
        _check_destination(old_file, backup)
        if target.exists() and (not target.is_file() or target.is_symlink() or
                                _digest(target) != entry["sha256"]):
            warnings.append(f"Modified file kept: {target}")
            remaining.append(entry)
            continue
        if entry["backed_up"] and not old_file.is_file():
            warnings.append(f"Missing backup; kept: {target}")
            remaining.append(entry)
            continue
        target.unlink(missing_ok=True)
        if entry["backed_up"]:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_file), str(target))
        restored += 1
    if remaining:
        state["files"] = remaining
        state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    else:
        state_file.unlink()
        if backup.exists():
            shutil.rmtree(backup)
    return restored, warnings


def gui() -> None:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError as exc:
        raise RuntimeError("Tkinter unavailable. Install python3-tk or use --list/--install") from exc
    window = tk.Tk()
    window.title("AMDNR Linux Launcher (Proton)")
    window.geometry("760x510")
    box = ttk.Frame(window, padding=16)
    box.pack(fill="both", expand=True)
    ttk.Label(box, text="AMDNR for Steam / Proton", font=("Sans", 17, "bold")).pack(anchor="w")
    ttk.Label(box, text="Choose a Windows game .exe; this manages files only, not GPU runtime support.",
              wraplength=700).pack(anchor="w", pady=(4, 12))
    game = tk.StringVar()
    package = tk.StringVar()
    alias = tk.StringVar(value="dxgi.dll")
    options = ttk.Frame(box)
    options.pack(fill="x")
    ttk.Label(options, text="Game executable").grid(row=0, column=0, sticky="w")
    ttk.Entry(options, textvariable=game).grid(row=1, column=0, sticky="ew")
    ttk.Button(options, text="Browse", command=lambda: game.set(
        filedialog.askopenfilename(title="Select game EXE", filetypes=[("Windows executables", "*.exe")])
        or game.get())).grid(row=1, column=1, padx=6)
    ttk.Label(options, text="AMDNR release ZIP").grid(row=2, column=0, sticky="w", pady=(9, 0))
    ttk.Entry(options, textvariable=package).grid(row=3, column=0, sticky="ew")
    ttk.Button(options, text="Browse", command=lambda: package.set(
        filedialog.askopenfilename(title="Select AMDNR ZIP", filetypes=[("ZIP archive", "*.zip")])
        or package.get())).grid(row=3, column=1, padx=6)
    ttk.Label(options, text="Proxy DLL name").grid(row=4, column=0, sticky="w", pady=(9, 0))
    ttk.Combobox(options, textvariable=alias, values=ALIASES, state="readonly").grid(
        row=5, column=0, sticky="w")
    options.columnconfigure(0, weight=1)
    result = tk.StringVar(value="Installed games are listed below. Double-click one to select its likely EXE.")
    ttk.Label(box, textvariable=result, wraplength=700).pack(anchor="w", pady=(12, 6))

    def action(which: str) -> None:
        try:
            exe = Path(game.get()).expanduser()
            if which == "install":
                launch_options = install(Path(package.get()).expanduser(), exe, alias.get())
                result.set(f"Installed. Set Steam launch options to: {launch_options}")
                messagebox.showinfo("Steam launch options", launch_options)
            else:
                count, notes = uninstall(exe)
                result.set(f"Restored/removed {count} files. " + "; ".join(notes))
                if notes:
                    messagebox.showwarning("Files kept", "\n".join(notes))
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            messagebox.showerror("AMDNR Linux Launcher", str(exc))
    buttons = ttk.Frame(box)
    buttons.pack(anchor="w", pady=(4, 12))
    ttk.Button(buttons, text="Install", command=lambda: action("install")).pack(side="left")
    ttk.Button(buttons, text="Uninstall / restore",
               command=lambda: action("uninstall")).pack(side="left", padx=8)
    ttk.Label(box, text="Detected Steam games").pack(anchor="w")
    games = steam_games()
    listing = tk.Listbox(box, height=9)
    listing.pack(fill="both", expand=True)
    for name, folder in games:
        listing.insert("end", f"{name} — {folder}")

    def select_game(_event: object) -> None:
        selection = listing.curselection()
        if selection:
            found = guess_executable(games[selection[0]][1])
            if found:
                game.set(str(found))
            else:
                result.set("No game EXE found automatically; use Browse.")
    listing.bind("<Double-Button-1>", select_game)
    window.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List detected Steam games")
    parser.add_argument("--list-json", action="store_true", help="List games and cached artwork as JSON")
    parser.add_argument("--install", type=Path, metavar="ZIP", help="Install an AMDNR release ZIP")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall and restore backups")
    parser.add_argument("--exe", type=Path, help="Full path to Windows game executable")
    parser.add_argument("--alias", default="dxgi.dll", choices=ALIASES)
    args = parser.parse_args()
    if args.install or args.uninstall:
        if not args.exe:
            parser.error("--install/--uninstall requires --exe")
        try:
            if args.install:
                print("Steam launch options:", install(args.install, args.exe, args.alias))
            else:
                count, warnings = uninstall(args.exe)
                print(f"Restored/removed {count} files")
                for warning in warnings:
                    print("WARNING:", warning, file=sys.stderr)
                if warnings:
                    return 2
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.list_json:
        print(json.dumps(steam_game_details(), ensure_ascii=False))
    elif args.list:
        for name, folder in steam_games():
            print(f"{name}\t{folder}")
    else:
        gui()
    return 0


if __name__ == "__main__":
    sys.exit(main())
