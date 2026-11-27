"""Read Steam's cached launch metadata without changing Steam or game files.

Supports v40/v41 appcache/appinfo.vdf and v42 appcache/appinfo shards.
Only Windows launch entries with existing executables may be recommended.
All parsers are size/depth-bounded; failures fall back to ordinary file scanning.
Python standard library only. Binary structure documented by SteamAppInfo.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

MAGIC40 = 0x07564428
MAGIC41 = 0x07564429
MAGIC42 = 0x0756442A
MAX_FILE = 512 * 1024 * 1024
MAX_SHARD = 64 * 1024 * 1024
MAX_STRING = 2 * 1024 * 1024


class MetadataError(ValueError):
    pass


def _u32(data: bytes, pos: int) -> int:
    if pos < 0 or pos + 4 > len(data):
        raise MetadataError("truncated appinfo")
    return struct.unpack_from("<I", data, pos)[0]


def _cstring(data: bytes, pos: int, limit: int = MAX_STRING) -> tuple[str, int]:
    if pos < 0 or pos >= len(data):
        raise MetadataError("truncated string")
    end = data.find(b"\0", pos, min(len(data), pos + limit + 1))
    if end == -1:
        raise MetadataError("unterminated string")
    return data[pos:end].decode("utf-8", "replace"), end + 1


def _key_table(data: bytes, pos: int, count: int, stop: int) -> tuple[list[str], int]:
    if count > 150000 or count < 0:
        raise MetadataError("invalid appinfo string count")
    items = []
    for _ in range(count):
        if pos >= stop:
            raise MetadataError("invalid string table")
        text, pos = _cstring(data, pos)
        if pos > stop:
            raise MetadataError("invalid string table boundary")
        items.append(text)
    return items, pos


def _binary_keys(data: bytes, table: list[str] | None) -> dict:
    """Parse only bounded KeyValues1 types; reject unknown/new types safely."""
    pos = 0
    visited = 0

    def parse(depth: int) -> dict:
        nonlocal pos, visited
        if depth > 30:
            raise MetadataError("appinfo nesting too deep")
        result = {}
        while pos < len(data):
            visited += 1
            if visited > 250000:
                raise MetadataError("too many keyvalues")
            kind = data[pos]
            pos += 1
            if kind == 8:
                return result
            if table is None:
                key, pos = _cstring(data, pos)
            else:
                index = _u32(data, pos)
                pos += 4
                if index >= len(table):
                    raise MetadataError("invalid key index")
                key = table[index]
            key = key.lower()
            if kind == 0:
                value = parse(depth + 1)
            elif kind == 1:
                value, pos = _cstring(data, pos)
            elif kind in (2, 3, 4, 6):
                if pos + 4 > len(data):
                    raise MetadataError("truncated key value")
                value = str(_u32(data, pos)) if kind == 2 else None
                pos += 4
            elif kind in (7, 9, 10):
                if pos + 8 > len(data):
                    raise MetadataError("truncated key value")
                value = None
                pos += 8
            elif kind == 5:
                # Steam's wide string: u16 length followed by UTF-16LE chars.
                if pos + 2 > len(data):
                    raise MetadataError("truncated wide string")
                length = struct.unpack_from("<H", data, pos)[0]
                pos += 2
                if pos + length * 2 > len(data):
                    raise MetadataError("truncated wide string")
                value = None
                pos += length * 2
            else:
                raise MetadataError("unsupported binary key type")
            if value is not None:
                result[key] = value
        raise MetadataError("unterminated keyvalues object")

    return parse(0)


def _read_file(path: Path, limit: int) -> bytes:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
        raise MetadataError("appinfo unavailable or too large")
    return path.read_bytes()


def _legacy_appinfo(path: Path, appid: int) -> dict | None:
    data = _read_file(path, MAX_FILE)
    magic = _u32(data, 0)
    if magic not in (MAGIC40, MAGIC41):
        raise MetadataError("unsupported appinfo format")
    pos = 8
    table = None
    end = len(data)
    if magic == MAGIC41:
        if len(data) < 16:
            raise MetadataError("truncated v41 header")
        offset = struct.unpack_from("<q", data, 8)[0]
        if offset < 20 or offset > len(data) - 4:
            raise MetadataError("invalid v41 string-table offset")
        count = _u32(data, offset)
        table, _ = _key_table(data, offset + 4, count, len(data))
        pos = 16
        end = offset
    while pos + 4 <= end:
        current = _u32(data, pos)
        if current == 0:
            return None
        if pos + 68 > end:
            raise MetadataError("truncated app entry")
        size = _u32(data, pos + 4)
        after = pos + 8 + size
        if size < 60 or after > end:
            raise MetadataError("bad app entry length")
        if current == appid:
            return _binary_keys(data[pos + 68:after], table)
        pos = after
    return None


def _shard(appid: int) -> int:
    # MurmurHash3 32-bit finalizer; the low byte gives the shard index.
    value = appid & 0xFFFFFFFF
    value ^= value >> 16
    value = value * 0x85EBCA6B & 0xFFFFFFFF
    value ^= value >> 13
    value = value * 0xC2B2AE35 & 0xFFFFFFFF
    value ^= value >> 16
    return value & 0xFF


def _sharded_appinfo(directory: Path, appid: int) -> dict | None:
    path = directory / f"appinfo_{_shard(appid):02x}.vdf"
    if not path.is_file():
        return None
    data = _read_file(path, MAX_SHARD)
    if len(data) < 44 or _u32(data, 0) != MAGIC42:
        raise MetadataError("unsupported v42 shard header")
    app_count, index_size, string_count, string_size, data_size = struct.unpack_from(
        "<IIIII", data, 16)
    if app_count > 25000 or string_count > 150000:
        raise MetadataError("oversized shard index")
    index_begin = 44
    index_end = index_begin + index_size
    strings_begin = index_end
    strings_end = strings_begin + string_size
    data_begin = strings_end
    if index_end > len(data) or data_begin + data_size > len(data):
        raise MetadataError("shard sections out of bounds")
    pos = index_begin
    entry = None
    for _ in range(app_count):
        if pos + 16 > index_end:
            raise MetadataError("truncated shard index")
        key, offset, size, summary_size = struct.unpack_from("<IIII", data, pos)
        if summary_size > 8192 or pos + 16 + summary_size > index_end:
            raise MetadataError("invalid shard summary")
        if key == appid:
            entry = (offset, size)
            break
        pos += 16 + summary_size
    if entry is None:
        return None
    table, _ = _key_table(data, strings_begin, string_count, strings_end)
    offset, size = entry
    if size < 21 or offset + size > data_size:
        raise MetadataError("invalid shard data offsets")
    section = data[data_begin + offset + 20:data_begin + offset + size]
    return _binary_keys(section, table)


def read_cached_app(appid: int, roots: list[Path]) -> dict | None:
    """Get matching Steam appinfo; no network, writes, or running Steam required."""
    if not 0 < appid < 2**32:
        return None
    for root in roots:
        cache = root / "appcache"
        try:
            if (cache / "appinfo").is_dir():
                found = _sharded_appinfo(cache / "appinfo", appid)
                if found is not None:
                    return found
            if (cache / "appinfo.vdf").is_file():
                found = _legacy_appinfo(cache / "appinfo.vdf", appid)
                if found is not None:
                    return found
        except (OSError, ValueError, struct.error):
            continue
    return None


def resolve_windows_launch(appinfo: dict | None, folder: Path) -> dict:
    """Explain Steam launch metadata as well as conservatively selecting a target."""
    result = {"source": "steam_cache", "windows_candidates": [],
              "selected": None, "linux_launches": 0, "reason": "metadata_missing",
              "metadata_present": isinstance(appinfo, dict),
              "metadata_sections": [], "launch_entries": 0,
              "windows_declared": 0, "windows_missing": [],
              "windows_invalid": [], "linux_declared": [],
              "windows_optional": 0}
    if not isinstance(appinfo, dict):
        return result
    outer = appinfo.get("appinfo", appinfo)
    if not isinstance(outer, dict):
        result["reason"] = "invalid_appinfo"
        return result
    result["metadata_sections"] = sorted(str(k) for k in outer.keys())[:30]
    common = outer.get("common", {})
    if isinstance(common, dict) and str(common.get("type", "")).lower() not in ("game", "demo", ""):
        result["reason"] = "not_a_game"
        return result
    config = outer.get("config", {})
    if not isinstance(config, dict):
        result["reason"] = "no_launch_config"
        return result
    launches = config.get("launch")
    if not isinstance(launches, dict) or not launches:
        result["reason"] = "no_launch_config"
        return result
    result["launch_entries"] = len(launches)

    normal = []
    all_windows = []
    linux = 0
    root = folder.resolve()
    for launch_id, entry in sorted(launches.items()):
        if not isinstance(entry, dict):
            continue
        flags = entry.get("config", {})
        flags = flags if isinstance(flags, dict) else {}
        platform = str(flags.get("oslist", "")).lower()
        executable = entry.get("executable", "")
        if not isinstance(executable, str) or not executable.strip():
            continue
        relative = executable.replace("\\", "/").strip().strip('"')
        if "linux" in platform:
            linux += 1
            if len(result["linux_declared"]) < 12:
                result["linux_declared"].append(relative)
        if "windows" not in platform:
            continue
        result["windows_declared"] += 1
        if relative.startswith("/") or ":" in relative or "\x00" in relative or \
                any(p in ("", ".", "..") for p in relative.split("/")):
            if len(result["windows_invalid"]) < 12:
                result["windows_invalid"].append(relative)
            continue
        target = root.joinpath(*relative.split("/"))
        try:
            if not target.is_file() or target.is_symlink() or \
                    not target.resolve().is_relative_to(root) or target.suffix.lower() != ".exe":
                if len(result["windows_missing"]) < 12:
                    result["windows_missing"].append(relative)
                continue
        except OSError:
            if len(result["windows_missing"]) < 12:
                result["windows_missing"].append(relative)
            continue
        target_string = str(target)
        if target_string not in all_windows:
            all_windows.append(target_string)
        standard = (not entry.get("type") and not entry.get("description")
                    and not flags.get("betakey") and not flags.get("ownsdlc")
                    and str(flags.get("realm", "steamglobal")).lower() in
                    ("steamglobal", ""))
        if standard and target_string not in normal:
            normal.append(target_string)
        elif not standard:
            result["windows_optional"] += 1
    result["windows_candidates"] = all_windows
    result["linux_launches"] = linux
    result["reason"] = "steam_primary" if len(normal) == 1 else (
        "steam_ambiguous" if len(normal) > 1 else
        "no_installed_windows_launch" if not all_windows else "steam_optional_only")
    if len(normal) == 1:
        result["selected"] = normal[0]
    return result
