"""Read-only host-library checks and pinned Ubuntu package cache recovery.

The community bridge uses a *private*, version-pinned ROCm runtime. We do not
substitute random host .so files for its pinned packages. Local .deb archives
can be reused ONLY when their SHA-256 matches upstream's exact package pin.
Fallback downloads from Ubuntu mirrors are approved by the same explicit
Prepare click, and are SHA-256 verified before upstream setup sees them.
No root, package-manager calls or modifications to system libraries.
"""
from __future__ import annotations

import ctypes.util
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import urllib.error
import urllib.request

# Exact upstream AMDNR-Linux linux-v0.3.7 fetch-rocm.py pins.
UBUNTU_PACKAGES = (
    ("libelf1_0.186-1ubuntu0.1_amd64.deb",
     "2cc781614b045b450a1e073ee3b0902f393ee58ede1d2ea4526ad805fcccf538",
     "e/elfutils"),
    ("libnuma1_2.0.14-3ubuntu2_amd64.deb",
     "0721c89001fbbd1ada23e89da5d60e762763c1a7b3dc814a2e9a518480a8043d",
     "n/numactl"),
)
UBUNTU_MIRRORS = (
    # Historic pinned files can disappear from the canonical archive while
    # remaining on mirrors. Every archive is verified against the exact
    # upstream SHA-256, independent of which mirror supplies the bytes.
    "https://security.ubuntu.com/ubuntu/pool/main/",
    "https://archive.ubuntu.com/ubuntu/pool/main/",
    "https://old-releases.ubuntu.com/ubuntu/pool/main/",
    "https://mirrors.edge.kernel.org/ubuntu/pool/main/",
    "https://ftp.task.gda.pl/ubuntu/pool/main/",
    "https://mirror.fem-net.de/ubuntu/pool/main/",
    "https://distro.ibiblio.org/ubuntu/ubuntu/pool/main/",
)
MAX_PACKAGE_SIZE = 8 * 1024 * 1024


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def distro_info(os_release: Path = Path("/etc/os-release")) -> dict[str, str]:
    result = {}
    try:
        for line in os_release.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                result[key] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return result


def host_library_status() -> dict:
    """Only detect presence. No loading, executing, importing GPU drivers or edits."""
    found = {"libelf.so.1": bool(ctypes.util.find_library("elf")),
             "libnuma.so.1": bool(ctypes.util.find_library("numa"))}
    distro = distro_info()
    distribution = distro.get("ID", "unknown").lower()
    version = distro.get("VERSION_ID", "")
    if distribution in ("ubuntu", "debian", "linuxmint", "pop"):
        package_elf = "libelf1" if (distribution == "ubuntu" and version.startswith("22.")) or (distribution == "debian" and version.startswith(("11", "12"))) else "libelf1t64"
        command = f"sudo apt install {package_elf} libnuma1"
    elif distribution in ("arch", "endeavouros", "manjaro", "cachyos"):
        command = "sudo pacman -S --needed elfutils numactl"
    elif distribution in ("fedora", "rhel", "centos"):
        command = "sudo dnf install elfutils-libelf numactl-libs"
    elif distribution in ("opensuse", "opensuse-tumbleweed", "opensuse-leap"):
        command = "sudo zypper install libelf1 libnuma1"
    else:
        command = ""
    return {
        "distro": distro.get("PRETTY_NAME", distribution),
        "system_libraries": found,
        "missing_system_libraries": [name for name, available in found.items() if not available],
        "install_command_preview": command,
        "system_packages_will_be_installed": False,
        "private_rocm_required": True,
        "explanation": "The community bridge stages pinned ROCm libraries privately. "
                       "Installed system libelf/libnuma are checked for diagnostics, "
                       "not substituted for version-pinned private runtime packages.",
    }


def reuse_or_fetch_pinned_ubuntu_packages(cache: Path,
                                          apt_cache: Path = Path("/var/cache/apt/archives"),
                                          *, opener=None) -> list[str]:
    """Recover exact hash-pinned .deb files before unmodified upstream setup.

    All writes are under the launcher's private cache. Never trust a same-named
    system package without checking the full archive SHA-256.
    """
    cache.mkdir(parents=True, exist_ok=True)
    opener = opener or urllib.request.urlopen
    actions = []
    for filename, digest, suffix in UBUNTU_PACKAGES:
        target = cache / filename
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError(f"Untrusted cached package path: {target}")
        if target.is_file():
            if sha256(target) != digest:
                raise ValueError(f"Existing cached package checksum mismatch: {filename}")
            actions.append("Already pinned in private cache: " + filename)
            continue
        local = apt_cache / filename
        if local.is_file() and not local.is_symlink() and sha256(local) == digest:
            handle, pending = tempfile.mkstemp(prefix=".ubuntu-pin-", dir=cache)
            try:
                with os.fdopen(handle, "wb") as file, local.open("rb") as source:
                    shutil.copyfileobj(source, file)
                if sha256(Path(pending)) != digest:
                    raise ValueError("Local package changed while copying: " + filename)
                os.replace(pending, target)
            finally:
                Path(pending).unlink(missing_ok=True)
            actions.append("Reused verified distro package cache: " + filename)
            continue

        errors = []
        for mirror in UBUNTU_MIRRORS:
            url = mirror + suffix + "/" + filename
            pending = None
            try:
                handle, pending = tempfile.mkstemp(prefix=".ubuntu-pin-", dir=cache)
                size = 0
                with os.fdopen(handle, "wb") as file, opener(url, timeout=30) as response:
                    if not response.geturl().startswith("https://"):
                        raise ValueError("Package mirror redirected to an insecure URL")
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        size += len(block)
                        if size > MAX_PACKAGE_SIZE:
                            raise ValueError("Pinned package exceeds size limit")
                        file.write(block)
                if sha256(Path(pending)) != digest:
                    raise ValueError("Downloaded pinned package checksum mismatch")
                os.replace(pending, target)
                actions.append("Downloaded SHA-256 verified Ubuntu package: " + filename)
                break
            except (OSError, ValueError, urllib.error.URLError) as exc:
                errors.append(f"{mirror.split('/')[2]}: {exc}")
            finally:
                if pending is not None:
                    Path(pending).unlink(missing_ok=True)
        else:
            raise ValueError(
                f"Unable to obtain upstream's pinned {filename} from Ubuntu mirrors. "
                "System libraries alone do not replace the required verified private "
                "ROCm package. Preparation stopped safely; no system packages changed. "
                + "; ".join(errors))
    return actions
