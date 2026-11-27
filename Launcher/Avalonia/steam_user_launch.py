"""Read Steam users' launch options and build conservative Proton previews.

Independent, read-only Steam KeyValues parser. Never writes Steam configuration.
"""
from __future__ import annotations

from pathlib import Path
import re

_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\{|\}|//[^\r\n]*', re.MULTILINE)
_ASSIGN = re.compile(r"""(?<!\S)WINEDLLOVERRIDES=(?:"([^"]*)"|'([^']*)'|([^\s]*))""")
_MAX_CONFIG = 16 * 1024 * 1024


def _decode(value: str) -> str:
    return value[1:-1].replace(r'\"', '"').replace(r'\\', '\\')


def _launch_option_from_vdf(text: str, appid: str) -> str | None:
    """Find only the exact apps/<appid>/LaunchOptions value, ignoring other apps."""
    stack: list[str] = []
    pending: str | None = None
    found: list[str] = []
    for token in _TOKEN.finditer(text):
        part = token.group()
        if part.startswith("//"):
            continue
        if part == "{":
            if pending is None:
                return None
            stack.append(pending)
            pending = None
        elif part == "}":
            if pending is not None or not stack:
                return None
            stack.pop()
        else:
            decoded = _decode(part)
            if pending is None:
                pending = decoded
            else:
                normal = [name.casefold() for name in stack]
                if (len(normal) >= 2 and normal[-2:] ==
                        ["apps", appid.casefold()] and
                        pending.casefold() == "launchoptions"):
                    found.append(decoded)
                pending = None
    if pending is not None or stack or len(found) > 1:
        return None
    return found[0] if found else None


def read_launch_options(appid: int, steam_roots: list[Path]) -> dict[str, object]:
    """Search local Steam userdata; do not guess when accounts disagree."""
    options: list[tuple[str, str]] = []
    errors = 0
    profiles = 0
    seen: set[str] = set()
    for root in steam_roots:
        try:
            userdata = root / "userdata"
            folders = sorted(userdata.iterdir()) if userdata.is_dir() else []
        except OSError:
            errors += 1
            continue
        for profile in folders:
            if not profile.name.isdecimal() or profile.name in seen:
                continue
            seen.add(profile.name)
            path = profile / "config/localconfig.vdf"
            try:
                if not path.is_file():
                    continue
                profiles += 1
                if path.stat().st_size > _MAX_CONFIG:
                    errors += 1
                    continue
                content = path.read_text(encoding="utf-8-sig", errors="replace")
                option = _launch_option_from_vdf(content, str(appid))
                if option is not None:
                    options.append((profile.name, option))
            except OSError:
                errors += 1
    nonempty = [(name, value) for name, value in options if value.strip()]
    distinct = {value for _, value in nonempty}
    if len(distinct) > 1:
        return {"status": "multiple_profiles", "existing": None, "profile": None,
                "profiles": len(nonempty)}
    if errors:
        return {"status": "unavailable", "existing": None, "profile": None,
                "profiles": profiles}
    if nonempty:
        return {"status": "found", "existing": nonempty[0][1],
                "profile": nonempty[0][0], "profiles": profiles}
    return {"status": "empty", "existing": "", "profile": None,
            "profiles": profiles}


def _combine_overrides(old: str, dll: str) -> str | None:
    """Replace only the selected DLL override; keep unrelated settings."""
    if not old or any(ch in old for ch in "\r\n$" + chr(96) + "\\"):
        return None
    items = old.split(";")
    result: list[str] = []
    for item in items:
        if not item:
            continue
        if "=" not in item:
            return None
        names, mode = item.split("=", 1)
        if not re.fullmatch(r"[a-zA-Z0-9_,.]+", names) or \
                not re.fullmatch(r"[a-zA-Z0-9,]+", mode):
            return None
        split = names.split(",")
        if dll in (name.casefold() for name in split):
            others = [name for name in split if name.casefold() != dll]
            if others:
                result.append(",".join(others) + "=" + mode)
        else:
            result.append(item)
    result.append(dll + "=n,b")
    return ";".join(result)


def preview_launch_options(existing: str | None, alias: str) -> dict[str, object]:
    """Build a copy-only preview, never interpret or execute launch options."""
    if existing is None:
        return {"status": "unavailable", "preview": None}
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+\.dll", alias, re.IGNORECASE):
        return {"status": "asi_or_unsupported", "preview": None}
    dll = alias[:-4].casefold()
    raw = existing.strip()
    if any(ch in raw for ch in "\x00\r\n"):
        return {"status": "complex_options", "preview": None}
    existing_override = list(_ASSIGN.finditer(raw))
    if len(existing_override) > 1 or \
            ("WINEDLLOVERRIDES=" in raw and not existing_override):
        return {"status": "complex_options", "preview": None}
    if existing_override:
        match = existing_override[0]
        old = next((value for value in match.groups() if value is not None), "")
        merged = _combine_overrides(old, dll)
        if merged is None:
            return {"status": "complex_options", "preview": None}
        return {"status": "merged", "preview":
                raw[:match.start()] + 'WINEDLLOVERRIDES="' + merged + '"' +
                raw[match.end():]}
    override = 'WINEDLLOVERRIDES="' + dll + '=n,b"'
    if not raw:
        return {"status": "added", "preview": override + " %command%"}
    if "%command%" in raw:
        return {"status": "added", "preview": override + " " + raw}
    return {"status": "added", "preview": override + " %command% " + raw}
