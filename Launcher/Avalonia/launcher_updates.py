"""Opt-in SHA-256 verified Linux AppImage update checks and safe local replacement.

Launcher releases originate from the user's Linux fork; game mod packages remain
pinned to the official 3zwr1 upstream and never use this update service.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import urllib.request


REPO = "InfernoEye/AMD-NR---OptiScaler"
RELEASES = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
ASSET = "AMDNR-Linux-x86_64.AppImage"
MAX_PACKAGE = 850 * 1024 * 1024
LINUX_TAG = re.compile(r"linux-v(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z0-9.-]+))?")


def _github_json() -> object:
    request = urllib.request.Request(RELEASES, headers={
        "User-Agent": "AMDNR-Linux-Launcher/1.0", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=15) as result:
        raw = result.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Update catalog too large")
    return json.loads(raw)


def version_tuple(text: str) -> tuple[int, int, int] | None:
    match = LINUX_TAG.fullmatch(text)
    return tuple(map(int, match.groups()[:3])) if match else None


def current_tag() -> str:
    location = Path(__file__).with_name("VERSION")
    if location.is_file() and not location.is_symlink() and location.stat().st_size < 128:
        value = location.read_text().strip()
        if version_tuple(value) is not None:
            return value
    return "development"


def check_updates() -> dict:
    entries = _github_json()
    if not isinstance(entries, list):
        raise ValueError("Unrecognized Linux release catalog")
    candidate = []
    for release in entries:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name")
        if not isinstance(tag, str) or version_tuple(tag) is None:
            continue
        assets = release.get("assets")
        if not isinstance(assets, list):
            continue
        archive = next((a for a in assets if isinstance(a, dict) and
                        a.get("name") == ASSET), None)
        if archive is None:
            continue
        size, sha = archive.get("size"), archive.get("digest")
        if (not isinstance(size, int) or not 0 < size <= MAX_PACKAGE or
                not isinstance(sha, str) or
                not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", sha)):
            continue
        candidate.append((version_tuple(tag), {
            "tag": tag, "size": size, "sha256": sha[7:].lower(),
            "name": ASSET, "published": release.get("published_at"),
        }))
    candidate.sort(key=lambda t: t[0], reverse=True)
    latest = candidate[0][1] if candidate else None
    local = current_tag()
    local_version = version_tuple(local)
    newer = bool(latest and (local_version is None or
                             version_tuple(latest["tag"]) > local_version))
    return {"current": local, "latest": latest, "available": newer,
            "source": REPO, "format": "AppImage", "automatic_install": False,
            "note": "Opt in to download. Installation requires a user-owned running AppImage."}


def _updates_dir() -> Path:
    base = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    return base / "amdnr" / "updates"


def download_update() -> dict:
    status = check_updates()
    latest = status["latest"]
    if not status["available"] or latest is None:
        return {"status": "already_current", "current": status["current"]}
    target_dir = _updates_dir() / latest["tag"]
    target_dir.mkdir(parents=True, exist_ok=True)
    if target_dir.is_symlink():
        raise ValueError("Unsafe update cache folder")
    target = target_dir / ASSET
    def digest(path):
        sha = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(chunk)
        return sha.hexdigest()
    if target.is_file() and not target.is_symlink() and (
            target.stat().st_size == latest["size"] and
            digest(target) == latest["sha256"]):
        return {"status": "downloaded", "file": str(target), "version": latest["tag"]}
    url = (f"https://github.com/{REPO}/releases/download/"
           f"{latest['tag']}/{ASSET}")
    request = urllib.request.Request(url, headers={"User-Agent": "AMDNR-Linux-Launcher/1.0"})
    fd, temp_name = tempfile.mkstemp(prefix=".update-", dir=target_dir)
    temp = Path(temp_name)
    try:
        count = 0
        hasher = hashlib.sha256()
        with os.fdopen(fd, "wb") as stream, urllib.request.urlopen(request, timeout=60) as response:
            for block in iter(lambda: response.read(1024 * 1024), b""):
                count += len(block)
                if count > latest["size"] or count > MAX_PACKAGE:
                    raise ValueError("Downloaded AppImage exceeds advertised size")
                hasher.update(block)
                stream.write(block)
            stream.flush()
            os.fsync(stream.fileno())
        if count != latest["size"] or hasher.hexdigest() != latest["sha256"]:
            raise ValueError("AppImage failed published SHA-256 verification")
        os.chmod(temp, 0o700)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return {"status": "downloaded", "file": str(target), "version": latest["tag"]}


def apply_downloaded_update(source: Path, *, consent: bool = False) -> dict:
    """Replace only the currently running user-owned AppImage, after explicit click."""
    if not consent:
        raise ValueError("AppImage update requires explicit approval")
    current = os.environ.get("APPIMAGE")
    if not current:
        raise ValueError("Not running as AppImage; use downloaded package manually")
    original = Path(current)
    if (original.is_symlink() or not original.is_file() or
            original.suffix != ".AppImage" or original.stat().st_uid != os.getuid() or
            not os.access(original.parent, os.W_OK)):
        raise ValueError("Current AppImage cannot be replaced safely")
    if (source.is_symlink() or not source.is_file() or
            source.name != ASSET or not source.resolve().is_relative_to(_updates_dir().resolve())):
        raise ValueError("Select an already downloaded verified AppImage")
    status = check_updates()
    latest = status.get("latest")
    if latest is None or source.parent.name != latest["tag"]:
        raise ValueError("Downloaded update is no longer the latest approved release")
    if source.stat().st_size != latest["size"]:
        raise ValueError("Downloaded update size changed")
    sha = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    if sha.hexdigest() != latest["sha256"]:
        raise ValueError("Downloaded update SHA-256 mismatch")
    backup = original.with_name(original.name + ".amdnr-previous")
    if backup.exists() or backup.is_symlink():
        raise ValueError("Previous launcher backup already exists; inspect before replacing")
    fd, temp_name = tempfile.mkstemp(prefix=".amdnr-updater-", dir=original.parent)
    staged = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(staged, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        os.rename(original, backup)
        try:
            os.replace(staged, original)
        except Exception:
            os.replace(backup, original)
            raise
    finally:
        staged.unlink(missing_ok=True)
    return {"status": "applied", "version": latest["tag"],
            "restart_required": True, "previous_launcher": str(backup),
            "message": "Quit and restart the AppImage to use the update."}
