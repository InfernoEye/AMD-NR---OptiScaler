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
import urllib.request
from concurrent.futures import ThreadPoolExecutor

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


def _artwork_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "amdnr" / "artwork"


def _artwork_key(game_folder: Path) -> str:
    return hashlib.sha256(str(game_folder.resolve()).encode("utf-8")).hexdigest()


def _is_image(data: bytes) -> bool:
    return data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n")


def _manual_artwork(game_folder: Path) -> Path | None:
    base = _artwork_dir() / _artwork_key(game_folder)
    for extension in (".png", ".jpg"):
        art = base.with_suffix(extension)
        try:
            if art.is_file() and _is_image(art.read_bytes()[:8]):
                return art
        except OSError:
            pass
    return None


def set_artwork(game_folder: Path, image: Path) -> str:
    """Save a per-game manual cover without modifying the game or Steam files."""
    if not game_folder.is_dir():
        raise ValueError(f"Game directory not found: {game_folder}")
    if not image.is_file():
        raise ValueError(f"Artwork not found: {image}")
    if image.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Artwork is larger than 8 MiB")
    payload = image.read_bytes()
    if not _is_image(payload):
        raise ValueError("Only JPEG and PNG artwork is supported")
    extension = ".png" if payload.startswith(b"\x89PNG") else ".jpg"
    base = _artwork_dir() / _artwork_key(game_folder)
    base.parent.mkdir(parents=True, exist_ok=True)
    target = base.with_suffix(extension)
    with tempfile.NamedTemporaryFile(dir=base.parent, prefix=".art-", delete=False) as out:
        temporary = Path(out.name)
        out.write(payload)
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    base.with_suffix(".jpg" if extension == ".png" else ".png").unlink(missing_ok=True)
    return str(target)


def _cached_artwork(appid: str, roots: list[Path]) -> Path | None:
    """Steam's official cache and user-selected custom artwork across accounts."""
    for root in roots:
        # A custom cover set in Steam should win over the official capsule.
        try:
            users = (root / "userdata").iterdir()
            for user in users:
                grid = user / "config/grid"
                for name in (f"{appid}p.png", f"{appid}p.jpg",
                             f"{appid}.png", f"{appid}.jpg",
                             f"{appid}_hero.png", f"{appid}_hero.jpg"):
                    candidate = grid / name
                    if candidate.is_file():
                        return candidate
        except OSError:
            pass

    # Extra Steam libraries may each contain a local appcache with art.
    candidates = list(dict.fromkeys([*roots, *steam_libraries()]))
    for root in candidates:
        cache = root / "appcache/librarycache"
        paths = (
            cache / appid / "library_600x900.jpg",
            cache / appid / "library_600x900.png",
            cache / f"{appid}_library_600x900.jpg",
            cache / f"{appid}_library_600x900.png",
            cache / appid / "header.jpg",
            cache / f"{appid}_header.jpg",
            cache / appid / "library_hero.jpg",
            cache / f"{appid}_library_hero.jpg",
            cache / f"{appid}_logo.png",
            cache / appid / "logo.png",
        )
        for path in paths:
            try:
                if path.is_file() and _is_image(path.read_bytes()[:8]):
                    return path
            except OSError:
                continue
        # New Steam clients put artwork under <app-id>/<asset-hash>/image.jpg.
        # Search only this app's folder (never the entire library cache).
        folder = cache / appid
        if folder.is_dir():
            patterns = (
                "library_600x900*.jpg", "library_600x900*.png",
                "library_600x900_2x.jpg", "header*.jpg", "header*.png",
                "library_hero*.jpg", "library_hero*.png", "logo*.png",
                "*/library_600x900*.jpg", "*/library_600x900*.png",
                "*/header*.jpg", "*/header*.png", "*/library_hero*.jpg",
            )
            for pattern in patterns:
                for path in sorted(folder.glob(pattern)):
                    try:
                        if path.is_file() and _is_image(path.read_bytes()[:8]):
                            return path
                    except OSError:
                        continue
    return None


def _download_artwork(appid: str, destination: Path) -> Path | None:
    """Bounded download from known Steam hosts, no third-party art services."""
    urls = [
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg",
    ]

    # Store metadata can point at content-hashed artwork for newer titles.
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={appid}&filters=basic"
        req = urllib.request.Request(url, headers={"User-Agent": "AMDNR-Linux-Launcher/1.0"})
        with urllib.request.urlopen(req, timeout=4) as response:
            metadata = response.read(512 * 1024)
        data = json.loads(metadata)
        details = data.get(appid, {}).get("data", {})
        # Read every image URL supplied by Steam rather than inventing game-specific
        # filenames; releases on the newer CDN use content-hashed asset URLs.
        from urllib.parse import urlparse
        if isinstance(details, dict):
            for field in ("capsule_imagev5", "capsule_image", "header_image"):
                candidate = details.get(field)
                if not isinstance(candidate, str):
                    continue
                parsed = urlparse(candidate)
                if parsed.scheme == "https" and parsed.hostname in {
                    "shared.fastly.steamstatic.com", "shared.steamstatic.com",
                    "shared.cloudflare.steamstatic.com",
                    "cdn.cloudflare.steamstatic.com", "cdn.akamai.steamstatic.com",
                    "shared.akamai.steamstatic.com",
                } and parsed.username is None and parsed.password is None:
                    urls.insert(0, candidate)
    except (OSError, ValueError, KeyError, TypeError):
        pass

    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AMDNR-Linux-Launcher/1.0"})
            with urllib.request.urlopen(req, timeout=4) as response:
                if response.status != 200:
                    continue
                payload = response.read(4 * 1024 * 1024 + 1)
            if len(payload) > 4 * 1024 * 1024 or len(payload) < 64 or not _is_image(payload):
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            extension = ".png" if payload.startswith(b"\x89PNG") else ".jpg"
            target = destination.with_suffix(extension)
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".art-", delete=False
            ) as output:
                temporary = Path(output.name)
                output.write(payload)
            try:
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            return target
        except (OSError, ValueError):
            continue
    return None


def _steam_artwork(appid: str, roots: list[Path], download: bool = False,
                   game_folder: Path | None = None) -> str | None:
    """Manual override > Steam custom grids > Steam cache > downloaded official art."""
    if game_folder is not None:
        manual = _manual_artwork(game_folder)
        if manual is not None:
            return str(manual)
    if not appid.isdecimal():
        return None

    existing = _cached_artwork(appid, roots)
    if existing is not None:
        return str(existing)

    cache_home = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    saved = cache_home / "amdnr/steam-artwork" / f"{appid}_library_600x900.jpg"
    for path in (saved, saved.with_suffix(".png")):
        try:
            if path.is_file() and _is_image(path.read_bytes()[:8]):
                return str(path)
        except OSError:
            continue

    if not download or os.environ.get("AMDNR_NO_ARTWORK_DOWNLOAD") == "1":
        return None
    downloaded = _download_artwork(appid, saved)
    return str(downloaded) if downloaded is not None else None


def _custom_games_path() -> Path:
    """User-owned preferences; never writes inside any installed game folder."""
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / "amdnr" / "custom-games.json"


def custom_games() -> list[dict[str, object]]:
    """Load remembered non-Steam game directories, including temporarily missing drives."""
    path = _custom_games_path()
    if not path.exists():
        return []
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("Custom game registry is too large")
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("format") != 1 or \
                not isinstance(state.get("games"), list):
            raise ValueError("Invalid custom game registry")
        result = []
        seen = set()
        for item in state["games"][:500]:
            if not isinstance(item, dict):
                continue
            name, folder = item.get("name"), item.get("folder")
            if not isinstance(name, str) or not name.strip() or len(name) > 120 or \
                    not isinstance(folder, str) or not Path(folder).is_absolute():
                continue
            if folder in seen:
                continue
            seen.add(folder)
            result.append({"name": name, "folder": folder, "artwork":
                           str(_manual_artwork(Path(folder))) if
                           _manual_artwork(Path(folder)) else None,
                           "exists": Path(folder).is_dir()})
        return result
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Unable to read custom game registry: {exc}") from exc


def _save_custom_games(items: list[dict[str, object]]) -> None:
    path = _custom_games_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".custom-games-", delete=False) as out:
        temporary = Path(out.name)
        json.dump({"format": 1, "games": [
            {"name": item["name"], "folder": item["folder"]} for item in items
        ]}, out, ensure_ascii=False, indent=2)
        out.write("\n")
    try:
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def add_custom_game(directory: Path, name: str | None = None) -> dict[str, object]:
    if not directory.is_dir():
        raise ValueError("Choose an existing game folder")
    if directory.is_symlink():
        raise ValueError("Choose a game folder rather than a symbolic link")
    folder = str(directory.resolve())
    display = (name or directory.name).strip()
    if not display or len(display) > 120 or any(ord(char) < 32 for char in display):
        raise ValueError("Game name must contain 1–120 printable characters")
    items = custom_games()
    if any(item["folder"] == folder for item in items):
        raise ValueError("That game folder is already in your custom library")
    if len(items) >= 500:
        raise ValueError("Custom library limit reached (500 entries)")
    items.append({"name": display, "folder": folder})
    _save_custom_games(items)
    return {"name": display, "folder": folder, "artwork": None, "exists": True}


def rename_custom_game(directory: Path, name: str) -> None:
    display = name.strip()
    if not display or len(display) > 120 or any(ord(char) < 32 for char in display):
        raise ValueError("Game name must contain 1–120 printable characters")
    key = str(directory.resolve())
    items = custom_games()
    for item in items:
        if item["folder"] == key:
            item["name"] = display
            _save_custom_games(items)
            return
    raise ValueError("Custom game entry not found")


def remove_custom_game(directory: Path) -> None:
    """Remove only the library entry; installed games and AMDNR files are untouched."""
    key = str(directory.resolve())
    items = custom_games()
    remaining = [item for item in items if item["folder"] != key]
    if len(remaining) == len(items):
        raise ValueError("Custom game entry not found")
    _save_custom_games(remaining)


def steam_game_details(download_artwork: bool = False) -> list[dict[str, str | None]]:
    """Resolve Steam IDs and local artwork; optionally fetch missing covers."""
    roots = steam_roots()
    pending: list[tuple[str, Path, str | None]] = []
    for name, folder in steam_games():
        appid = None
        manifest_dir = folder.parent.parent
        try:
            manifests = manifest_dir.glob("appmanifest_*.acf")
            for manifest in manifests:
                try:
                    content = manifest.read_text(encoding="utf-8-sig", errors="replace")
                    if vdf_value(content, "installdir") == folder.name:
                        appid = vdf_value(content, "appid") or manifest.stem.removeprefix(
                            "appmanifest_")
                        break
                except OSError:
                    continue
        except OSError:
            pass
        pending.append((name, folder, appid))

    def resolve(game: tuple[str, Path, str | None]) -> dict[str, str | None]:
        name, folder, appid = game
        artwork = _steam_artwork(appid or "", roots, download_artwork, folder)
        return {"name": name, "folder": str(folder), "artwork": artwork}

    # Downloads are concurrent, bounded, and do not slow normal/offline scans.
    if download_artwork:
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(resolve, pending))
    return [resolve(game) for game in pending]


def artwork_diagnostics(download_artwork: bool = False) -> dict[str, object]:
    """Report which games lack cover art, without exposing user filesystem paths."""
    games = steam_game_details(download_artwork)
    missing = [{"name": game["name"], "reason": "No usable local or official cover found"}
               for game in games if not game["artwork"]]
    return {"total": len(games), "with_artwork": len(games) - len(missing),
            "missing": missing}


# Release downloads are restricted to this project's upstream GitHub repository.
# Individual game metadata is never hardcoded.
RELEASE_REPO = "3zwr1/AMD-NR---OptiScaler"
RELEASE_API = f"https://api.github.com/repos/{RELEASE_REPO}/releases"


