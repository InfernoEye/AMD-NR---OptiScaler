"""Independent, bounded third-party Linux game metadata discovery.

Parses official local installation metadata only. No shell execution, prefix
launching, blind filesystem crawling or modifications to third-party apps.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re


MAX_METADATA = 4 * 1024 * 1024
MAX_ENTRIES = 1500


def _config() -> Path:
    return Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config")))


def _data() -> Path:
    return Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share")))


def _read_json(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_METADATA:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        return None


def _candidate(name: object, directory: object, launcher: str) -> dict | None:
    if not isinstance(directory, str) or not directory.strip():
        return None
    path = Path(directory).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        return None
    label = name.strip() if isinstance(name, str) else path.name
    if not 0 < len(label) <= 200:
        label = path.name
    return {"name": label, "folder": str(path.resolve()),
            "store": launcher, "executable": None,
            "note": "Detected via installed-game metadata; choose Windows EXE when needed"}


def heroic_games() -> list[dict]:
    root = _config() / "heroic"
    candidates = [
        (root / "legendaryConfig/legendary/installed.json", "Heroic (Epic)"),
        (root / "gog_store/installed.json", "Heroic (GOG)"),
        (root / "nile/installed.json", "Heroic (Amazon)"),
    ]
    discovered = []
    for path, provider in candidates:
        data = _read_json(path)
        if isinstance(data, dict):
            values = list(data.values())[:MAX_ENTRIES]
        elif isinstance(data, list):
            values = data[:MAX_ENTRIES]
        else:
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            folder = item.get("install_path") or item.get("installPath") or item.get("install_dir")
            name = item.get("title") or item.get("app_name") or item.get("name")
            game = _candidate(name, folder, provider)
            if game:
                discovered.append(game)
    return discovered


def lutris_games() -> list[dict]:
    # Lutris stores per-game local YAML launch snippets. Only accept simple
    # quoted scalar fields; complex interpolation is not interpreted.
    folder = _data() / "lutris/games"
    if not folder.is_dir() or folder.is_symlink():
        return []
    found = []
    try:
        entries = list(folder.glob("*.yml"))[:MAX_ENTRIES]
    except OSError:
        return []
    for item in entries:
        if item.is_symlink() or not item.is_file() or item.stat().st_size > 64 * 1024:
            continue
        try:
            content = item.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scalars = {}
        for line in content.splitlines():
            match = re.fullmatch(r"\s{0,6}(name|exe|working_dir|prefix|game):\s*(.*?)\s*", line)
            if match:
                value = match.group(2).strip().strip('"').strip("'")
                if (value and "$" not in value and "{" not in value and
                        not value.startswith("~") and 0 < len(value) < 1024):
                    scalars.setdefault(match.group(1), value)
        exe = scalars.get("exe")
        working = scalars.get("working_dir")
        path = (Path(working) if working else Path(exe).parent) if exe else (
            Path(working) if working else None)
        if path is None:
            continue
        game = _candidate(scalars.get("name") or item.stem, str(path), "Lutris")
        if game:
            if exe and Path(exe).is_file() and Path(exe).suffix.lower() == ".exe":
                game["executable"] = str(Path(exe).resolve())
            found.append(game)
    return found


def external_games() -> list[dict]:
    seen, games = set(), []
    for item in heroic_games() + lutris_games():
        key = item["folder"].casefold()
        if key in seen:
            continue
        seen.add(key)
        games.append(item)
    return sorted(games, key=lambda x: (x["name"].casefold(), x["store"]))
