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


# Bridge launch composition is separate from the legacy Windows proxy merger.
# Keep unrelated Steam options byte-for-byte, and only remove DLL overrides
# attributable to this launcher's archived installation records.
_OLD_OVERRIDE_ALIASES = frozenset({
    "dxgi", "version", "winmm", "winhttp", "wininet", "dbghelp", "d3d12",
})
_BRIDGE_CONFLICTS = (
    "PROTON_USE_WINED3D=", "PROTON_NO_D3D12=", "PROTON_DISABLE_D3D12=",
)


def preview_bridge_launch(existing: str | None, wrapper: str,
                          managed_aliases: tuple[str, ...] = ()) -> dict[str, object]:
    """Build a Steam copy-only bridge preview and an explicit cleanup summary.

    No shell evaluation; ambiguous syntax is never rewritten. The saved Steam
    text is never changed by this function.
    """
    import shlex
    if existing is None:
        return {"compose_status": "unavailable", "preview": None,
                "removed": [], "kept": [], "review": [
                    "Steam launch options could not be read; paste the current text for review."]}
    current = existing.strip()
    if not wrapper.startswith("/") or any(ch in wrapper for ch in "\x00\r\n"):
        raise ValueError("Bridge wrapper path must be an absolute regular path.")
    quoted_wrapper = shlex.quote(wrapper)
    # Steam's command processor is shell-like. Prefer a double quoted path
    # because the upstream preview already uses it and paths can contain spaces.
    quoted_wrapper = '"' + wrapper.replace("\\", "\\\\").replace('"', '\\"') + '"'
    removed: list[str] = []
    kept: list[str] = []
    review: list[str] = []
    old_aliases = {name.casefold().removesuffix(".dll") for name in managed_aliases}
    old_aliases &= _OLD_OVERRIDE_ALIASES

    if any(ch in current for ch in "\x00\r\n"):
        return {"compose_status": "needs_review", "preview": None, "removed": [],
                "kept": [], "review": ["Multiline launch options need manual review."]}

    if "%command%" not in current:
        if current and any(ch in current for ch in "$" + chr(96) + "|;&<>"):
            return {"compose_status": "needs_review", "preview": None,
                    "removed": [], "kept": [], "review": [
                        "Complex launch options without %command%; cannot insert bridge safely."]}
        # Plain game arguments can follow the placeholder, but an existing
        # executable/wrapper without %command% is ambiguous.
        if current and (current.startswith("/") or current.startswith("./")):
            return {"compose_status": "needs_review", "preview": None,
                    "removed": [], "kept": [], "review": [
                        "Existing executable/wrapper lacks %command%; review manually."]}
        current = "%command% " + current if current else "%command%"
        kept.append("Existing game arguments" if existing.strip() else "Steam's %command% placeholder")

    if current.count("%command%") != 1:
        return {"compose_status": "needs_review", "preview": None,
                "removed": [], "kept": [], "review": [
                    "Multiple %command% placeholders; review manually."]}
    if any(token in current for token in ("&&", "||", "; ", "| ", "$(", chr(96), "\n")):
        return {"compose_status": "needs_review", "preview": None,
                "removed": [], "kept": [], "review": [
                    "Shell chaining or substitution makes automatic merging ambiguous."]}
    if "amdnr-linux/run.sh" in current or "AMDNR-Linux" in current:
        return {"compose_status": "needs_review", "preview": None,
                "removed": [], "kept": [], "review": [
                    "An older bridge wrapper is already in Steam options; remove it before replacing."]}

    matches = list(_ASSIGN.finditer(current))
    if len(matches) > 1 or ("WINEDLLOVERRIDES=" in current and not matches):
        return {"compose_status": "needs_review", "preview": None,
                "removed": [], "kept": [], "review": [
                    "Several or unusual WINEDLLOVERRIDES entries need manual review."]}
    if matches:
        item = matches[0]
        old = next((value for value in item.groups() if value is not None), "")
        # Preserve override groups and modes for DLLs we have not tracked.
        remaining = []
        for pair in old.split(";"):
            if not pair or "=" not in pair:
                return {"compose_status": "needs_review", "preview": None,
                        "removed": [], "kept": [], "review": ["Invalid DLL override syntax."]}
            aliases, mode = pair.split("=", 1)
            if (not re.fullmatch(r"[a-zA-Z0-9_,.]+", aliases) or
                    not re.fullmatch(r"[a-zA-Z0-9,]+", mode)):
                return {"compose_status": "needs_review", "preview": None,
                        "removed": [], "kept": [], "review": ["Complex DLL override syntax."]}
            names = aliases.split(",")
            old_names = [name for name in names if name.casefold() in old_aliases]
            for name in old_names:
                removed.append("Old managed DLL override: " + name + "=" + mode)
            remaining_names = [name for name in names if name.casefold() not in old_aliases]
            if remaining_names:
                remaining.append(",".join(remaining_names) + "=" + mode)
                kept.append("Other DLL override: " + ",".join(remaining_names) + "=" + mode)
                if any(name.casefold() in _OLD_OVERRIDE_ALIASES for name in remaining_names):
                    review.append("An untracked DLL override remains; verify it is needed with the bridge.")
        replacement = ('WINEDLLOVERRIDES="' + ";".join(remaining) + '"') if remaining else ""
        current = (current[:item.start()] + replacement + current[item.end():]).strip()
        current = re.sub(r" {2,}", " ", current)
    for variable in _BRIDGE_CONFLICTS:
        if variable in current:
            review.append(variable[:-1] + " may disable the required D3D12 path; review in Steam.")
    if not removed:
        kept.append("Existing Steam launch arguments and environment settings")
    proposal = current.replace("%command%", quoted_wrapper + " %command%", 1)
    return {"compose_status": "review" if review else "ready",
            "preview": proposal, "removed": removed, "kept": kept,
            "review": review}