def _github_json(url: str) -> object:
    request = urllib.request.Request(
        url, headers={"User-Agent": "AMDNR-Avalonia-Linux/1.0",
                      "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("GitHub release metadata is too large")
    return json.loads(payload)



# Official dedicated Daniel runtime ZIPs are distinct from AMDNR core archives.
# Discover the full release history and keep one authoritative release per version.
DANIEL_RUNTIME_TAG = "Alpha0.3.5.5R4"  # Legacy 0.6.0 fallback for existing installations.
DANIEL_RUNTIME_ASSET = "v0.6.0-Runtime.zip"
DANIEL_RUNTIME_RE = re.compile(r"v(\d+\.\d+\.\d+)-Runtime\.zip", re.I)
DANIEL_REQUIRED_FILES = frozenset({
    "dlssnr_amd_pass1.dll", "dlssnr_amd_pass2.dll",
    "dlssnr_amd_pass3.dll", "dlssnr_on_amd_weights.bin",
})
DANIEL_OPTIONAL_FILES = frozenset({"danielblnc_ATTRIBUTION.txt"})


def _daniel_version(asset: str) -> str | None:
    match = DANIEL_RUNTIME_RE.fullmatch(asset)
    return match.group(1) if match else None


def _daniel_sort(version: str) -> tuple[int, ...]:
    return tuple(int(item) for item in version.split("."))


def component_catalog(limit: int = 12) -> list[dict[str, object]]:
    """List current AMDNR extension assets and all officially published Daniel runtimes.

    History is read from the official repository only, never the Linux fork.
    Version entries deduplicate identical packages across multiple releases.
    Require either a published SHA256SUMS file OR an asset SHA-256 digest.
    """
    if not 1 <= limit <= 100:
        raise ValueError("Invalid catalog limit")
    releases = _github_json(f"{RELEASE_API}?per_page={max(limit, 100)}")
    if not isinstance(releases, list):
        raise ValueError("Invalid releases response")
    found, seen = [], set()
    daniel_versions = {}
    for index, release in enumerate(releases):
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag, assets = release.get("tag_name"), release.get("assets")
        if (not isinstance(tag, str) or
                not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", tag) or
                not isinstance(assets, list)):
            continue
        has_manifest = any(isinstance(a, dict) and a.get("name") == "SHA256SUMS.txt"
                           for a in assets)
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name, size = asset.get("name"), asset.get("size")
            digest = asset.get("digest")
            if (not isinstance(name, str) or not isinstance(size, int) or
                    not 0 < size <= 1024 ** 3):
                continue
            verified = (has_manifest or (isinstance(digest, str) and
                        bool(re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest))))
            if not verified:
                continue
            version = _daniel_version(name)
            if version is not None:
                # The same version occurs on multiple historical releases.
                # Prefer the newest release carrying the approved ZIP.
                if version not in daniel_versions:
                    daniel_versions[version] = {
                        "tag": tag, "name": f"Daniel {version} runtime",
                        "asset": name, "bytes": size,
                        "prerelease": bool(release.get("prerelease", False)),
                    }
            elif index < limit and re.fullmatch(
                    r"AMDNR-(?!v[0-9]|Launcher)[A-Za-z0-9._-]+\.zip", name, re.I):
                if name not in seen:
                    seen.add(name)
                    found.append({"tag": tag, "name": name, "asset": name,
                                  "bytes": size,
                                  "prerelease": bool(release.get("prerelease", False))})
    return ([daniel_versions[x] for x in sorted(daniel_versions,
                                               key=_daniel_sort, reverse=True)] + found)


def _is_component_zip(name: str) -> bool:
    return (_daniel_version(name) is not None or bool(re.fullmatch(
        r"AMDNR-(?!v[0-9]|Launcher)[A-Za-z0-9._-]+\.zip", name, re.I)))


def _component_install_name(asset: str, zip_member: str) -> str:
    """Only supported Daniel binaries/weights are installed in the game root."""
    if _daniel_version(asset) is not None:
        basename = zip_member.rsplit("/", 1)[-1]
        if basename not in DANIEL_REQUIRED_FILES | DANIEL_OPTIONAL_FILES:
            raise ValueError("Unsupported Daniel runtime payload: " + zip_member)
        return basename
    return zip_member


def _component_manifest(executable: Path) -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    key = hashlib.sha256(str(executable.resolve().parent).encode()).hexdigest()
    return state / "amdnr" / "managed-components" / f"{key}.json"


def _component_records(executable: Path) -> dict:
    path = _component_manifest(executable)
    if not path.exists():
        return {}
    if path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Invalid component registry")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get("format") != 1 or not isinstance(data.get("components"), dict):
        raise ValueError("Invalid component registry")
    return data["components"]


def _save_component_records(executable: Path, records: dict) -> None:
    path = _component_manifest(executable)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Unsafe component registry")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".components-", delete=False) as stream:
        temp = Path(stream.name)
        os.chmod(temp, 0o600)
        json.dump({"format": 1, "components": records}, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


# Model/runtime components can expand far beyond their compressed ZIP size.
# Keep bounded extraction and enforce available storage at installation time.
MAX_COMPONENT_UNPACKED = 12 * 1024 ** 3
MAX_COMPONENT_FILE = 8 * 1024 ** 3
MAX_COMPONENT_FILES = 10000


def _component_entries(archive: Path, *, inspect_only: bool = False) -> list:
    if _daniel_version(archive.name) == "0.8.0":
        # 0.8 uses the NeuralHub host and AMDNR-NeuralHub-080 setup/data
        # rather than Daniel 0.6's three pass DLLs. Never flatten its ZIP
        # into the game root or interpret it as an empty/corrupt archive.
        raise ValueError(
            "Daniel 0.8.0 uses NeuralHub, not the legacy pass-DLL layout. "
            "Its host, settings, and data-index preparation require a separate "
            "installer; this version is listed but installation is not supported yet.")
    with zipfile.ZipFile(archive) as source:
        entries, seen, size = [], set(), 0
        for entry in source.infolist():
            name = entry.filename
            parts = name.rstrip("/").split("/")
            if (not name or chr(92) in name or name.startswith("/") or ":" in name
                    or any(p in ("", ".", "..") for p in parts)):
                raise ValueError("Unsafe archive path")
            if entry.is_dir():
                continue
            if _daniel_version(archive.name) is not None:
                if name.rsplit("/", 1)[-1] not in DANIEL_REQUIRED_FILES | DANIEL_OPTIONAL_FILES:
                    continue
            mode = (entry.external_attr >> 16) & 0o170000
            if mode not in (0, 0o100000):
                raise ValueError("Archive contains links or special files")
            if (entry.file_size < 0 or entry.compress_size < 0 or
                    entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise ValueError("Unsupported component file")
            size += entry.file_size
            if len(entries) >= (100000 if inspect_only else MAX_COMPONENT_FILES):
                raise ValueError("Component archive has too many files for safe inspection/extraction")
            if not inspect_only and entry.file_size > MAX_COMPONENT_FILE:
                raise ValueError("Component file exceeds 8 GiB extracted size limit")
            if not inspect_only and size > MAX_COMPONENT_UNPACKED:
                raise ValueError("Component exceeds 12 GiB extracted size limit")
            destination = _component_install_name(archive.name, name)
            if destination.casefold() in seen:
                raise ValueError("Duplicate archive destination")
            seen.add(destination.casefold())
            entries.append(entry)
    if not entries:
        raise ValueError("Empty component archive")
    if _daniel_version(archive.name) is not None:
        actual = {_component_install_name(archive.name, x.filename) for x in entries}
        if not DANIEL_REQUIRED_FILES.issubset(actual):
            raise ValueError("Daniel runtime ZIP missing required pass DLLs or weights")
    return entries


def _component_target(root: Path, name: str) -> Path:
    dest = root.joinpath(*name.split("/"))
    relative = dest.relative_to(root)
    if (not name or name.startswith("/") or chr(92) in name or ":" in name or
            any(part in ("", ".", "..") for part in name.split("/"))):
        raise ValueError("Unsafe recorded component path")
    parent = root
    if root.is_symlink():
        raise ValueError("Symlink game folder")
    for segment in relative.parts[:-1]:
        parent = parent / segment
        if parent.is_symlink():
            raise ValueError("Symlink component directory")
    if dest.is_symlink():
        raise ValueError("Symlink component target")
    return dest


def _component_existing_matches(source: zipfile.ZipFile, entry: zipfile.ZipInfo,
                                dest: Path) -> bool:
    """Compare exact bytes without modifying an existing game file."""
    if dest.is_symlink() or not dest.is_file() or dest.stat().st_size != entry.file_size:
        return False
    expected = hashlib.sha256()
    with source.open(entry) as incoming:
        for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
            expected.update(chunk)
    return _digest(dest) == expected.hexdigest()


def component_preview(executable: Path, tag: str, asset: str) -> dict:
    # Select the installation backend before network I/O. NeuralHub requires
    # a different, currently unavailable Linux GPU/driver integration; never
    # download its ZIP and pretend it is a legacy pass-DLL component.
    if _daniel_version(asset) == "0.8.0":
        raise ValueError(
            "Daniel 0.8.0 uses NeuralHub and requires Windows AMD GPU driver "
            "interfaces not implemented by this Proton launcher. No files changed.")
    if not executable.is_file() or executable.is_symlink() or executable.suffix.lower() != ".exe":
        raise ValueError("Select a Windows game executable")
    if not _is_component_zip(asset):
        raise ValueError("Not a component package")
    archive = download_release(tag, asset)
    root = executable.resolve().parent
    entries = _component_entries(archive, inspect_only=True)
    total_size = sum(e.file_size for e in entries)
    too_many = len(entries) > MAX_COMPONENT_FILES
    too_large = (too_many or total_size > MAX_COMPONENT_UNPACKED or any(
        e.file_size > MAX_COMPONENT_FILE for e in entries))
    largest_files = [{"name": e.filename, "bytes": e.file_size}
                     for e in sorted(entries, key=lambda e: e.file_size, reverse=True)[:5]]
    conflicts, identical, new_files, replaceable = [], [], [], []
    with zipfile.ZipFile(archive) as source:
        for entry in entries:
            try:
                dest = _component_target(root, _component_install_name(asset, entry.filename))
                if dest.exists():
                    if not too_large and _component_existing_matches(source, entry, dest):
                        identical.append(_component_install_name(asset, entry.filename))
                    else:
                        conflicts.append(_component_install_name(asset, entry.filename))
                        if dest.is_file() and not dest.is_symlink() and not too_large:
                            replaceable.append(entry.filename)
                else:
                    new_files.append(_component_install_name(asset, entry.filename))
            except (ValueError, OSError):
                conflicts.append(_component_install_name(asset, entry.filename))
    if _daniel_version(asset) is not None:
        for older in _component_records(executable):
            if _daniel_version(older) is not None and older != asset:
                conflicts.append("Remove installed Daniel " + str(_daniel_version(older)) +
                                 " before installing another version")
    return {"tag": tag, "asset": asset,
            "files": [_component_install_name(asset, e.filename) for e in entries[:50]],
            "file_count": len(entries),
            "extracted_bytes": total_size, "largest_files": largest_files,
            "too_many_files": too_many,
            "safety_limit_exceeded": too_large,
            "conflicts": conflicts[:50], "conflict_count": len(conflicts),
            "replaceable_count": len(replaceable),
            "identical": identical[:50], "identical_count": len(identical),
            "new_file_count": len(new_files),
            "installable": not conflicts and not too_large}



def _component_backup_dir(executable: Path, asset: str) -> Path:
    """Per-game/per-component immutable originals outside the game directory."""
    if not _is_component_zip(asset):
        raise ValueError("Invalid component asset")
    manifest = _component_manifest(executable)
    return manifest.parent / (manifest.stem + ".backups") / hashlib.sha256(asset.encode()).hexdigest()


def _write_component_file(source: zipfile.ZipFile, entry: zipfile.ZipInfo,
                          destination: Path) -> str:
    """Bounded extraction to exclusive temp file; atomic rename in destination directory."""
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".amdnr-component-",
                                     delete=False) as stream:
        temp = Path(stream.name)
    try:
        sha = hashlib.sha256()
        written = 0
        with source.open(entry) as incoming, temp.open("wb") as output:
            for block in iter(lambda: incoming.read(1024 * 1024), b""):
                written += len(block)
                if written > entry.file_size or written > MAX_COMPONENT_FILE:
                    raise ValueError("Unexpected extracted file size")
                sha.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if written != entry.file_size:
            raise ValueError("Incomplete component extraction")
        os.replace(temp, destination)
        return sha.hexdigest()
    finally:
        temp.unlink(missing_ok=True)


def install_component(executable: Path, tag: str, asset: str,
                      *, replace_conflicts: bool = False) -> dict:
    preview = component_preview(executable, tag, asset)
    if preview["safety_limit_exceeded"]:
        raise ValueError("Component exceeds safe extraction limits; inspection only")
    if _daniel_version(asset) is not None:
        previous = [name for name in _component_records(executable)
                    if _daniel_version(name) is not None and name != asset]
        if previous:
            raise ValueError("Remove installed Daniel " + ", ".join(previous) +
                             " before installing another version")
    if preview["conflict_count"] and (not replace_conflicts or
                                       preview["conflict_count"] != preview["replaceable_count"]):
        raise ValueError("Component would overwrite game files: " + ", ".join(preview["conflicts"][:6]))
    records = _component_records(executable)
    if asset in records:
        raise ValueError("Component already managed")
    if _daniel_version(asset) is not None:
        others = [x for x in records if _daniel_version(x) is not None and x != asset]
        if others:
            raise ValueError("Another Daniel runtime is installed (" + ", ".join(others) +
                             "). Remove it safely before switching versions.")
    if replace_conflicts and any(asset != other and name in
           (set(record.get("files", {})) | set(record.get("replaced", {})))
           for other, record in records.items() if isinstance(record, dict)
           for name in preview["conflicts"]):
        raise ValueError("A conflicting file is managed by another component")

    root = executable.resolve().parent
    archive = _release_cache_dir() / tag / asset
    entries = _component_entries(archive)
    required = sum(e.file_size for e in entries)
    free = shutil.disk_usage(root).free
    if free < required + max(128 * 1024 ** 2, required // 20):
        raise ValueError("Insufficient free disk space for extracted component")

    backup_dir = _component_backup_dir(executable, asset)
    if backup_dir.is_symlink() or backup_dir.exists():
        raise ValueError("Component backup directory already exists; inspect before retrying")

    added, replaced, hashes = [], {}, {}
    created_backup = False
    try:
        if replace_conflicts and preview["conflict_count"]:
            backup_dir.mkdir(parents=True, exist_ok=False)
            created_backup = True
        with zipfile.ZipFile(archive) as source:
            for entry in entries:
                name = _component_install_name(asset, entry.filename)
                dest = _component_target(root, name)
                if dest.exists():
                    if _component_existing_matches(source, entry, dest):
                        continue
                    if not replace_conflicts or not dest.is_file() or dest.is_symlink():
                        raise ValueError("Existing game file differs; refusing overwrite: " + name)
                    original_sha = _digest(dest)
                    backup = _component_target(backup_dir, name)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    with dest.open("rb") as incoming, backup.open("xb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                        outgoing.flush()
                        os.fsync(outgoing.fileno())
                    if _digest(backup) != original_sha or _digest(dest) != original_sha:
                        raise ValueError("Game file changed during backup: " + name)
                    replaced[name] = {"original_sha256": original_sha, "sha256": None}
                    replacement = dest.parent / (".amdnr-pending-" + hashlib.sha256(name.encode()).hexdigest())
                    if replacement.exists() or replacement.is_symlink():
                        raise ValueError("Temporary replacement path already exists")
                    try:
                        new_sha = _write_component_file(source, entry, replacement)
                        if _digest(dest) != original_sha:
                            raise ValueError("Game file changed during replacement: " + name)
                        os.replace(replacement, dest)
                        replaced[name]["sha256"] = new_sha
                    finally:
                        replacement.unlink(missing_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Atomic exclusive creation for brand-new files, without overwriting existing.
                with dest.open("xb") as output, source.open(entry) as incoming:
                    added.append(dest)
                    sha = hashlib.sha256()
                    written = 0
                    for block in iter(lambda: incoming.read(1024 * 1024), b""):
                        written += len(block)
                        if written > entry.file_size or written > MAX_COMPONENT_FILE:
                            raise ValueError("Unexpected extracted file size")
                        sha.update(block)
                        output.write(block)
                    output.flush()
                    os.fsync(output.fileno())
                    if written != entry.file_size:
                        raise ValueError("Incomplete component extraction")
                    hashes[name] = sha.hexdigest()
        records[asset] = {"tag": tag, "files": hashes, "replaced": replaced}
        _save_component_records(executable, records)
    except Exception:
        for name, metadata in reversed(list(replaced.items())):
            dest = _component_target(root, name)
            backup = _component_target(backup_dir, name)
            # Restore only our own replacement (never overwrite a third-party edit).
            if (metadata["sha256"] is not None and dest.is_file()
                    and _digest(dest) == metadata["sha256"] and backup.is_file()):
                shutil.copy2(backup, dest)
        for dest in reversed(added):
            if dest.is_file() and not dest.is_symlink():
                dest.unlink()
        # Retain backups on failures, to avoid losing originals during an interrupted rollback.
        raise
    return {"status": "installed", "asset": asset, "files": len(added),
            "replaced_files": len(replaced),
            "existing_identical_kept": len(entries) - len(added) - len(replaced)}


def installed_components(executable: Path) -> list:
    root = executable.resolve().parent
    output = []
    for asset, rec in _component_records(executable).items():
        if not isinstance(rec, dict) or not isinstance(rec.get("files"), dict) or not isinstance(rec.get("replaced", {}), dict):
            raise ValueError("Invalid component record")
        changed = []
        for name, digest in rec["files"].items():
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Invalid recorded component digest")
            dest = _component_target(root, name)
            if not dest.is_file() or _digest(dest) != digest:
                changed.append(name)
        backup_dir = _component_backup_dir(executable, asset)
        if backup_dir.is_symlink():
            raise ValueError("Unsafe component backups")
        for name, info in rec.get("replaced", {}).items():
            if not isinstance(info, dict):
                raise ValueError("Invalid component replacement record")
            digest, original = info.get("sha256"), info.get("original_sha256")
            if not all(isinstance(d, str) and re.fullmatch(r"[0-9a-f]{64}", d) for d in (digest, original)):
                raise ValueError("Invalid component replacement digests")
            dest = _component_target(root, name)
            backup = _component_target(backup_dir, name)
            if (not dest.is_file() or _digest(dest) != digest or
                    not backup.is_file() or _digest(backup) != original):
                changed.append(name)
        output.append({"asset": asset, "tag": rec.get("tag"),
                       "files": len(rec["files"]) + len(rec.get("replaced", {})),
                       "modified": changed})
    return output


def remove_component(executable: Path, asset: str) -> dict:
    records = _component_records(executable)
    if asset not in records:
        raise ValueError("Component not managed")
    root = executable.resolve().parent
    rec = records[asset]
    installed = installed_components(executable)
    match = next(x for x in installed if x["asset"] == asset)
    if match["modified"]:
        raise ValueError("Component modified or backup missing; refusing removal: " + match["modified"][0])
    backup_dir = _component_backup_dir(executable, asset)
    # Copy originals to temporary files before making any change. Never delete backups
    # until the registry is saved; recovery remains possible after an interrupted removal.
    staged = []
    try:
        for name in rec.get("replaced", {}):
            dest = _component_target(root, name)
            backup = _component_target(backup_dir, name)
            with tempfile.NamedTemporaryFile(dir=dest.parent, prefix=".amdnr-restore-",
                                             delete=False) as temp_stream:
                temp = Path(temp_stream.name)
            staged.append((temp, dest))
            shutil.copyfile(backup, temp)
        for temp, dest in staged:
            os.replace(temp, dest)
        for name in rec["files"]:
            _component_target(root, name).unlink()
        del records[asset]
        _save_component_records(executable, records)
    finally:
        for temp, _ in staged:
            temp.unlink(missing_ok=True)
    # Once every original is restored and registry update succeeds, clean stale backups
    # so future explicit reinstalls of the same version are possible.
    if backup_dir.is_dir() and not backup_dir.is_symlink():
        try:
            shutil.rmtree(backup_dir)
        except OSError:
            pass
    return {"status": "removed", "asset": asset,
            "files": len(rec["files"]), "restored": len(rec.get("replaced", {}))}


def prepare_mochi_model(executable: Path, source: Path) -> dict[str, object]:
    """Build verified Mochi Model A/B from a user-selected NVIDIA DLL or ZIP.

    No NVIDIA DLL or extracted model is bundled or obtained automatically.
    The bundled MIT Linux extractor validates the input SHA-256 and every
    model weight before returning files. No existing game file is replaced.
    """
    import subprocess
    if not executable.is_file() or executable.is_symlink() or executable.suffix.lower() != ".exe":
        raise ValueError("Select an existing Windows game executable")
    if (not source.is_file() or source.is_symlink() or
            source.suffix.lower() not in (".dll", ".zip") or
            not 0 < source.stat().st_size <= 1024 ** 3):
        raise ValueError("Choose a local nvngx_dlssnr.dll or ZIP (maximum 1 GiB)")
    if source.suffix.lower() == ".dll" and source.name.lower() != "nvngx_dlssnr.dll":
        raise ValueError("Source must be named nvngx_dlssnr.dll")
    tools = Path(__file__).with_name("model-tools")
    extractor = tools / "extract_model.sh"
    if not extractor.is_file() or extractor.is_symlink():
        raise ValueError("Local Mochi model extraction tools are unavailable")
    root = executable.resolve().parent
    target_dir = _component_target(root, "dlssnr-amd")
    if target_dir.exists() and (target_dir.is_symlink() or not target_dir.is_dir()):
        raise ValueError("Unsafe Mochi model destination")
    for filename in ("dlssnr.bin", "dlssnr-small.bin"):
        candidate = target_dir / filename
        if candidate.exists() or candidate.is_symlink():
            raise ValueError("Mochi model destination already exists; no files replaced: " + filename)
    # Stage on the game volume; hardlink the finished verified model into place
    # atomically and exclusively, preventing partial or overwritten models.
    completed = []
    with tempfile.TemporaryDirectory(prefix=".amdnr-model-", dir=root) as work:
        staging = Path(work)
        try:
            proc = subprocess.run(
                ["bash", str(extractor), str(source.resolve()), str(staging)],
                capture_output=True, text=True, timeout=600, check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                     "TMPDIR": str(staging)})
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Local Mochi model extraction timed out") from exc
        except FileNotFoundError as exc:
            raise ValueError("Mochi model extraction requires bash and python3") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise ValueError("Mochi model preparation failed: " + detail[-1200:])
        produced = [name for name in ("dlssnr.bin", "dlssnr-small.bin")
                    if (staging / name).is_file() and not (staging / name).is_symlink()]
        if "dlssnr.bin" not in produced:
            raise ValueError("Mochi model extractor produced no Model A")
        info = {}
        for name in produced:
            path = staging / name
            with path.open("rb") as prepared:
                signature = prepared.read(8)
            if (not 1024 * 1024 < path.stat().st_size <= 512 * 1024 * 1024 or
                    signature != b"NRMODEL1"):
                raise ValueError("Mochi model output failed format/size validation: " + name)
            info[name] = {"bytes": path.stat().st_size, "sha256": _digest(path)}
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            for name in produced:
                output = _component_target(root, "dlssnr-amd/" + name)
                os.link(staging / name, output)
                completed.append((output, info[name]["sha256"]))
        except Exception:
            for output, digest in completed:
                if output.is_file() and not output.is_symlink() and _digest(output) == digest:
                    output.unlink()
            raise
    return {"status": "prepared", "source": source.name, "models": info,
            "note": "Locally verified model data installed; restart the game to test Mochi runtime."}


# Optional user-approved COMMUNITY mirror; never an official NVIDIA endpoint.
# Pin both the GitHub release ZIP and the known, extractor-approved NVIDIA input.
# The plain dlssnr-310.9.16 release carries a MODIFIED runtime and fails
# Mochi's exact-source hash. Use the separate NVIDIA-original mirror release.
MOCHI_COMMUNITY_REPO = "RankFTW/rhi-repo"
MOCHI_COMMUNITY_TAG = "dlssnr-310.9.16-nvidia"
MOCHI_COMMUNITY_ASSET = "nvngx_dlssnr_310.9.16-nvidia.zip"
MOCHI_COMMUNITY_ZIP_SHA256 = "5277355f0578d36f2a25413d8c7ff4c6f9966cea5bad714305f23b20173e09f6"
MOCHI_EXPECTED_DLL_SHA256 = "2bc19bc09a7b89dd44f73e2ac0108fcc586e2154bdd0830f242f4f040e28789f"


def prepare_mochi_from_community(executable: Path, *, consent: bool = False) -> dict[str, object]:
    """Opt-in, hash-pinned, inspect-only community mirror fetch; no DLL persistence.

    Neither the mirror nor its copyright authorization is asserted to be
    official. No binary is installed or executed: the verified DLL is used
    only as input to the bundled local model extractor and then deleted.
    """
    if not consent:
        raise ValueError("Community binary download requires explicit user opt-in")
    if not executable.is_file() or executable.is_symlink() or executable.suffix.lower() != ".exe":
        raise ValueError("Select an existing Windows game executable")
    root = executable.resolve().parent
    target = _component_target(root, "dlssnr-amd")
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise ValueError("Unsafe Mochi model destination")
    if any((target / x).exists() or (target / x).is_symlink()
           for x in ("dlssnr.bin", "dlssnr-small.bin")):
        raise ValueError("Mochi model destination already exists; no files replaced")
    # Fetch metadata only from the fixed GitHub repository/tag. Do not trust
    # arbitrary URLs or SHA values supplied by the release description.
    metadata = _github_json(
        f"https://api.github.com/repos/{MOCHI_COMMUNITY_REPO}/releases/tags/{MOCHI_COMMUNITY_TAG}")
    if not isinstance(metadata, dict) or metadata.get("draft"):
        raise ValueError("Community mirror release metadata unavailable")
    asset = next((a for a in metadata.get("assets", [])
                  if isinstance(a, dict) and a.get("name") == MOCHI_COMMUNITY_ASSET), None)
    if not isinstance(asset, dict) or not isinstance(asset.get("size"), int):
        raise ValueError("Pinned community ZIP not found")
    if not 0 < asset["size"] <= 512 * 1024 * 1024:
        raise ValueError("Community source exceeds download limit")
    if asset.get("digest") != "sha256:" + MOCHI_COMMUNITY_ZIP_SHA256:
        raise ValueError("Community mirror ZIP digest changed; no download attempted")
    from urllib.parse import quote
    url = (f"https://github.com/{MOCHI_COMMUNITY_REPO}/releases/download/"
           f"{quote(MOCHI_COMMUNITY_TAG)}/{quote(MOCHI_COMMUNITY_ASSET)}")
    with tempfile.TemporaryDirectory(prefix=".amdnr-community-", dir=root) as work:
        staging = Path(work)
        archive = staging / MOCHI_COMMUNITY_ASSET
        request = urllib.request.Request(
            url, headers={"User-Agent": "AMDNR-Avalonia-Linux/1.0"})
        total, hasher = 0, hashlib.sha256()
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("xb") as output:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                total += len(chunk)
                if total > asset["size"]:
                    raise ValueError("Community ZIP exceeds advertised size")
                hasher.update(chunk)
                output.write(chunk)
        if total != asset["size"] or hasher.hexdigest() != MOCHI_COMMUNITY_ZIP_SHA256:
            raise ValueError("Community ZIP failed pinned SHA-256 verification")
        if not zipfile.is_zipfile(archive):
            raise ValueError("Community source is not a valid ZIP")
        with zipfile.ZipFile(archive) as source:
            entries = [e for e in source.infolist()
                       if not e.is_dir() and e.filename.split("/")[-1].lower() == "nvngx_dlssnr.dll"]
            if len(entries) != 1 or entries[0].file_size > 512 * 1024 * 1024:
                raise ValueError("Expected exactly one supported NVIDIA DLL in community ZIP")
            entry = entries[0]
            dll = staging / "nvngx_dlssnr.dll"
            dll_sha = hashlib.sha256()
            copied = 0
            with source.open(entry) as incoming, dll.open("xb") as output:
                for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                    copied += len(chunk)
                    if copied > entry.file_size or copied > 512 * 1024 * 1024:
                        raise ValueError("Community DLL exceeds declared extracted size")
                    dll_sha.update(chunk)
                    output.write(chunk)
            if copied != entry.file_size or dll_sha.hexdigest() != MOCHI_EXPECTED_DLL_SHA256:
                raise ValueError("Community NVIDIA DLL does not match supported model source SHA-256")
        result = prepare_mochi_model(executable, dll)
        result["source"] = "User-approved community mirror (verified input)"
        result["community_mirror"] = MOCHI_COMMUNITY_REPO
        return result


def runtime_diagnostics(executable: Path) -> dict[str, object]:
    """Read-only file-level diagnostics for the actual AMDNR proxy/runtime layout."""
    if not executable.is_file() or executable.is_symlink() or executable.suffix.lower() != ".exe":
        raise ValueError("Select an existing Windows executable")
    root = executable.resolve().parent
    filenames = (
        "OptiScaler.dll", "dxgi.dll", "version.dll", "winmm.dll", "winhttp.dll",
        "MochizukiNrRuntime.dll", "dlssnr-amd.asi",
        "dlssnr_amd_pass1.dll", "dlssnr_amd_pass2.dll",
        "dlssnr_amd_pass3.dll", "dlssnr_on_amd_weights.bin",
        "LmxxfNrRuntime.dll", "LmxxfNrRuntime.pak",
        "dlssnr-amd/dlssnr.bin",
        "dlssnr-amd/model.bin",
        "model-tools/dlssnr_extract_model.exe",
    )
    paths = {}
    for filename in filenames:
        path = root / filename
        paths[filename] = {"exists": path.is_file() and not path.is_symlink(),
                           "bytes": path.stat().st_size if path.is_file() and not path.is_symlink() else None}
    # Native Mochi .dll package is not an ASI plugin. Its model is derived
    # locally from a user's verified NVIDIA input; distribution ZIPs do not
    # contain the proprietary extracted weights.
    model = paths["dlssnr-amd/dlssnr.bin"]
    shader_root = root / "dlssnr-amd" / "shaders"
    aco_root = root / "dlssnr-amd" / "aco"
    plugins = root / "plugins"
    plugin_asi = []
    if plugins.is_dir() and not plugins.is_symlink():
        plugin_asi = sorted(x.name for x in plugins.iterdir()
                            if x.is_file() and not x.is_symlink() and x.suffix.lower() == ".asi")
    records = _component_records(executable)
    components = []
    for asset, record in records.items():
        names = list(record.get("files", {})) + list(record.get("replaced", {}))
        runtime_paths = [name for name in names
                         if name.casefold().endswith((".dll", ".asi", ".bin", ".pak"))]
        archive_candidates = []
        cache_archive = _release_cache_dir() / str(record.get("tag", "")) / asset
        if cache_archive.is_file() and not cache_archive.is_symlink():
            try:
                with zipfile.ZipFile(cache_archive) as source:
                    archive_candidates = [
                        item.filename for item in source.infolist()
                        if not item.is_dir() and item.filename.casefold().endswith(
                            (".dll", ".asi", ".pak", ".bin"))][:80]
            except (OSError, ValueError, zipfile.BadZipFile):
                archive_candidates = ["[Could not inspect cached component ZIP]"]
        components.append({"asset": asset, "runtime_paths": runtime_paths[:80],
                           "archive_candidates": archive_candidates,
                           "cached_archive_present": cache_archive.is_file(),
                           "managed_files": len(names)})
    return {"folder": str(root), "files": paths, "plugins_asi": plugin_asi,
            "components": components,
            "mochi_runtime_present": paths["MochizukiNrRuntime.dll"]["exists"],
            "mochi_model_present": model["exists"] and model["bytes"] is not None and model["bytes"] > 0,
            "mochi_shader_dir_present": shader_root.is_dir() and not shader_root.is_symlink(),
            "mochi_aco_dir_present": aco_root.is_dir() and not aco_root.is_symlink(),
            "mochi_legacy_asi_required": False,
            "daniel_pass_present": all(paths[f"dlssnr_amd_pass{i}.dll"]["exists"]
                                      for i in range(1, 4)),
            "daniel_weights_present": paths["dlssnr_on_amd_weights.bin"]["exists"],
            "note": "File presence does not establish that a neural runtime initializes under Proton."}


def release_catalog(limit: int = 12) -> list[dict[str, object]]:
    """Return only upstream AMDNR full-package ZIP assets from GitHub releases."""
    if not 1 <= limit <= 30:
        raise ValueError("Invalid catalog limit")
    records = _github_json(f"{RELEASE_API}?per_page={limit}")
    if not isinstance(records, list):
        raise ValueError("Unexpected GitHub release response")
    found: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict) or record.get("draft"):
            continue
        tag = record.get("tag_name")
        assets = record.get("assets", [])
        if not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", tag):
            continue
        if not isinstance(assets, list):
            continue
        checksums = [a for a in assets if isinstance(a, dict)
                     and a.get("name") == "SHA256SUMS.txt"]
        archives = [a for a in assets if isinstance(a, dict)
                    and re.fullmatch(r"AMDNR-v[A-Za-z0-9._-]+\.zip", str(a.get("name", "")))]
        if not checksums:
            continue
        for archive in archives:
            size = archive.get("size")
            if not isinstance(size, int) or not 0 < size <= 1024 * 1024 * 1024:
                continue
            found.append({
                "tag": tag, "name": record.get("name") or tag,
                "asset": archive["name"], "bytes": size,
                "prerelease": bool(record.get("prerelease", False)),
            })
    return found


def _release_asset(tag: str, asset_name: str) -> tuple[str, str, int, str | None]:
    """Resolve a selected release again; never trust a caller-supplied download URL."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", tag):
        raise ValueError("Invalid release tag")
    if not (re.fullmatch(r"AMDNR-v[A-Za-z0-9._-]+\.zip", asset_name) or _is_component_zip(asset_name)):
        raise ValueError("Only AMDNR release ZIP packages can be downloaded")
    record = _github_json(f"{RELEASE_API}/tags/{tag}")
    if not isinstance(record, dict) or record.get("draft"):
        raise ValueError("Release not found")
    assets = record.get("assets", [])
    if not isinstance(assets, list):
        raise ValueError("Invalid release assets")
    archive = next((a for a in assets if isinstance(a, dict)
                    and a.get("name") == asset_name), None)
    checksum = next((a for a in assets if isinstance(a, dict)
                     and a.get("name") == "SHA256SUMS.txt"), None)
    if not archive:
        raise ValueError("Selected release archive is missing")
    size = archive.get("size")
    if not isinstance(size, int) or not 0 < size <= 1024 * 1024 * 1024:
        raise ValueError("Release archive size is unsupported")
    root = f"https://github.com/{RELEASE_REPO}/releases/download/{tag}/"
    # Construct release URLs instead of accepting arbitrary URLs from API JSON.
    from urllib.parse import quote
    metadata_digest = archive.get("digest")
    metadata_sha256 = None
    if isinstance(metadata_digest, str) and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", metadata_digest):
        metadata_sha256 = metadata_digest[7:].lower()
    if checksum is None and metadata_sha256 is None:
        raise ValueError("No official SHA-256 checksum for selected release asset")
    return (root + quote(asset_name),
            root + "SHA256SUMS.txt" if checksum is not None else None,
            size, metadata_sha256)


def _release_cache_dir() -> Path:
    return Path(str(launcher_settings()["download_directory"]))


def download_release(tag: str, asset_name: str) -> Path:
    """Download a checksum-verified AMDNR ZIP to the user's cache, never to a game."""
    archive_url, sums_url, size, metadata_sha256 = _release_asset(tag, asset_name)
    expected = None
    if sums_url is not None:
        request = urllib.request.Request(sums_url, headers={"User-Agent": "AMDNR-Avalonia-Linux/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            sums = response.read(256 * 1024 + 1)
        if len(sums) > 256 * 1024:
            raise ValueError("Checksum manifest too large")
        for line in sums.decode("utf-8-sig").splitlines():
            match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", line.strip())
            if match and match.group(2).strip() == asset_name:
                expected = match.group(1).lower()
                break
    if expected is None:
        # Some official historical release manifests omit separately uploaded
        # runtime ZIPs. GitHub's release-asset digest is also an upstream
        # SHA-256 checksum, returned for this exact asset by the GitHub API.
        if metadata_sha256 is None:
            raise ValueError("No SHA-256 checksum for selected ZIP in release manifest or asset metadata")
        expected = metadata_sha256
    elif metadata_sha256 is not None and expected != metadata_sha256:
        raise ValueError("Official release SHA-256 manifest conflicts with asset metadata")

    cache = _release_cache_dir() / tag
    destination = cache / asset_name
    if destination.exists() and destination.is_file() and _digest(destination) == expected:
        return destination
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=cache, prefix=".download-", delete=False) as out:
        temporary = Path(out.name)
    try:
        hasher = hashlib.sha256()
        total = 0
        request = urllib.request.Request(archive_url, headers={"User-Agent": "AMDNR-Avalonia-Linux/1.0"})
        with urllib.request.urlopen(request, timeout=40) as response, temporary.open("wb") as stream:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                total += len(chunk)
                if total > size or total > 1024 * 1024 * 1024:
                    raise ValueError("Release download exceeded the published size")
                hasher.update(chunk)
                stream.write(chunk)
        if total != size:
            raise ValueError("Release download incomplete")
        if hasher.hexdigest() != expected:
            raise ValueError("Downloaded ZIP failed SHA-256 verification")
        if not zipfile.is_zipfile(temporary):
            raise ValueError("Downloaded release is not a ZIP archive")
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def _launcher_settings_path() -> Path:
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / "amdnr" / "launcher-settings.json"


def launcher_settings() -> dict[str, object]:
    """Validated, per-user preferences; no game files are read."""
    defaults: dict[str, object] = {
        "default_alias": "dxgi.dll",
        "download_directory": str(
            Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
            / "amdnr" / "releases"),
        "show_prereleases": False,
    }
    path = _launcher_settings_path()
    if not path.exists():
        return defaults
    try:
        if path.stat().st_size > 64 * 1024:
            raise ValueError("Launcher settings are too large")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("format") != 1:
            raise ValueError("Invalid launcher settings format")
        alias = data.get("default_alias")
        if alias in ALIASES:
            defaults["default_alias"] = alias
        download = data.get("download_directory")
        if isinstance(download, str) and len(download) <= 4096 and \
                Path(download).is_absolute():
            defaults["download_directory"] = download
        if isinstance(data.get("show_prereleases"), bool):
            defaults["show_prereleases"] = data["show_prereleases"]
        return defaults
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Unable to read launcher settings: {exc}") from exc


def save_launcher_settings(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ValueError("Settings must be a JSON object")
    alias = data.get("default_alias")
    download = data.get("download_directory")
    prerelease = data.get("show_prereleases")
    if alias not in ALIASES:
        raise ValueError("Unsupported default proxy DLL")
    if not isinstance(download, str) or not 1 <= len(download) <= 4096 or \
            not Path(download).is_absolute() or "\0" in download:
        raise ValueError("Download directory must be an absolute path")
    path = Path(download)
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError("Download path must be a directory, not a symlink or file")
    if not isinstance(prerelease, bool):
        raise ValueError("Show prereleases must be true or false")
    output = {"format": 1, "default_alias": alias,
              "download_directory": download,
              "show_prereleases": prerelease}
    target = _launcher_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=".settings-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(output, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {key: value for key, value in output.items() if key != "format"}


def _extension_manifest_path(executable: Path) -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    key = hashlib.sha256(str(executable.resolve().parent).encode("utf-8")).hexdigest()
    return state / "amdnr" / "managed-extensions" / f"{key}.json"


def _managed_extensions(executable: Path) -> dict[str, str]:
    path = _extension_manifest_path(executable)
    if not path.exists():
        return {}
    if path.stat().st_size > 64 * 1024:
        raise ValueError("Managed extension registry too large")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != 1 or \
            not isinstance(doc.get("extensions"), dict):
        raise ValueError("Invalid managed extension registry")
    result: dict[str, str] = {}
    for name, digest in doc["extensions"].items():
        if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,120}\.asi", name,
                                                  re.IGNORECASE) and \
                isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest):
            result[name] = digest
    return result


def _write_managed_extensions(executable: Path, extensions: dict[str, str]) -> None:
    target = _extension_manifest_path(executable)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=target.parent, prefix=".extensions-",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump({"format": 1, "extensions": extensions}, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def import_extension(executable: Path, source: Path) -> dict[str, str]:
    """Install a user-selected .asi without overwriting existing game/plugin files."""
    if not executable.is_file() or executable.is_symlink() or \
            executable.suffix.lower() != ".exe":
        raise ValueError("Select an existing Windows executable")
    if not source.is_file() or source.is_symlink() or source.suffix.lower() != ".asi" or \
            not re.fullmatch(r"[A-Za-z0-9._-]{1,120}\.asi", source.name, re.IGNORECASE):
        raise ValueError("Select a regular .asi extension with a safe filename")
    if not 0 < source.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError("Extension must be between 1 byte and 32 MiB")
    root = executable.resolve().parent
    plugins = root / "plugins"
    if plugins.is_symlink():
        raise ValueError("Plugin directory must not be a symlink")
    plugins.mkdir(parents=True, exist_ok=True)
    destination = plugins / source.name
    if destination.exists() or destination.is_symlink():
        raise ValueError("An extension with this filename already exists; no files replaced")
    managed = _managed_extensions(executable)
    if source.name in managed:
        raise ValueError("Extension is already registered; inspect it first")
    # Use exclusive creation to avoid races/overwrites.
    created = False
    try:
        with destination.open("xb") as output_file:
            created = True
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output_file)
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    try:
        managed[source.name] = _digest(destination)
        _write_managed_extensions(executable, managed)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {"name": source.name, "status": "installed"}


def remove_managed_extension(executable: Path, name: str) -> dict[str, str]:
    """Remove only unmodified extensions this launcher previously imported."""
    if not executable.is_file() or executable.is_symlink() or \
            executable.suffix.lower() != ".exe":
        raise ValueError("Select an existing Windows executable")
    managed = _managed_extensions(executable)
    if name not in managed:
        raise ValueError("Extension is not managed by this Linux launcher")
    destination = executable.resolve().parent / "plugins" / name
    if destination.is_symlink() or not destination.is_file() or \
            _digest(destination) != managed[name]:
        raise ValueError("Extension was modified or removed; refusing to delete it")
    destination.unlink()
    del managed[name]
    _write_managed_extensions(executable, managed)
    return {"name": name, "status": "removed"}


def extension_inventory(executable: Path) -> dict[str, object]:
    """Inventory plugin files without loading DLLs, altering files or scanning games."""
    if not executable.is_file() or executable.is_symlink() or \
            executable.suffix.casefold() != ".exe":
        raise ValueError("Select an existing Windows executable")
    root = executable.resolve().parent
    plugins = root / "plugins"
    ini = root / "OptiScaler.ini"
    result: dict[str, object] = {
        "folder": str(plugins), "plugins": [], "enabled": None,
        "ini_present": ini.is_file() and not ini.is_symlink(),
    }
    if plugins.is_dir() and not plugins.is_symlink():
        found = []
        managed = _managed_extensions(executable)
        for candidate in sorted(plugins.iterdir(), key=lambda p: p.name.casefold()):
            if candidate.suffix.lower() not in (".asi", ".dll") or \
                    not candidate.is_file() or candidate.is_symlink():
                continue
            found.append({"name": candidate.name, "size": candidate.stat().st_size,
                          "managed": candidate.name in managed,
                          "modified": (candidate.name in managed and
                                       _digest(candidate) != managed[candidate.name])})
            if len(found) >= 500:
                break
        result["plugins"] = found
    if ini.is_file() and not ini.is_symlink() and ini.stat().st_size <= 512 * 1024:
        content = ini.read_text(encoding="utf-8-sig", errors="replace")
        section = None
        values = []
        for line in content.splitlines():
            match = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
            if match:
                section = match.group(1).strip().lower()
                continue
            if line.lstrip().startswith((";", "#")):
                continue
            match = re.match(r"^\s*LoadAsiPlugins\s*=\s*(true|false|1|0)\s*$",
                             line, re.IGNORECASE)
            if match and section == "plugins":
                values.append(match.group(1).lower() in ("true", "1"))
        if len(values) == 1:
            result["enabled"] = values[0]
    return result


def set_extension_loader(executable: Path, expected_sha: str, enabled: bool) -> dict[str, str]:
    """Set one [Plugins] LoadAsiPlugins entry through the backup-aware INI editor."""
    if not isinstance(enabled, bool):
        raise ValueError("Invalid extension loader state")
    snapshot = ini_snapshot(executable)
    if snapshot["sha256"] != expected_sha.casefold():
        raise ValueError("INI changed since it was opened. Reload before saving")
    text = str(snapshot["text"])
    lines = text.splitlines(keepends=True)
    in_plugins = False
    matches: list[int] = []
    section_locations: list[int] = []
    for i, line in enumerate(lines):
        section = re.match(r"^\s*\[([^\]\r\n]+)\]\s*$", line.rstrip("\r\n"))
        if section:
            in_plugins = section.group(1).strip().casefold() == "plugins"
            if in_plugins:
                section_locations.append(i)
            continue
        if in_plugins and not line.lstrip().startswith((";", "#")) and \
                re.match(r"^\s*LoadAsiPlugins\s*=", line, re.IGNORECASE):
            matches.append(i)
    if len(section_locations) > 1 or len(matches) > 1:
        raise ValueError("Multiple plugin settings; edit manually")
    value = "true" if enabled else "false"
    newline = "\r\n" if "\r\n" in text else "\n"
    if matches:
        i = matches[0]
        line = lines[i]
        replacement = re.sub(
            r"(?i)(^\s*LoadAsiPlugins\s*=\s*)[^;\r\n]*",
            lambda m: m.group(1) + value, line, count=1)
        lines[i] = replacement
    elif section_locations:
        i = section_locations[0] + 1
        lines.insert(i, "LoadAsiPlugins=" + value + newline)
    else:
        if text and not text.endswith(("\n", "\r")):
            lines.append(newline)
        lines.append("[Plugins]" + newline)
        lines.append("LoadAsiPlugins=" + value + newline)
    return save_game_ini(executable, expected_sha, "".join(lines))


def _game_ini_path(executable: Path) -> Path:
    if not executable.is_file() or executable.is_symlink() or \
            executable.suffix.casefold() != ".exe":
        raise ValueError("Choose an existing, regular Windows game executable")
    target = executable.resolve().parent / "OptiScaler.ini"
    if not target.is_file() or target.is_symlink():
        raise ValueError("OptiScaler.ini not found beside the selected executable")
    if target.stat().st_size > 512 * 1024:
        raise ValueError("OptiScaler.ini is too large to edit safely")
    return target


def ini_snapshot(executable: Path) -> dict[str, object]:
    """Exact UTF-8 INI text and discovered section/key names, no assumptions."""
    ini = _game_ini_path(executable)
    content = ini.read_bytes()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("INI is not UTF-8; edit it manually to preserve encoding") from exc
    sections: list[dict[str, object]] = []
    current: dict[str, object] = {"name": "General (before sections)", "keys": []}
    for line in text.splitlines():
        match = re.match(r"^\s*\[([^\]\r\n]{1,120})\]\s*$", line)
        if match:
            sections.append(current)
            current = {"name": match.group(1).strip(), "keys": []}
        else:
            setting = re.match(r"^\s*([^;#\s][^=\r\n]{0,119}?)\s*=", line)
            if setting:
                keys = current["keys"]
                if isinstance(keys, list) and len(keys) < 150:
                    keys.append(setting.group(1).strip())
    sections.append(current)
    return {"text": text, "sha256": hashlib.sha256(content).hexdigest(),
            "sections": sections[:150], "path": str(ini)}


def save_game_ini(executable: Path, expected_sha: str, new_text: str) -> dict[str, str]:
    """Optimistic-concurrency save with untouched backup outside the game.

    Preserve unknown fields, whitespace and comments in the user-edited text.
    Never update installer-owned file checksums or rewrite its backup manifest.
    """
    ini = _game_ini_path(executable)
    if not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha):
        raise ValueError("Invalid original INI checksum")
    if not isinstance(new_text, str) or "\0" in new_text:
        raise ValueError("Invalid INI content")
    new_data = new_text.encode("utf-8")
    if len(new_data) > 512 * 1024:
        raise ValueError("INI content exceeds the 512 KiB limit")
    if not re.search(r"^\s*\[[^\]\r\n]+\]", new_text, flags=re.MULTILINE):
        raise ValueError("INI must contain at least one [section]")
    original = ini.read_bytes()
    if hashlib.sha256(original).hexdigest() != expected_sha.casefold():
        raise ValueError("INI changed since it was opened. Reload before saving")
    if original == new_data or original.lstrip(b"\xef\xbb\xbf") == new_data:
        return {"status": "unchanged", "backup": "", "sha256": expected_sha.casefold()}
    state_home = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    folder_hash = hashlib.sha256(str(ini.parent.resolve()).encode("utf-8")).hexdigest()
    backups = state_home / "amdnr" / "config-backups" / folder_hash
    backups.mkdir(parents=True, exist_ok=True)
    import datetime
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with tempfile.NamedTemporaryFile(dir=backups, prefix=timestamp + "-",
                                     suffix=".ini", delete=False) as copy:
        backup = Path(copy.name)
        os.chmod(backup, 0o600)
        copy.write(original)
        copy.flush()
        os.fsync(copy.fileno())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=ini.parent, prefix=".amdnr-ini-",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, ini.stat().st_mode & 0o777)
            stream.write(new_data)
            stream.flush()
            os.fsync(stream.fileno())
        # Do not silently overwrite another process's more recent edit.
        if hashlib.sha256(ini.read_bytes()).hexdigest() != expected_sha.casefold():
            raise ValueError("INI changed while saving. Backup kept; reload first")
        os.replace(temporary, ini)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"status": "saved", "backup": str(backup),
            "sha256": hashlib.sha256(new_data).hexdigest()}


