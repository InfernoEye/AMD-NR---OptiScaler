#!/usr/bin/env python3
"""Opt-in adapter for the separately maintained AMDNR-Linux GPL-3.0+ bridge.

No third-party source is copied into this repository. A checksum-pinned published
release is downloaded only on explicit Prepare. Its reviewed setup/manage CLI
does the staging and installation with its own backup and recovery records.

This module never writes Steam settings, Proton configurations or game files
without a separate --approve-bridge-install / --approve-bridge-remove action.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

# Only releases reviewed against the setup/manage interface may be executed.
# To approve a future release, review the release diff, verify the downloaded
# source archive hash independently, and add its version/digest here.
SUPPORTED_RELEASES = {
    "0.3.7": "7e4ddb01a352a824bbf6009cfd8a1c0728267679e4a170d33fc8e01f91b84423",
}
VERSION = max(SUPPORTED_RELEASES, key=lambda version: tuple(map(int, version.split("."))))
ARCHIVE = f"AMDNR-Linux-v{VERSION}.tar.gz"
URL = f"https://github.com/hassanm0301/AMDNR-Linux/releases/download/linux-v{VERSION}/{ARCHIVE}"
SHA256 = SUPPORTED_RELEASES[VERSION]
RELEASES_API = "https://api.github.com/repos/hassanm0301/AMDNR-Linux/releases?per_page=30"
RELEASE_TAG = re.compile(r"^linux-v(\d+)\.(\d+)\.(\d+)$")
PROJECT = "https://github.com/hassanm0301/AMDNR-Linux"
SOURCE_ROOT = f"AMDNR-Linux-v{VERSION}"
MAX_ARCHIVE_BYTES = 90 * 1024 * 1024
MAX_UNPACKED_BYTES = 450 * 1024 * 1024
OWN_RECORD = ".amdnr-linux-install.json"  # used by both installers, with incompatible formats

# The latest native lmxxf AMDNR host is separate from the Linux bridge release.
# Exact SHA-256 digests and sizes from the publisher's GitHub release assets.
# No Daniel/NeuralHub runtime is selected or fetched.
HOST_VERSION = "0.3.5.8.28"
HOST_SHA256 = "94cd51e77676156d5f8c2ad760e6ae2347da9a03fdacf29e3b29d0a6d5895aa9"
HOST_SIZE = 550947033
LMXXF_VERSION = "0.4.6.2"
LMXXF_SHA256 = "a0c7344a615be5a810c601f3151d28d4bd22c728353ff2a9bbb31baf6f13b498"
LMXXF_SIZE = 794752422
HOST_ARCHIVE = f"AMDNR-v{HOST_VERSION}.zip"
LMXXF_ARCHIVE = f"AMDNR-lmxxf-{LMXXF_VERSION}.zip"
HOST_RELEASE_URL = f"https://github.com/3zwr1/AMD-NR---OptiScaler/releases/download/Alpha{HOST_VERSION}"
# Published/pinned by AMDNR-Linux v0.3.7. Every selected runtime is
# verified again by manage.stage against the actual host's pass DLL hashes.
DANIEL_VERSIONS = ("0.6.0", "0.5.1", "0.5.0", "0.4.3", "0.4.1", "0.4.0")
RUNTIME_CHOICES = ("lmxxf", *DANIEL_VERSIONS)


def validate_runtime(runtime: str) -> str:
    if runtime not in RUNTIME_CHOICES:
        raise ValueError(f"Unsupported neural runtime: {runtime!r}. Allowed: {', '.join(RUNTIME_CHOICES)}")
    return runtime




def check_releases(*, opener=None) -> dict:
    """Read-only update discovery. Discovery never authorizes third-party code.

    Only SHA-256-reviewed releases in SUPPORTED_RELEASES may be prepared.
    Network errors are surfaced to the caller; no update is silently selected.
    """
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "AMDNR-Avalonia-bridge-release-check"},
    )
    with opener(request, timeout=15) as response:
        if not response.geturl().startswith("https://"):
            raise ValueError("Release lookup redirected to an insecure URL.")
        payload = response.read(256 * 1024 + 1)
        if len(payload) > 256 * 1024:
            raise ValueError("GitHub release listing exceeds size limit.")
    items = json.loads(payload)
    if not isinstance(items, list):
        raise ValueError("GitHub release listing has an unexpected format.")
    releases = []
    seen = set()
    for entry in items:
        if not isinstance(entry, dict) or entry.get("draft") or entry.get("prerelease"):
            continue
        tag = entry.get("tag_name")
        if not isinstance(tag, str) or not RELEASE_TAG.fullmatch(tag) or tag in seen:
            continue
        seen.add(tag)
        version = tag.removeprefix("linux-v")
        filename = f"AMDNR-Linux-v{version}.tar.gz"
        assets = entry.get("assets", [])
        has_source = isinstance(assets, list) and any(
            isinstance(asset, dict) and asset.get("name") == filename
            for asset in assets
        )
        if not has_source:
            continue
        approved = version in SUPPORTED_RELEASES
        releases.append({
            "version": version,
            "tag": tag,
            "approved": approved,
            "compatibility": "reviewed" if approved else "requires_review",
            "download_allowed": approved,
            "published_at": entry.get("published_at"),
        })
    releases.sort(key=lambda item: tuple(map(int, item["version"].split("."))), reverse=True)
    latest = releases[0]["version"] if releases else None
    return {
        "provider": "hassanm0301/AMDNR-Linux",
        "installed_adapter_version": VERSION,
        "approved_versions": sorted(SUPPORTED_RELEASES, key=lambda v: tuple(map(int, v.split("."))), reverse=True),
        "latest_upstream_version": latest,
        "newer_upstream_available": bool(latest and
            tuple(map(int, latest.split("."))) > tuple(map(int, VERSION.split(".")))),
        "releases": releases,
        "updated_automatically": False,
        "notice": "New upstream versions require archive checksum and setup/manage API review before preparation. "
                  "Discovering a release does not establish GPU, Proton or game compatibility.",
    }


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


def prepared_path(runtime: str = "lmxxf") -> Path:
    # Preserve the old v0.3.5.6 staged package and other runtime selections.
    runtime = validate_runtime(runtime)
    return cache_dir() / f"package-amdnr-{HOST_VERSION}-{runtime}"


def package_is_ready(package: Path, runtime: str = "lmxxf") -> bool:
    """Only recognize a complete staged bundle for the chosen AMDNR host."""
    runtime = validate_runtime(runtime)
    marker = package / "amdnr-linux/SOURCE.txt"
    components = package / "amdnr-linux/components.json"
    try:
        if not (package / "amdnr-linux/run.sh").is_file() or not (package / "d3d12.dll").is_file():
            return False
        if not marker.is_file() or marker.is_symlink() or not components.is_file():
            return False
        description = marker.read_text(encoding="utf-8")
        config = json.loads(components.read_text(encoding="utf-8"))
        return (f"Host/runtime: AMDNR {HOST_VERSION}," in description and
                f"Archive SHA-256: {HOST_SHA256}" in description and
                f"SHA-256 {LMXXF_SHA256}" in description and
                config.get("neural_runtime") == ("lmxxf" if runtime == "lmxxf" else "daniel") and
                (runtime == "lmxxf" or config.get("daniel", {}).get("version") == runtime))
    except (OSError, ValueError, UnicodeError):
        return False


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


def status(exe: Path | None = None, runtime: str = "lmxxf") -> dict:
    runtime = validate_runtime(runtime)
    src = source_path()
    package = prepared_path(runtime)
    archive = cache_dir() / ARCHIVE
    report = {
        "provider": "hassanm0301/AMDNR-Linux",
        "source": PROJECT,
        "version": VERSION,
        "approved_versions": sorted(SUPPORTED_RELEASES),
        "release_approval": "reviewed_sha256_pin",
        "updates_checked_online": False,
        "license": "GPL-3.0-or-later; LGPL vkd3d; upstream third-party notices",
        "archive_sha256": SHA256,
        "release_verified": archive.is_file() and not archive.is_symlink()
            and file_hash(archive) == SHA256,
        "source_ready": (src / "RELEASE-MANIFEST.json").is_file()
            and (src / "linux/setup.py").is_file(),
        "prepared": package_is_ready(package, runtime),
        "selected_runtime": runtime,
        "runtime_choices": RUNTIME_CHOICES,
        "host_version": HOST_VERSION,
        "lmxxf_version": LMXXF_VERSION,
        "legacy_prepared": (cache_dir() / "package/amdnr-linux/run.sh").is_file(),
        "required_proton": "Wine 11-based Proton (tested GE-Proton11-9)",
        "tested_gpu": "RX 9070 XT; other GPUs not validated",
        "steam_options_unchanged": True,
    }
    if exe is not None:
        from bridge_migration import pending_snapshot
        pending = pending_snapshot(exe)
        report["migration_pending"] = pending is not None
        report["migration_snapshot"] = str(pending) if pending else None
        report["exe"] = str(exe)
        report["community_installed"] = (exe.parent / "amdnr-linux/run.sh").is_file()
        report["installed_runtime"] = None
        components = exe.parent / "amdnr-linux/components.json"
        if report["community_installed"] and components.is_file() and not components.is_symlink():
            try:
                config = json.loads(components.read_text(encoding="utf-8"))
                neural = config.get("neural_runtime")
                if neural == "lmxxf":
                    report["installed_runtime"] = "lmxxf"
                elif neural == "daniel" and isinstance(config.get("daniel"), dict):
                    version = config["daniel"].get("version")
                    if version in DANIEL_VERSIONS:
                        report["installed_runtime"] = version
            except (OSError, ValueError, UnicodeError):
                pass
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


# Versioned compatibility fix for the exact v0.3.7 release. Both the
# downloaded Debian archive and this source release are checksum-verified.
# Only this precise dependency entry is changed, and only in the private cache.
UPSTREAM_LIBELF_PIN = (
    'e/elfutils/libelf1_0.186-1ubuntu0.1_amd64.deb", '
    '"2cc781614b045b450a1e073ee3b0902f393ee58ede1d2ea4526ad805fcccf538"'
)
REVIEWED_LIBELF_PIN = (
    'e/elfutils/libelf1_0.188-1~bpo22.04.1_amd64.deb", '
    '"280b71b2f310fa637e325a4923db4c634964994de1a75f5e5770ef6247179c55"'
)


def apply_reviewed_libelf_pin(src: Path) -> bool:
    """Patch one old upstream dependency tuple, never relax SHA-256 checking.

    Returns True when an update was applied and False if already updated.
    Rejects unknown upstream script layouts instead of guessing at a patch.
    """
    if VERSION != "0.3.7":
        raise ValueError("libelf compatibility patch is only reviewed for linux-v0.3.7")
    script = src / "linux/fetch-rocm.py"
    if not script.is_file() or script.is_symlink():
        raise ValueError("Expected regular upstream linux/fetch-rocm.py is missing.")
    content = script.read_text(encoding="utf-8")
    if content.count(REVIEWED_LIBELF_PIN) == 1 and UPSTREAM_LIBELF_PIN not in content:
        return False
    if content.count(UPSTREAM_LIBELF_PIN) != 1 or REVIEWED_LIBELF_PIN in content:
        raise ValueError("Unrecognized upstream libelf pin; refusing to alter source.")
    revised = content.replace(UPSTREAM_LIBELF_PIN, REVIEWED_LIBELF_PIN, 1)
    # This script lives only under the verified release's private extraction.
    script.write_text(revised, encoding="utf-8")
    return True


# Upstream v0.3.7 stages only older hosts. This narrowly updates its
# verified, private source copy; no upstream archive, game or system file is
# changed. Any unexpected upstream layout is rejected.
UPSTREAM_DEFAULT_HOST = 'RELEASE_VERSION = "0.3.5.6"'
UPDATED_DEFAULT_HOST = f'RELEASE_VERSION = "{HOST_VERSION}"'
UPSTREAM_HOST_ENTRY = '    "a11143327ede14ff4d7fe50ea0ce9d148320aeec4cd163f11c8c9973c944a97d": "0.3.5.8R2",'
UPDATED_HOST_ENTRY = f'    "{HOST_SHA256}": "{HOST_VERSION}",'
UPSTREAM_LMXXF_ENTRY = 'LMXXF_ARCHIVES = {'
UPDATED_LMXXF_ENTRY = (
    'LMXXF_ARCHIVES = {\n'
    f'    "{HOST_VERSION}": runtimes.Download(\n'
    f'        "{LMXXF_ARCHIVE}", "{LMXXF_VERSION}",\n'
    f'        "{HOST_RELEASE_URL}/{LMXXF_ARCHIVE}",\n'
    f'        "{LMXXF_SHA256}", {LMXXF_SIZE}),'
)


def apply_current_amdnr_pin(src: Path) -> bool:
    """Opt into a digest-pinned native lmxxf AMDNR host, not NeuralHub.

    Preserve the Linux bridge's old host whitelist and add one reviewed tuple.
    Refuse to modify unexpected private source or skip a hash check.
    """
    if VERSION != "0.3.7":
        raise ValueError("Current AMDNR adapter only applies to Linux bridge v0.3.7")
    manager = src / "linux/manage.py"
    setup = src / "linux/setup.py"
    for path in (manager, setup):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing regular verified upstream script: {path.name}")
    original_manager = manager.read_text(encoding="utf-8")
    original_setup = setup.read_text(encoding="utf-8")
    if (original_manager.count(UPDATED_HOST_ENTRY) == 1 and
            original_manager.count(UPDATED_LMXXF_ENTRY) == 1 and
            original_setup.count(UPDATED_DEFAULT_HOST) == 1 and
            UPSTREAM_DEFAULT_HOST not in original_setup):
        return False
    if (original_manager.count(UPSTREAM_HOST_ENTRY) != 1 or
            original_manager.count(UPSTREAM_LMXXF_ENTRY) != 1 or
            UPDATED_HOST_ENTRY in original_manager or
            UPDATED_LMXXF_ENTRY in original_manager or
            original_setup.count(UPSTREAM_DEFAULT_HOST) != 1):
        raise ValueError("Unexpected upstream host-staging interface; refusing current AMDNR override.")
    amended_manager = original_manager.replace(
        UPSTREAM_HOST_ENTRY, UPSTREAM_HOST_ENTRY + "\n" + UPDATED_HOST_ENTRY, 1
    ).replace(UPSTREAM_LMXXF_ENTRY, UPDATED_LMXXF_ENTRY, 1)
    amended_setup = original_setup.replace(UPSTREAM_DEFAULT_HOST, UPDATED_DEFAULT_HOST, 1)
    # Both files live solely under the already checksum-verified private source.
    manager.write_text(amended_manager, encoding="utf-8")
    setup.write_text(amended_setup, encoding="utf-8")
    return True


def preparer_python() -> str:
    """Find an existing Python 3.12+ with zstd support, without installing packages."""
    candidates = [sys.executable, shutil.which("python3.14"), shutil.which("python3.13"),
                  shutil.which("python3.12"), "/usr/bin/python3", shutil.which("python3")]
    checked = set()
    for candidate in candidates:
        if not candidate or candidate in checked or not Path(candidate).is_file():
            continue
        checked.add(candidate)
        try:
            test = subprocess.run(
                [str(candidate), "-c",
                 "import sys; assert sys.version_info >= (3,12); "
                 "import importlib.util; "
                 "assert sys.version_info >= (3,14) or importlib.util.find_spec('zstandard') is not None"],
                capture_output=True, timeout=7, check=False)
            if test.returncode == 0:
                return str(candidate)
        except (OSError, subprocess.TimeoutExpired):
            pass
    raise ValueError(
        "Community preparation needs Python 3.12+ with the 'zstandard' module "
        "(or Python 3.14+ with built-in compression.zstd). Install that module "
        "for your system Python and retry; no system packages are installed automatically.")


def prepare(compiler: Path, runtime: str = "lmxxf") -> dict:
    runtime = validate_runtime(runtime)
    interpreter = preparer_python()
    from bridge_discovery import compiler_is_candidate
    if not compiler_is_candidate(compiler):
        raise ValueError("The chosen d3dcompiler_47.dll is not a regular x64 PE file. "
                         "Choose a native x64 compiler from software you own.")
    if prepared_path(runtime).exists():
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
    # The verified upstream release has an unavailable libelf1 0.186 pin.
    # Fetch a replacement under a reviewed SHA-256 pin, then update the exact
    # matching upstream fetch-rocm tuple in the private extracted source.
    # Other upstream dependencies and integrity checking remain unchanged.
    from bridge_deps import reuse_or_fetch_pinned_ubuntu_packages
    dependency_actions = reuse_or_fetch_pinned_ubuntu_packages(cache_dir() / "upstream-cache")
    if apply_reviewed_libelf_pin(src):
        dependency_actions.append("Applied reviewed libelf1 0.188 pin to private upstream fetch script")
    if apply_current_amdnr_pin(src):
        dependency_actions.append(f"Selected SHA-256 pinned AMDNR {HOST_VERSION} and lmxxf {LMXXF_VERSION}")
    command = [interpreter, str(src / "linux/setup.py"), "prepare",
               "--compiler", str(compiler.resolve()),
               "--output", str(prepared_path(runtime)),
               "--cache", str(cache_dir() / "upstream-cache")]
    if runtime != "lmxxf":
        command.extend(["--daniel-runtime", runtime])
    # Running third-party GPL setup code requires the user's separate Prepare
    # click. It fetches pinned upstream AMDNR/ROCm assets into our private cache.
    finished = subprocess.run(command, cwd=src, text=True, capture_output=True,
                              timeout=2400, check=False)
    if finished.returncode:
        raise ValueError("Community setup failed (exit %d): %s" %
                         (finished.returncode, (finished.stdout + "\n" + finished.stderr)[-5000:]))
    if not package_is_ready(prepared_path(runtime), runtime):
        raise ValueError("Community setup did not stage the expected current AMDNR/lmxxf package.")
    return {"prepared": True, "package": str(prepared_path(runtime)), "host_version": HOST_VERSION,
            "selected_runtime": runtime,
            "provider": PROJECT, "dependency_actions": dependency_actions,
            "output": finished.stdout[-1500:]}


def install(exe: Path, approved: bool, runtime: str = "lmxxf", *, replace_existing: bool = False) -> dict:
    runtime = validate_runtime(runtime)
    if not approved:
        raise ValueError("Bridge installation requires explicit user approval.")
    folder = _game_directory(exe)
    report = status(exe, runtime)
    if not report["prepared"]:
        raise ValueError("Prepare the checksum-verified community package first.")
    if report.get("community_installed"):
        raise ValueError("An existing community bridge is installed. Restore it using its managed "
                         "uninstaller before installing a different runtime.")
    from bridge_migration import pending_snapshot
    pending = pending_snapshot(exe)
    if pending is not None:
        raise ValueError(f"Unfinished migration at {pending}; recover it before installation.")
    if report["conflicts"] and not replace_existing:
        raise ValueError("Existing game hooks require explicit backup-and-replace approval:\n" +
                         "\n".join(report["conflicts"]))
    manager = source_path() / "linux/manage.py"
    if not manager.is_file():
        raise ValueError("Verified community management tool is missing.")
    # Recheck just before writing; deliberate replacement is a separate action.
    if game_conflicts(exe) and not replace_existing:
        raise ValueError("Files changed since preview. Reopen compatibility checks.")
    snapshot = None
    if replace_existing:
        from launcher_maintenance import _ensure_not_running
        _ensure_not_running(exe)
        from bridge_migration import snapshot_existing
        snapshot = snapshot_existing(exe).get("snapshot")
    command = [sys.executable, str(manager), "install", str(prepared_path(runtime)),
               str(folder), "--exe", str(exe.resolve()), "--proxy", "auto"]
    try:
        finished = subprocess.run(command, cwd=source_path(), text=True,
                                  capture_output=True, timeout=300, check=False)
        if finished.returncode:
            raise ValueError("Community manager refused installation:\n" +
                             (finished.stdout + "\n" + finished.stderr)[-4000:])
    except Exception as error:
        if snapshot is not None:
            from bridge_migration import restore_snapshot
            restored = restore_snapshot(Path(snapshot))
            if restored["blocked"]:
                raise ValueError(
                    f"Installation failed; original files retained in {snapshot}. "
                    "Bridge files occupy some original paths. Review managed uninstall "
                    "and recover the migration before retrying. " +
                    "; ".join(restored["blocked"])) from error
        raise
    if snapshot is not None:
        from bridge_migration import mark_installed
        mark_installed(Path(snapshot))
    wrapper = folder / "amdnr-linux/run.sh"
    return {"installed": True, "exe": str(exe), "manager": PROJECT,
            "migration_snapshot": snapshot,
            "launch_option_preview": f'"{wrapper}" %command%',
            "steam_modified": False,
            "warning": "Copy launch option manually. On first game launch the wrapper "
                       "will modify the existing Proton prefix with journaled HIP/compiler files. "
                       "Preserve the community installation folder and backups.",
            "output": finished.stdout[-1600:]}


def steam_launch_preview(exe: Path, *, steam_report: dict | None = None,
                         manual_options: str | None = None) -> dict:
    """Read-only bridge launch preview using Steam's active userdata when unambiguous.

    Existing launch options are never written. Only aliases from verified v1
    records preserved in the migration snapshot may be dropped automatically.
    """
    from bridge_migration import game_root, latest_installed_snapshot
    from steam_user_launch import preview_bridge_launch
    if not exe.is_file() or exe.is_symlink():
        raise ValueError("Selected game executable is missing.")
    wrapper = exe.resolve().parent / "amdnr-linux/run.sh"
    aliases = set()
    snapshot = latest_installed_snapshot(exe)
    if snapshot is not None:
        original = snapshot / "original"
        for record in original.rglob(".amdnr-linux-install.json"):
            if record.is_symlink() or not record.is_file() or not record.resolve().is_relative_to(original.resolve()):
                continue
            if record.stat().st_size > 4 * 1024 * 1024:
                continue
            try:
                payload = json.loads(record.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeError):
                continue
            if payload.get("format") != 1 or not isinstance(payload.get("files"), list):
                continue
            alias = payload.get("alias")
            if isinstance(alias, str) and alias.casefold() in (
                    "dxgi.dll", "version.dll", "winmm.dll", "winhttp.dll",
                    "wininet.dll", "dbghelp.dll", "d3d12.dll"):
                aliases.add(alias)
    if steam_report is None:
        steam_report = {"status": "unavailable", "existing": None}
    steam_status = steam_report.get("status", "unavailable")
    current = manual_options if manual_options is not None else (
        steam_report.get("existing") if steam_status in ("found", "empty") else None)
    if current is not None and not isinstance(current, str):
        raise ValueError("Unexpected launch options type.")
    result = preview_bridge_launch(current, str(wrapper), tuple(sorted(aliases)))
    result.update({
        "steam_status": "manual" if manual_options is not None else steam_status,
        "existing": current,
        "managed_aliases": sorted(aliases),
        "wrapper": str(wrapper),
        "steam_modified": False,
        "proton_modified": False,
        "instruction": "Paste the reviewed final preview into Steam > Game Properties > General > Launch Options.",
    })
    return result


def recover_migration(exe: Path, approved: bool) -> dict:
    if not approved:
        raise ValueError("Migration recovery requires explicit user approval.")
    from bridge_migration import recover_pending
    return recover_pending(exe)


def remove(exe: Path, approved: bool, *, restore_previous: bool = True,
           force: bool = False) -> dict:
    if not approved:
        raise ValueError("Community bridge removal requires explicit consent.")
    if force and restore_previous:
        raise ValueError("Force removal cannot automatically restore a previous AMDNR installation.")
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
    if force:
        from launcher_maintenance import _ensure_not_running
        _ensure_not_running(exe)
        from bridge_force_remove import preserve_changed_bridge_files
        preserved_bridge = preserve_changed_bridge_files(folder, data)
    else:
        preserved_bridge = None
    command = [sys.executable, str(manager), "uninstall", str(folder)]
    if force:
        command.append("--force")  # reviewed v0.3.7 manager's explicit force mode
    finished = subprocess.run(command,
                              cwd=source_path(), text=True, capture_output=True, timeout=300)
    fallback = None
    if finished.returncode:
        if not force:
            raise ValueError("Uninstall stopped; inspect changed files before retrying: " +
                             (finished.stdout + "\n" + finished.stderr)[-4000:])
        from bridge_force_remove import quarantine_recorded_bridge
        fallback = quarantine_recorded_bridge(folder, data)
    migration = None
    from bridge_migration import (latest_installed_snapshot, restore_snapshot,
                                  retain_after_full_uninstall)
    old_snapshot = latest_installed_snapshot(exe)
    if old_snapshot is not None:
        migration = (restore_snapshot(old_snapshot) if restore_previous
                     else retain_after_full_uninstall(old_snapshot))
        if restore_previous and migration["blocked"]:
            raise ValueError("Bridge uninstalled, but some original files could not be restored. "
                             f"Recovery snapshot: {old_snapshot}; blocked: " +
                             ", ".join(migration["blocked"]))
    return {"removed": True, "migration_restoration": migration, "steam_modified": False,
            "preserved_bridge": preserved_bridge, "forced": force,
            "fallback": fallback, "prefix_recovery_required": bool(fallback),
            "previous_install_restored": restore_previous,
            "warning": ("Remove the bridge wrapper from Steam launch options manually. " +
                        ("Upstream force removal failed; owned files were quarantined, but Proton "
                         "prefix recovery requires manual review." if fallback else "")),
            "output": finished.stdout[-1000:]}