def _preferred_exe_path(directory: Path) -> Path:
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    key = hashlib.sha256(str(directory.resolve()).encode("utf-8")).hexdigest()
    return config / "amdnr" / "game-executables" / f"{key}.json"


def saved_executable(directory: Path) -> str | None:
    """Read a per-install-directory preference; stale paths are ignored."""
    if not directory.is_dir():
        return None
    try:
        record = json.loads(_preferred_exe_path(directory).read_text(encoding="utf-8"))
        path = Path(record["executable"])
        if path.is_file() and path.suffix.lower() == ".exe" and not path.is_symlink() \
                and path.resolve().is_relative_to(directory.resolve()):
            return str(path.resolve())
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def remember_executable(directory: Path, executable: Path) -> str:
    """Persist explicit user choice within this game, not a global game-name mapping."""
    if not directory.is_dir() or not executable.is_file() or \
            executable.suffix.lower() != ".exe" or executable.is_symlink() or \
            not executable.resolve().is_relative_to(directory.resolve()):
        raise ValueError("Choose a Windows executable inside the selected game folder")
    destination = _preferred_exe_path(directory)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=destination.parent, prefix=".exe-choice-",
        encoding="utf-8", delete=False
    ) as output:
        temporary = Path(output.name)
        json.dump({"executable": str(executable.resolve())}, output)
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return str(executable.resolve())


def _game_binary_scan(directory: Path) -> tuple[list[Path], list[str], bool]:
    """Bounded, symlink-free traversal with per-directory error recovery."""
    if not directory.is_dir():
        return [], [], False
    root = directory.resolve()
    folders = [(root, 0)]
    windows: list[Path] = []
    native: list[str] = []
    unreadable = False
    visited = 0
    # Vendor/dependency subtrees cannot contain the game's launcher. Avoid
    # walking entire embedded development SDKs or Windows redistributables.
    skip = {"__pycache__", ".git", "node_modules", "steamapps",
            "redist", "_commonredist", "redistributables"}
    while folders and visited < 30000 and len(windows) < 200:
        folder, depth = folders.pop()
        try:
            with os.scandir(folder) as entries:
                children = sorted(list(entries), key=lambda e: e.name.casefold())
        except OSError:
            unreadable = True
            continue
        for entry in children:
            visited += 1
            if visited > 30000:
                break
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if depth < 14 and entry.name.casefold() not in skip:
                        folders.append((Path(entry.path), depth + 1))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                name = entry.name.casefold()
                path = Path(entry.path)
                if name.endswith(".exe"):
                    windows.append(path)
                elif depth <= 3 and (
                    name.endswith((".x86_64", ".x86", ".sh", ".appimage"))
                    or (depth <= 1 and "." not in name)
                ):
                    # Only inspect the first few bytes; do not execute candidates.
                    with path.open("rb") as stream:
                        magic = stream.read(4)
                    if magic == b"\x7fELF" or (
                        magic.startswith(b"#!") and
                        name.endswith((".sh", ".x86_64", ".x86"))
                    ):
                        native.append(str(path.relative_to(root)))
            except OSError:
                unreadable = True
                continue
    return windows, native[:12], unreadable or visited >= 30000


def steam_launch_options_for_directory(directory: Path, alias: str) -> dict[str, object]:
    """Get read-only user launch options and a proposed combined Steam command."""
    import importlib.util
    source = Path(__file__).with_name("steam_user_launch.py")
    spec = importlib.util.spec_from_file_location("amdnr_steam_user_launch", source)
    if spec is None or spec.loader is None:
        return {"status": "unavailable", "existing": None, "preview": None,
                "reason": "parser_unavailable"}
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    folder = directory.resolve()
    if folder.parent.name != "common" or folder.parent.parent.name != "steamapps":
        return {"status": "not_steam_install", "existing": None, "preview": None}
    appid = None
    for manifest in folder.parent.parent.glob("appmanifest_*.acf"):
        try:
            if manifest.stat().st_size > 1024 * 1024:
                continue
            content = manifest.read_text(encoding="utf-8-sig", errors="replace")
            if vdf_value(content, "installdir") != folder.name:
                continue
            found = vdf_value(content, "appid") or manifest.stem.removeprefix("appmanifest_")
            if found.isdecimal():
                appid = int(found)
                break
        except OSError:
            continue
    if appid is None:
        return {"status": "manifest_missing", "existing": None, "preview": None}
    report = parser.read_launch_options(appid, steam_roots())
    report["appid"] = appid
    if report["status"] in ("empty", "found"):
        report.update(parser.preview_launch_options(report["existing"], alias))
        # Compose status is separate from read status.
        report["compose_status"] = report.pop("status")
        report["status"] = "found" if report["existing"] else "empty"
    else:
        report["preview"] = None
    return report


def steam_launch_for_directory(directory: Path) -> dict[str, object]:
    """Resolve Windows launch target from the installed Steam app's cached AppID."""
    missing = {"source": "steam_cache", "windows_candidates": [],
               "selected": None, "linux_launches": 0, "reason": "not_steam_install"}
    try:
        folder = directory.resolve()
        if folder.parent.name != "common" or folder.parent.parent.name != "steamapps":
            return missing
        manifest_dir = folder.parent.parent
        appid = None
        for manifest in manifest_dir.glob("appmanifest_*.acf"):
            if not manifest.is_file():
                continue
            content = manifest.read_text(encoding="utf-8-sig", errors="replace")
            if vdf_value(content, "installdir") == folder.name:
                found = vdf_value(content, "appid") or manifest.stem.removeprefix("appmanifest_")
                if found.isdecimal():
                    appid = int(found)
                    break
        if appid is None:
            missing["reason"] = "manifest_missing"
            return missing

        import importlib.util
        source = Path(__file__).with_name("steam_launch_info.py")
        spec = importlib.util.spec_from_file_location("amdnr_steam_launch_info", source)
        if spec is None or spec.loader is None:
            raise ValueError("Steam metadata parser not available")
        parser = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(parser)
        data = parser.read_cached_app(appid, steam_roots())
        report = parser.resolve_windows_launch(data, folder)
        report["appid"] = appid
        return report
    except (OSError, ValueError, ImportError, AttributeError) as exc:
        missing["reason"] = "cache_unavailable"
        return missing


def executable_scan(directory: Path) -> dict[str, object]:
    """Windows EXE candidates plus honest native-game/partial-scan diagnostics."""
    windows, native, partial = _game_binary_scan(directory)
    if not directory.is_dir():
        return {"candidates": [], "native": [], "reason": "missing_directory",
                "partial": False, "steam_launch": {"selected": None, "reason": "missing_directory"}}
    bad = ("unins", "setup", "crash", "redist", "vcredist",
           "unitycrash", "easyanticheat", "benchmark", "updater",
           "anticheat", "uninstall", "vconsole", "editor", "crashhandler")
    root = directory.resolve()
    ranked: list[tuple[int, Path]] = []
    for path in windows:
        relative = path.relative_to(root)
        lower = str(relative).lower().replace("\\", "/")
        score = 0
        if any(part in path.name.casefold() for part in bad):
            score -= 100
        if "shipping" in path.name.casefold():
            score += 45
        if "binaries/win64" in lower:
            score += 30
        if "win64" in lower or "x64" in lower:
            score += 10
        if path.stem.casefold() == directory.name.casefold():
            score += 20
        score -= len(relative.parts) * 2
        ranked.append((score, path))
    ranked.sort(key=lambda v: (-v[0], str(v[1]).casefold()))
    best = ranked[0][0] if ranked else -999
    runner = ranked[1][0] if len(ranked) > 1 else -999
    confident = best > -50 and (
        len(ranked) == 1 or (best >= 15 and best - runner >= 15))
    candidates = [
        {"path": str(path), "recommended": rank == 0 and score > -50,
         "auto_select": rank == 0 and confident,
         "suspicious": score <= -50}
        for rank, (score, path) in enumerate(ranked[:50])
    ]
    # Steam's installed app manifest maps a folder to AppID; appinfo can give
    # a real launch target. Keep all other scanner results as fallbacks.
    steam = steam_launch_for_directory(directory)
    if steam.get("reason") == "not_a_game":
        for entry in candidates:
            entry["auto_select"] = False
    steam_choice = steam.get("selected")
    if isinstance(steam_choice, str):
        match = next((entry for entry in candidates if entry["path"] == steam_choice), None)
        for entry in candidates:
            entry["auto_select"] = False
            entry["recommended"] = entry["path"] == steam_choice
        if match is None:
            candidates.insert(0, {"path": steam_choice, "recommended": True,
                                  "auto_select": True, "suspicious": False})
        else:
            match["auto_select"] = True
            candidates.remove(match)
            candidates.insert(0, match)
    reason = ("steam_primary" if steam_choice else
              "found_windows_exe" if candidates else
              "native_linux_files" if native else
              "partial_scan" if partial else "no_windows_exe")
    return {"candidates": candidates, "native": native,
            "reason": reason, "partial": partial, "steam_launch": steam}


def _library_index_path() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "amdnr" / "library-index.json"


def _read_library_index() -> dict[str, dict[str, object]]:
    path = _library_index_path()
    if not path.is_file():
        return {}
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Library index exceeds size limit")
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("format") != 1 or \
                not isinstance(state.get("games"), list):
            raise ValueError("Invalid library index")
        entries = {}
        for item in state["games"][:5000]:
            if isinstance(item, dict) and isinstance(item.get("folder"), str) and \
                    Path(item["folder"]).is_absolute():
                entries[item["folder"]] = item
        return entries
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Unable to read saved library index: {exc}") from exc


def _write_library_index(entries: list[dict[str, object]]) -> None:
    path = _library_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".library-index-",
            suffix=".tmp", delete=False
        ) as stream:
            temporary = stream.name
            os.chmod(temporary, 0o600)
            json.dump({"format": 1, "games": entries}, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _valid_index_executable(folder: Path, value: object) -> str | None:
    """Only trust an existing .exe strictly inside the intended game directory."""
    if not isinstance(value, str) or not value:
        return None
    try:
        exe = Path(value)
        if not exe.is_absolute() or not exe.is_file() or exe.is_symlink() or \
                exe.suffix.casefold() != ".exe" or \
                not exe.resolve().is_relative_to(folder.resolve()):
            return None
        return str(exe.resolve())
    except (OSError, ValueError):
        return None


def differential_library() -> list[dict[str, object]]:
    """Quick manifest + file-existence reconciliation; never crawl game binaries.

    Steam manifest discovery is necessary to find installs/uninstalls. Existing
    entries retain last known artwork and EXE; only new entries resolve artwork.
    Missing custom mounts remain saved; deleted Steam manifests remove entries.
    """
    previous = _read_library_index()
    # Upgrade existing users' saved full-audit selections into the new index
    # without rescanning game files or Steam metadata.
    try:
        prior_audit = {
            str(row["folder"]): row.get("executable")
            for row in cached_library_audit()
            if row.get("status") == "windows_ready"
        }
    except ValueError:
        prior_audit = {}
    steam = steam_games()
    custom = custom_games()
    games: list[dict[str, object]] = []
    seen: set[str] = set()
    new_steam: set[str] = set()
    for name, folder in steam:
        key = str(folder)
        old = previous.get(key, {})
        if key not in previous:
            new_steam.add(key)
        games.append({"name": name, "folder": key, "custom": False,
                      "artwork": old.get("artwork"),
                      "artwork_checked": old.get("artwork_checked", False),
                      "executable": old.get("executable")})
        seen.add(key)
    for entry in custom:
        folder = str(entry["folder"])
        if folder in seen:
            continue
        old = previous.get(folder, {})
        games.append({"name": str(entry["name"]), "folder": folder, "custom": True,
                      "artwork": entry.get("artwork") or old.get("artwork"),
                      "artwork_checked": True,
                      "executable": old.get("executable")})
        seen.add(folder)
    # Third-party game installs are reconciled from small Heroic/Lutris metadata
    # files; no recursive executable scanning occurs during normal refresh.
    try:
        from third_party_stores import external_games
        for external in external_games():
            folder = external["folder"]
            if folder in seen:
                continue
            old = previous.get(folder, {})
            games.append({"name": external["name"], "folder": folder,
                          "custom": True, "store": external["store"],
                          "artwork": old.get("artwork"),
                          "artwork_checked": True,
                          "executable": old.get("executable") or external.get("executable")})
            seen.add(folder)
    except (OSError, ValueError):
        # Game discovery must remain usable when third-party metadata breaks.
        pass

    # Resolve cover art only for newly installed Steam games or missing cached art.
    needs_art = {row["folder"] for row in games if not row["custom"] and
                 (row["folder"] in new_steam or
                  (isinstance(row["artwork"], str) and
                   not Path(row["artwork"]).is_file()) or
                  not row["artwork_checked"])}
    if needs_art:
        art_by_folder = {row["folder"]: row["artwork"]
                         for row in steam_game_details(False)
                         if row["folder"] in needs_art}
        for row in games:
            if row["folder"] in needs_art:
                row["artwork"] = art_by_folder.get(row["folder"])
                row["artwork_checked"] = True
    for row in games:
        folder = Path(str(row["folder"]))
        # An explicit user cover can change without a full Steam-artwork search.
        manual_art = _manual_artwork(folder) if folder.is_dir() else None
        if manual_art is not None:
            row["artwork"] = str(manual_art)
        if isinstance(row["artwork"], str) and not Path(row["artwork"]).is_file():
            row["artwork"] = None
        # A remembered manual choice outranks cached automatic metadata.
        row["executable"] = (saved_executable(folder) or
                             _valid_index_executable(folder, row["executable"]) or
                             _valid_index_executable(folder, prior_audit.get(str(folder))))
    games.sort(key=lambda row: str(row["name"]).casefold())
    _write_library_index(games)
    return games


def index_library_executable(folder: Path, executable: Path) -> None:
    """Update an already-indexed game's EXE when it is successfully selected."""
    valid = _valid_index_executable(folder, str(executable))
    if valid is None:
        raise ValueError("Executable must exist within the selected game folder")
    index = _read_library_index()
    key = str(folder.resolve())
    if key not in index:
        return  # A removed or unknown game must not be reinserted.
    index[key]["executable"] = valid
    _write_library_index(list(index.values()))


def installed_games_overview() -> list[dict[str, object]]:
    """Lightweight installation-record inventory from the saved game index.

    Checks only the indexed executable and its adjacent installation record.
    No Steam discovery, recursion, file hashing, or modifications occur here.
    """
    overview: list[dict[str, object]] = []
    for row in sorted(_read_library_index().values(),
                      key=lambda item: str(item.get("name", "")).casefold()):
        folder_string = row.get("folder")
        if not isinstance(folder_string, str):
            continue
        folder = Path(folder_string)
        exe = _valid_index_executable(folder, row.get("executable"))
        if exe is None:
            continue
        record_path = Path(exe).parent / STATE_NAME
        if not record_path.is_file():
            continue
        entry: dict[str, object] = {
            "name": str(row.get("name", folder.name)),
            "folder": str(folder),
            "executable": exe,
            "status": "invalid_record",
            "alias": None,
            "tracked_files": 0,
            "source_archive": None,
            "custom": bool(row.get("custom", False)),
        }
        try:
            if record_path.is_symlink() or record_path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("Invalid installation record file")
            state = json.loads(record_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("format") != 1 or \
                    not isinstance(state.get("files"), list) or \
                    state.get("alias") not in ALIASES:
                raise ValueError("Invalid installation record")
            entry["status"] = "recorded"
            entry["alias"] = state["alias"]
            entry["tracked_files"] = len(state["files"])
            source = state.get("source_archive")
            if isinstance(source, str) and len(source) < 4096:
                entry["source_archive"] = source
        except (OSError, ValueError, TypeError, UnicodeError):
            pass
        overview.append(entry)
    return overview


def _library_audit_cache_path() -> Path:
    """Durable per-user snapshot; not stored inside a Steam library or game."""
    state_home = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return state_home / "amdnr" / "library-audit.json"


def cached_library_audit() -> list[dict[str, object]]:
    """Read the last completed user-requested audit without scanning game files."""
    path = _library_audit_cache_path()
    if not path.exists():
        return []
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Audit snapshot exceeds size limit")
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict) or snapshot.get("format") != 1 or \
                not isinstance(snapshot.get("entries"), list):
            raise ValueError("Unsupported audit snapshot format")
        rows = snapshot["entries"]
        if len(rows) > 5000:
            raise ValueError("Audit snapshot exceeds entry limit")
        result = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            folder = row.get("folder")
            if not isinstance(folder, str) or not Path(folder).is_absolute():
                continue
            if row.get("status") not in (
                "windows_ready", "native_linux", "needs_selection",
                "no_windows_exe", "missing_folder", "scan_incomplete", "scan_error",
                "needs_attention",
            ):
                continue
            # This is intentionally a saved snapshot, not a live check.
            result.append(row)
        return result
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Unable to read saved library audit: {exc}") from exc


def _save_library_audit(rows: list[dict[str, object]]) -> None:
    """Atomically replace the last complete snapshot after an explicit audit."""
    path = _library_audit_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".library-audit-",
            suffix=".tmp", delete=False
        ) as stream:
            temp_name = stream.name
            os.chmod(stream.name, 0o600)
            json.dump({"format": 1, "entries": rows}, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name is not None and os.path.exists(temp_name):
            os.unlink(temp_name)


def library_audit() -> list[dict[str, object]]:
    """Read-only executable readiness inventory for Steam and saved custom games.

    Runs only on explicit request; ordinary Library refresh never scans binaries.
    A recorded AMDNR installation is an inventory marker, not integrity proof.
    """
    entries: list[tuple[str, Path, bool]] = [
        (name, folder, False) for name, folder in steam_games()
    ]
    seen = {str(folder.resolve()) for _, folder, _ in entries}
    for entry in custom_games():
        folder = Path(str(entry["folder"]))
        canonical = str(folder.resolve())
        if canonical not in seen:
            entries.append((str(entry["name"]), folder, True))
            seen.add(canonical)

    results: list[dict[str, object]] = []
    for name, folder, custom in sorted(entries, key=lambda x: x[0].casefold()):
        row: dict[str, object] = {
            "name": name, "folder": str(folder), "custom": custom,
            "status": "needs_attention", "executable": None,
            "source": None, "native": [], "steam_windows_missing": [],
            "installed_record": False,
        }
        try:
            if not folder.is_dir():
                row["status"] = "missing_folder"
                results.append(row)
                continue
            saved = saved_executable(folder)
            # If Steam supplies a unique installed EXE or the user saved one,
            # no costly filesystem crawl is needed for Windows readiness.
            steam = steam_launch_for_directory(folder) if not custom else {}
            row["steam_windows_missing"] = steam.get("windows_missing", [])
            choice = saved or steam.get("selected")
            if choice is not None and Path(choice).is_file():
                row["status"] = "windows_ready"
                row["executable"] = choice
                row["source"] = "saved" if saved else "steam"
            else:
                scan = executable_scan(folder)
                row["native"] = scan["native"]
                choice = next((candidate["path"] for candidate in scan["candidates"]
                               if candidate["auto_select"]), None)
                if choice:
                    row["status"] = "windows_ready"
                    row["executable"] = choice
                    row["source"] = "heuristic"
                elif scan["candidates"]:
                    row["status"] = "needs_selection"
                elif scan["reason"] == "native_linux_files":
                    row["status"] = "native_linux"
                elif scan["partial"]:
                    row["status"] = "scan_incomplete"
                else:
                    row["status"] = "no_windows_exe"
            selected = row["executable"]
            if isinstance(selected, str):
                state = Path(selected).parent / STATE_NAME
                row["installed_record"] = state.is_file()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row["status"] = "scan_error"
        results.append(row)
    return results


def executable_candidates(directory: Path) -> list[dict[str, object]]:
    """Backwards-compatible candidate list for the Linux GUI and CLI."""
    return executable_scan(directory)["candidates"]


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
    """User-confirmed first install, with a durable recovery journal.

    All existing files are backed up and verified before the first destination
    changes. If a normal error occurs, rollback restores the original state.
    If the process is interrupted, Doctor can recover the same transaction.
    """
    import launcher_maintenance as maintenance

    if alias not in ALIASES:
        raise ValueError(f"Unsupported DLL alias: {alias}")
    if (not executable.is_file() or executable.is_symlink() or
            executable.suffix.lower() != ".exe"):
        raise ValueError("Choose the game's actual Windows .exe file")
    root = executable.resolve().parent
    state_file = root / STATE_NAME
    journal = root / maintenance.JOURNAL_NAME
    if journal.exists() or journal.is_symlink():
        raise ValueError("Interrupted AMDNR transaction exists; recover it first")
    if state_file.exists() or state_file.is_symlink():
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
            replacements.append((source, target, relative.as_posix()))
        if not replacements:
            raise ValueError("No compatible files found in archive")
        if len({name.casefold() for _, _, name in replacements}) != len(replacements):
            raise ValueError("Package contains colliding filenames")
        backup = root / BACKUP_NAME / "linux-launcher"
        if backup.exists() or backup.is_symlink():
            raise ValueError(f"Existing backup directory: {backup}; resolve it first")
        records = []
        touched = []
        journal_ready = False
        try:
            backup.mkdir(parents=True, mode=0o700)
            for source, target, name in replacements:
                if target.is_symlink() or (target.exists() and not target.is_file()):
                    raise ValueError(f"Refusing non-regular destination: {target}")
                previous = target.is_file()
                old_sha = _digest(target) if previous else None
                new_sha = _digest(source)
                if previous:
                    previous_copy = maintenance.safe_path(backup, name)
                    previous_copy.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, previous_copy)
                    if _digest(previous_copy) != old_sha or _digest(target) != old_sha:
                        raise ValueError("Original changed during backup: " + name)
                records.append({"path": name, "sha256": new_sha,
                                "backed_up": previous})
                touched.append({"path": name, "previous_sha256": old_sha,
                                "expected_sha256": new_sha})
            record = {"format": 1, "alias": alias, "source_archive": archive.name,
                      "source_sha256": _digest(archive), "files": records}
            record_bytes = (json.dumps(record, sort_keys=True, indent=2) + "\n").encode()
            maintenance.write_json_atomic(journal, {
                "format": 2, "mode": "install", "touched": touched,
                "new_state_sha256": hashlib.sha256(record_bytes).hexdigest(),
            })
            journal_ready = True
            for source, target, _ in replacements:
                maintenance._write_binary_atomic(source, target)
            maintenance.write_json_atomic(state_file, record)
            journal.unlink()
        except Exception:
            if journal_ready:
                # Any third-party change to touched files blocks unsafe
                # rollback and intentionally retains the recovery journal.
                maintenance.restore_transaction(executable)
            elif backup.is_dir() and not backup.is_symlink():
                shutil.rmtree(backup)
            raise
    if alias.lower().endswith(".asi"):
        return "ASI plugins require a compatible ASI loader in the game prefix (no Wine DLL override)."
    override = alias.rsplit(".", 1)[0].lower()
    return f'WINEDLLOVERRIDES="{override}=n,b" %command%'


def uninstall(executable: Path) -> tuple[int, list[str]]:
    root = executable.resolve().parent
    if (root / ".amdnr-linux-transaction.json").exists() or (root / ".amdnr-linux-transaction.json").is_symlink():
        raise ValueError("Interrupted AMDNR update exists; recover it before uninstalling")
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


def installation_report(executable: Path) -> dict[str, object]:
    """Read-only file and backup inventory. Compatible with older v1 records."""
    if not executable.is_file() or executable.suffix.lower() != ".exe":
        raise ValueError("Select an existing Windows game executable")
    root = executable.resolve().parent
    path = root / STATE_NAME
    if not path.exists():
        return {"installed": False, "status": "not_installed", "files": 0}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("format") != 1 or not isinstance(state.get("files"), list):
            raise ValueError("Invalid installation format")
        alias = state.get("alias")
        if alias not in ALIASES:
            raise ValueError("Unrecognized recorded DLL alias")
        valid = missing = modified = backup_missing = 0
        backup = root / BACKUP_NAME / "linux-launcher"
        for item in state["files"]:
            if not isinstance(item, dict):
                raise ValueError("Invalid installation file record")
            relative = item.get("path", "")
            if not isinstance(relative, str) or not _safe_member(relative):
                raise ValueError("Unsafe path in installation record")
            target = root / relative
            _check_destination(target, root)
            if not target.is_file() or target.is_symlink():
                missing += 1
            elif _digest(target) != item.get("sha256"):
                modified += 1
            else:
                valid += 1
            if item.get("backed_up") is True:
                previous = backup / relative
                _check_destination(previous, backup)
                if not previous.is_file() or previous.is_symlink():
                    backup_missing += 1
        source = state.get("source_archive")
        digest = state.get("source_sha256")
        return {
            "installed": True,
            "status": "healthy" if missing + modified + backup_missing == 0 else "needs_attention",
            "alias": alias,
            "files": len(state["files"]),
            "verified": valid, "missing": missing, "modified": modified,
            "backups_missing": backup_missing,
            "source_archive": source if isinstance(source, str) else None,
            "source_sha256": digest if isinstance(digest, str) else None,
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"installed": True, "status": "invalid_record", "error": str(exc)}


def doctor_report(executable: Path | None, archive: Path | None) -> dict[str, object]:
    """Read-only checks; never modify a game or claim Proton GPU compatibility."""
    checks: list[dict[str, object]] = []
    def add_check(name: str, ok: bool, detail: str, pending: bool = False) -> None:
        checks.append({"name": name, "ok": ok, "status": "not_selected" if pending else
                       ("ok" if ok else "problem"), "detail": detail})

    add_check("Linux", sys.platform.startswith("linux"),
              "Native Linux launcher (not a Windows GPU runtime test)")
    libraries = steam_libraries()
    add_check("Steam libraries", bool(libraries), f"{len(libraries)} Steam libraries found")
    add_check("Game executable", executable is not None and executable.is_file()
              and executable.suffix.lower() == ".exe",
              "Windows game executable selected" if executable and executable.is_file()
              else "Select a valid Windows .exe", pending=executable is None)
    add_check("AMDNR release ZIP", archive is not None and archive.is_file()
              and zipfile.is_zipfile(archive),
              "Valid ZIP archive selected" if archive and archive.is_file()
              and zipfile.is_zipfile(archive) else "Select a valid release ZIP", pending=archive is None)
    if executable and executable.is_file():
        root = executable.resolve().parent
        state_path = root / STATE_NAME
        if not state_path.exists():
            add_check("Installation record", False,
                      "No installation managed by this Linux launcher was found beside the EXE",
                      pending=True)
        else:
            report = installation_report(executable)
            if report["status"] == "invalid_record":
                add_check("Installation record", False, str(report["error"]))
            else:
                problems = report["missing"] + report["modified"]
                add_check("Installed AMDNR files", problems == 0,
                          f'{report["verified"]} recorded files verified; '
                          f'{problems} missing or modified')
                if report["backups_missing"]:
                    add_check("Installation backups", False,
                              f'{report["backups_missing"]} original backups missing')
    return {"checks": checks,
            "note": "Diagnostics check only the Linux file installation and local Steam setup. "
                    "They do not certify GPU support, anti-cheat compatibility or Proton rendering."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List detected Steam games")
    parser.add_argument("--other-stores-json", action="store_true", help="Discover Heroic/Lutris installed games")
    parser.add_argument("--releases-json", action="store_true", help="Show upstream AMDNR release packages as JSON")
    parser.add_argument("--doctor-json", action="store_true", help="Read-only launcher and installation diagnostics")
    parser.add_argument("--installation-json", action="store_true", help="Inspect installed files, backups and archive origin")
    parser.add_argument("--installed-games-json", action="store_true", help="Read cached installation records without scanning game files")
    parser.add_argument("--settings-json", action="store_true", help="Read persistent launcher preferences")
    parser.add_argument("--save-settings-base64", metavar="JSON_B64", help="Save validated launcher preferences")
    parser.add_argument("--ini-json", action="store_true", help="Read OptiScaler.ini beside --exe")
    parser.add_argument("--auto-prepare-mochi-model", action="store_true",
                        help="Download and verify optional pinned community source and prepare Mochi")
    parser.add_argument("--accept-community-source", action="store_true",
                        help="Explicit consent to use unofficial third-party NVIDIA binary mirror")
    parser.add_argument("--prepare-mochi-model", type=Path, metavar="NVIDIA_DLL_OR_ZIP",
                        help="Prepare Mochi models locally from verified user-provided NVIDIA DLL")
    parser.add_argument("--runtime-diagnostics-json", action="store_true",
                        help="Read game-local neural runtime file presence without altering files")
    parser.add_argument("--components-json", action="store_true")
    parser.add_argument("--installed-components-json", action="store_true")
    parser.add_argument("--component-preview", metavar="TAG")
    parser.add_argument("--install-component", metavar="TAG")
    parser.add_argument("--replace-component-conflicts", action="store_true")
    parser.add_argument("--remove-component", metavar="ZIP")
    parser.add_argument("--component-asset", metavar="ZIP")
    parser.add_argument("--extensions-json", action="store_true", help="Read installed ASI/DLL plugins and loader state")
    parser.add_argument("--import-extension", type=Path, metavar="ASI", help="Import a local ASI extension without overwrites")
    parser.add_argument("--remove-managed-extension", metavar="NAME", help="Remove an unmodified launcher-managed ASI")
    parser.add_argument("--set-extension-loader", choices=("true", "false"), help="Enable/disable ASI loader with backed-up INI edit")
    parser.add_argument("--save-ini-base64", metavar="TEXT_B64", help="Save OptiScaler.ini with backup")
    parser.add_argument("--save-ini-source", type=Path, metavar="UTF8_FILE", help="Save INI text from temporary UTF-8 input")
    parser.add_argument("--ini-expected-sha", metavar="SHA256", help="Checksum from previous --ini-json read")
    parser.add_argument("--exes-json", type=Path, metavar="GAME_DIR", help="Find game executable candidates")
    parser.add_argument("--exe-scan-json", type=Path, metavar="GAME_DIR", help="Scan Windows executables and report Linux-native builds")
    parser.add_argument("--steam-launch-json", type=Path, metavar="GAME_DIR", help="Read cached Steam launch configuration for game")
    parser.add_argument("--steam-user-options-json", type=Path, metavar="GAME_DIR", help="Read existing Steam launch options and preview combined Proton override")
    parser.add_argument("--saved-exe", type=Path, metavar="GAME_DIR", help="Get a remembered executable")
    parser.add_argument("--remember-exe", type=Path, metavar="GAME_DIR", help="Remember executable selected with --exe")
    parser.add_argument("--download-release", metavar="TAG", help="Download and verify selected AMDNR release")
    parser.add_argument("--release-asset", metavar="ZIP", help="Archive filename for --download-release")
    parser.add_argument("--list-json", action="store_true", help="List games and cached artwork as JSON")
    parser.add_argument("--library-differential-json", action="store_true", help="Reconcile saved library index without binary scanning")
    parser.add_argument("--library-index-exe", type=Path, metavar="GAME_DIR", help="Save a valid chosen executable in library index")
    parser.add_argument("--library-audit-json", action="store_true", help="Read-only executable readiness inventory")
    parser.add_argument("--library-audit-cache-json", action="store_true", help="Read saved audit without scanning games")
    parser.add_argument("--custom-games-json", action="store_true", help="List remembered custom game entries")
    parser.add_argument("--add-custom-game", type=Path, metavar="FOLDER", help="Add custom game directory")
    parser.add_argument("--rename-custom-game", type=Path, metavar="FOLDER", help="Rename custom game entry")
    parser.add_argument("--remove-custom-game", type=Path, metavar="FOLDER", help="Forget custom game entry")
    parser.add_argument("--custom-name", type=str, help="Display name for custom game")
    parser.add_argument("--artwork-report", action="store_true", help="JSON summary of games with missing artwork")
    parser.add_argument("--download-artwork", action="store_true", help="Fetch missing cover art from Steam CDN")
    parser.add_argument("--set-artwork", type=Path, metavar="IMAGE", help="Set cover image (PNG/JPG) for a game")
    parser.add_argument("--game-folder", type=Path, help="Game directory for --set-artwork")
    parser.add_argument("--archive", type=Path, metavar="ZIP", help="Archive path for --doctor-json")
    parser.add_argument("--install", type=Path, metavar="ZIP", help="Install an AMDNR release ZIP")
    parser.add_argument("--repair", type=Path, metavar="ZIP", help="Repair from exact recorded ZIP")
    parser.add_argument("--repair-auto", action="store_true", help="Find and verify the original package automatically")
    parser.add_argument("--update-from", type=Path, metavar="ZIP", help="Safely update installed AMDNR package")
    parser.add_argument("--backup-modified", action="store_true", help="Explicit consent to retain/replace changed tracked files")
    parser.add_argument("--recovery-status", action="store_true", help="Inspect interrupted transaction journal")
    parser.add_argument("--compatibility-json", action="store_true", help="Linux GPU, Proton tools, game process and anti-cheat probe")
    parser.add_argument("--check-launcher-updates", action="store_true", help="Check signed metadata for independent Linux launcher releases")
    parser.add_argument("--download-launcher-update", action="store_true", help="Download and SHA-256 verify latest Linux AppImage")
    parser.add_argument("--apply-launcher-update", type=Path, metavar="APPIMAGE", help="Replace running user-owned AppImage after explicit consent")
    parser.add_argument("--accept-launcher-update", action="store_true", help="Approve replacing the current Linux AppImage")
    parser.add_argument("--proton-profile-json", type=Path, metavar="FOLDER", help="Read game-specific Proton preferences")
    parser.add_argument("--save-proton-profile", type=Path, metavar="FOLDER", help="Save a per-game JSON profile from --profile-json")
    parser.add_argument("--profile-json", type=str, metavar="JSON", help="Proton profile JSON content")
    parser.add_argument("--proton-options-json", type=Path, metavar="FOLDER", help="Show safe combined Steam launch preview")
    parser.add_argument("--support-bundle", action="store_true", help="Create a redacted local diagnostic ZIP")
    parser.add_argument("--recover-transaction", action="store_true", help="Restore crash-recovery snapshot with strict hash checks")
    parser.add_argument("--try-next-proxy", action="store_true", help="Switch clean managed proxy to next unoccupied DLL alias")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall and restore backups")
    parser.add_argument("--bridge-status-json", action="store_true",
                        help="Read-only community ROCm bridge compatibility and conflict status")
    parser.add_argument("--bridge-prepare", type=Path, metavar="COMPILER",
                        help="Download pinned GPL community source and prepare bridge using your own shader compiler")
    parser.add_argument("--bridge-install", action="store_true",
                        help="Install separately managed bridge beside --exe, with explicit approval")
    parser.add_argument("--approve-bridge-install", action="store_true",
                        help="Explicit consent to install the community bridge in the selected game folder")
    parser.add_argument("--bridge-remove", action="store_true",
                        help="Use community manager to restore an installed bridge with consent")
    parser.add_argument("--approve-bridge-remove", action="store_true",
                        help="Explicit consent to remove the separately managed community bridge")
    parser.add_argument("--exe", type=Path, help="Full path to Windows game executable")
    parser.add_argument("--alias", default="dxgi.dll", choices=ALIASES)
    args = parser.parse_args()
    if args.bridge_status_json or args.bridge_prepare is not None or args.bridge_install or args.bridge_remove:
        try:
            import community_bridge
            if args.bridge_status_json:
                result = community_bridge.status(args.exe)
            elif args.bridge_prepare is not None:
                result = community_bridge.prepare(args.bridge_prepare)
            else:
                if args.exe is None:
                    parser.error("--bridge-install/--bridge-remove require --exe")
                if args.bridge_install:
                    result = community_bridge.install(args.exe, args.approve_bridge_install)
                else:
                    result = community_bridge.remove(args.exe, args.approve_bridge_remove)
            print(json.dumps(result, ensure_ascii=False))
            # Bridge commands are complete CLI actions, not a precursor to the
            # legacy Tkinter UI. Never fall through to gui() after success.
            return 0
        except (OSError, ValueError, TypeError, KeyError, TimeoutError,
                RuntimeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    if args.custom_games_json or args.add_custom_game or args.rename_custom_game or args.remove_custom_game:
        try:
            if args.custom_games_json:
                print(json.dumps(custom_games(), ensure_ascii=False))
            elif args.add_custom_game:
                print(json.dumps(add_custom_game(args.add_custom_game, args.custom_name), ensure_ascii=False))
            elif args.rename_custom_game:
                if not args.custom_name:
                    parser.error("--rename-custom-game requires --custom-name")
                rename_custom_game(args.rename_custom_game, args.custom_name)
                print("Custom game renamed")
            else:
                remove_custom_game(args.remove_custom_game)
                print("Custom game entry removed; game files were not changed")
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.other_stores_json:
        try:
            from third_party_stores import external_games
            print(json.dumps(external_games(), ensure_ascii=False))
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.installed_games_json:
        try:
            print(json.dumps(installed_games_overview(), ensure_ascii=False))
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.settings_json or args.save_settings_base64 is not None:
        try:
            if args.settings_json:
                print(json.dumps(launcher_settings(), ensure_ascii=False))
            else:
                import base64
                payload = base64.b64decode(args.save_settings_base64, validate=True)
                if len(payload) > 64 * 1024:
                    raise ValueError("Settings payload too large")
                print(json.dumps(save_launcher_settings(json.loads(payload)), ensure_ascii=False))
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.auto_prepare_mochi_model:
        if args.exe is None:
            parser.error("--auto-prepare-mochi-model requires --exe")
        try:
            print(json.dumps(prepare_mochi_from_community(
                args.exe, consent=args.accept_community_source), ensure_ascii=False))
        except (OSError, ValueError, TypeError, zipfile.BadZipFile) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.prepare_mochi_model is not None:
        if args.exe is None:
            parser.error("--prepare-mochi-model requires --exe")
        try:
            print(json.dumps(prepare_mochi_model(args.exe, args.prepare_mochi_model),
                             ensure_ascii=False))
        except (OSError, ValueError, TypeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.runtime_diagnostics_json:
        if args.exe is None:
            parser.error("--runtime-diagnostics-json requires --exe")
        try:
            print(json.dumps(runtime_diagnostics(args.exe), ensure_ascii=False))
        except (OSError, ValueError, TypeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif (args.components_json or args.installed_components_json or args.component_preview
          or args.install_component or args.remove_component):
        try:
            if args.components_json:
                result = component_catalog()
            else:
                if args.exe is None:
                    parser.error("Component management requires --exe")
                if args.installed_components_json:
                    result = installed_components(args.exe)
                elif args.remove_component:
                    result = remove_component(args.exe, args.remove_component)
                else:
                    if not args.component_asset:
                        parser.error("Component preview/install requires --component-asset")
                    if args.component_preview:
                        result = component_preview(args.exe, args.component_preview, args.component_asset)
                    else:
                        result = install_component(args.exe, args.install_component, args.component_asset,
                                                   replace_conflicts=args.replace_component_conflicts)
            print(json.dumps(result, ensure_ascii=False))
        except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.import_extension is not None or args.remove_managed_extension is not None:
        if args.exe is None:
            parser.error("--import-extension/--remove-managed-extension require --exe")
        try:
            if args.import_extension:
                result = import_extension(args.exe, args.import_extension)
            else:
                result = remove_managed_extension(args.exe, args.remove_managed_extension)
            print(json.dumps(result, ensure_ascii=False))
        except (OSError, ValueError, TypeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.extensions_json or args.set_extension_loader is not None:
        if args.exe is None:
            parser.error("--extensions-json/--set-extension-loader require --exe")
        try:
            if args.extensions_json:
                print(json.dumps(extension_inventory(args.exe), ensure_ascii=False))
            else:
                if not args.ini_expected_sha:
                    parser.error("--set-extension-loader requires --ini-expected-sha")
                print(json.dumps(set_extension_loader(args.exe, args.ini_expected_sha,
                    args.set_extension_loader == "true"), ensure_ascii=False))
        except (OSError, ValueError, UnicodeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.ini_json or args.save_ini_base64 is not None or args.save_ini_source is not None:
        if args.exe is None:
            parser.error("--ini-json/--save-ini-base64 require --exe")
        try:
            if args.ini_json:
                print(json.dumps(ini_snapshot(args.exe), ensure_ascii=False))
            else:
                if not args.ini_expected_sha:
                    parser.error("--save-ini-base64 requires --ini-expected-sha")
                if args.save_ini_source is not None:
                    source = args.save_ini_source
                    if not source.is_file() or source.is_symlink() or \
                            source.stat().st_size > 512 * 1024:
                        raise ValueError("INI source must be a regular file <=512 KiB")
                    payload = source.read_bytes()
                else:
                    import base64
                    payload = base64.b64decode(args.save_ini_base64, validate=True)
                if len(payload) > 512 * 1024:
                    raise ValueError("INI payload too large")
                print(json.dumps(save_game_ini(args.exe, args.ini_expected_sha,
                    payload.decode("utf-8")), ensure_ascii=False))
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif (args.repair or args.repair_auto or args.update_from or args.recovery_status or
          args.recover_transaction or args.try_next_proxy):
        if args.exe is None:
            parser.error("Maintenance operations require --exe")
        try:
            import launcher_maintenance as maintenance
            if args.repair_auto:
                result = maintenance.repair_automatically(args.exe,
                    allow_modified=args.backup_modified)
            elif args.repair:
                result = maintenance.repair_or_update(args.exe, args.repair,
                    allow_modified=args.backup_modified)
            elif args.update_from:
                result = maintenance.repair_or_update(args.exe, args.update_from,
                    update=True, allow_modified=args.backup_modified)
            elif args.recovery_status:
                result = maintenance.status(args.exe)
            elif args.recover_transaction:
                result = maintenance.restore_transaction(args.exe)
            else:
                result = maintenance.next_proxy(args.exe, ALIASES)
            print(json.dumps(result, ensure_ascii=False))
        except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif (args.check_launcher_updates or args.download_launcher_update or args.apply_launcher_update):
        try:
            import launcher_updates as updates
            if args.check_launcher_updates:
                result = updates.check_updates()
            elif args.download_launcher_update:
                result = updates.download_update()
            else:
                result = updates.apply_downloaded_update(
                    args.apply_launcher_update, consent=args.accept_launcher_update)
            print(json.dumps(result, ensure_ascii=False))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif (args.compatibility_json or args.proton_profile_json or args.save_proton_profile or
          args.proton_options_json or args.support_bundle):
        try:
            import linux_environment as environment
            if args.compatibility_json:
                if args.exe is None:
                    parser.error("--compatibility-json requires --exe")
                result = environment.compatibility(args.exe, steam_roots())
            elif args.proton_profile_json:
                result = environment.profile(args.proton_profile_json)
            elif args.save_proton_profile:
                if args.profile_json is None:
                    parser.error("--save-proton-profile requires --profile-json")
                result = environment.save_profile(args.save_proton_profile,
                                                   json.loads(args.profile_json))
            elif args.proton_options_json:
                result = environment.launch_preview(args.proton_options_json, args.alias)
            elif args.support_bundle:
                if args.exe is None:
                    parser.error("--support-bundle requires --exe")
                result = environment.support_bundle(args.exe)
            print(json.dumps(result, ensure_ascii=False))
        except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.installation_json:
        if args.exe is None:
            parser.error("--installation-json requires --exe")
        try:
            print(json.dumps(installation_report(args.exe), ensure_ascii=False))
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.remember_exe is not None:
        if args.exe is None:
            parser.error("--remember-exe requires --exe")
        try:
            print(remember_executable(args.remember_exe, args.exe))
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.saved_exe is not None:
        print(saved_executable(args.saved_exe) or "")
    elif args.steam_user_options_json is not None:
        try:
            print(json.dumps(steam_launch_options_for_directory(args.steam_user_options_json,
                args.alias), ensure_ascii=False))
        except (OSError, ValueError, ImportError) as exc:
            print(json.dumps({"status": "unavailable", "existing": None,
                              "preview": None, "reason": str(exc)}))
    elif args.steam_launch_json is not None:
        print(json.dumps(steam_launch_for_directory(args.steam_launch_json), ensure_ascii=False))
    elif args.exe_scan_json is not None:
        print(json.dumps(executable_scan(args.exe_scan_json), ensure_ascii=False))
    elif args.exes_json is not None:
        print(json.dumps(executable_candidates(args.exes_json), ensure_ascii=False))
    elif args.doctor_json:
        print(json.dumps(doctor_report(args.exe, args.archive), ensure_ascii=False))
    elif args.releases_json or args.download_release:
        try:
            if args.releases_json:
                print(json.dumps(release_catalog(), ensure_ascii=False))
            else:
                if not args.release_asset:
                    parser.error("--download-release requires --release-asset")
                print(download_release(args.download_release, args.release_asset))
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.set_artwork:
        if not args.game_folder:
            parser.error("--set-artwork requires --game-folder")
        try:
            print(set_artwork(args.game_folder, args.set_artwork))
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.install or args.uninstall:
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
    elif args.artwork_report:
        print(json.dumps(artwork_diagnostics(args.download_artwork), ensure_ascii=False, indent=2))
    elif args.library_differential_json:
        try:
            print(json.dumps(differential_library(), ensure_ascii=False))
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.library_index_exe is not None:
        if args.exe is None:
            parser.error("--library-index-exe requires --exe")
        try:
            index_library_executable(args.library_index_exe, args.exe)
            print("Library executable index updated")
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.library_audit_cache_json:
        try:
            print(json.dumps(cached_library_audit(), ensure_ascii=False))
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.library_audit_json:
        try:
            entries = library_audit()
            _save_library_audit(entries)
            # Update executable pointers in the differential index after a
            # deliberate deep scan, without changing user EXE preferences.
            index = _read_library_index()
            for row in entries:
                folder = str(row["folder"])
                if folder in index:
                    index[folder]["executable"] = row.get("executable")
            if index:
                _write_library_index(list(index.values()))
            print(json.dumps(entries, ensure_ascii=False))
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    elif args.list_json:
        print(json.dumps(steam_game_details(args.download_artwork), ensure_ascii=False))
    elif args.list:
        for name, folder in steam_games():
            print(f"{name}\t{folder}")
    else:
        # CLI-only backend. This module must never spawn a second desktop
        # interface when invoked without an explicit action.
        parser.print_help(sys.stderr)
        print("\nNo action specified. Start the native Avalonia launcher for the GUI.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
