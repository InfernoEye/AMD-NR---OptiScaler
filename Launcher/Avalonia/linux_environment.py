"""Read-only Linux/Proton diagnostics and opt-in per-game profile helpers.

No Steam file is modified; any launch command generated here is a preview.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import tempfile
from datetime import datetime, timezone
import zipfile


MAX_LOG = 2 * 1024 * 1024
MAX_PERF_CSV = 32 * 1024 * 1024
LOG_NAMES = ("OptiScaler.log", "OptiScaler.txt", "AMDNR.log",
             "OptiScaler.ini", "MochizukiNrRuntime.log", "DLSSNR.log")
TOKEN_RE = re.compile(r"(?i)(token|secret|password|authorization|apikey)\s*[:=]\s*([^\s,;]+)")
CHEAT_NAMES = ("easyanticheat", "battleye", "beservice", "ricochet",
               "vgk.sys", "vanguard", "xigncode", "nprotect")
GPU_DRIVERS = {"0x1002": "AMD", "0x10de": "NVIDIA", "0x8086": "Intel"}


def _config_root() -> Path:
    return Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "amdnr"


def _profile_file(game_folder: Path) -> Path:
    token = hashlib.sha256(str(game_folder.resolve()).encode()).hexdigest()[:32]
    return _config_root() / "proton-profiles" / (token + ".json")


def gpu_probe() -> list[dict]:
    found = []
    drm = Path("/sys/class/drm")
    for item in sorted(drm.glob("card[0-9]*"))[:16]:
        dev = item / "device"
        try:
            vendor = (dev / "vendor").read_text().strip().lower()
            pci_device = (dev / "device").read_text().strip().lower()
            driver_link = dev / "driver"
            driver = driver_link.resolve().name if driver_link.exists() else None
            if vendor not in GPU_DRIVERS:
                continue
            found.append({"card": item.name, "vendor": GPU_DRIVERS[vendor],
                          "pci_id": pci_device, "driver": driver,
                          "generation": "unknown (not inferred from PCI ID)"})
        except (OSError, ValueError):
            continue
    return found


def proton_tools(steam_roots: list[Path]) -> list[dict]:
    items, seen = [], set()
    for root in steam_roots[:16]:
        candidates = [
            root / "compatibilitytools.d",
            root / "steamapps" / "common",
            root.parent / "compatibilitytools.d",
        ]
        for folder in candidates:
            if not folder.is_dir() or folder.is_symlink():
                continue
            try:
                children = list(folder.iterdir())[:400]
            except OSError:
                continue
            for entry in children:
                if not entry.is_dir() or entry.is_symlink():
                    continue
                name = entry.name
                if not (name.lower().startswith("proton") or name.lower().startswith("ge-proton")):
                    continue
                resolved = str(entry.resolve())
                if resolved in seen:
                    continue
                seen.add(resolved)
                items.append({"name": name, "path": resolved, "available": True})
    return sorted(items, key=lambda x: x["name"].lower())[:64]


def game_running(executable: Path) -> dict:
    """Only a best-effort process heuristic; Wine process paths can differ."""
    try:
        exe_name = executable.name.lower()
        folder_name = executable.parent.name.lower()
        match = []
        own_id = os.getuid()
        for proc in list(Path("/proc").iterdir())[:15000]:
            if not proc.name.isdigit():
                continue
            try:
                if proc.stat().st_uid != own_id:
                    continue
                args = (proc / "cmdline").read_bytes()[:32768].replace(b"\x00", b" ").decode(
                    "utf-8", errors="replace").lower()
                if exe_name in args or (folder_name in args and "wine" in args):
                    match.append(int(proc.name))
            except (OSError, PermissionError, UnicodeError):
                continue
        return {"running": bool(match), "pids": match[:16],
                "confidence": "heuristic",
                "note": "Wine/Proton processes may not expose Windows executable names."}
    except OSError:
        return {"running": None, "pids": [], "confidence": "unavailable"}


def anti_cheat_scan(game_folder: Path) -> dict:
    """Bounded filename-only scan, no anti-cheat bypass or process modification."""
    hits = []
    scanned = 0
    queue = [(game_folder, 0)]
    while queue and scanned < 3000:
        folder, depth = queue.pop(0)
        if folder.is_symlink() or not folder.is_dir():
            continue
        try:
            children = list(folder.iterdir())[:500]
        except OSError:
            continue
        for child in children:
            scanned += 1
            if any(key in child.name.lower().replace(" ", "") for key in CHEAT_NAMES):
                hits.append(child.name[:128])
            if child.is_dir() and not child.is_symlink() and depth < 2:
                queue.append((child, depth + 1))
            if scanned >= 3000:
                break
    return {"potential_anti_cheat": bool(hits), "filenames": sorted(set(hits))[:30],
            "scanned": scanned, "partial": bool(queue),
            "warning": "File names do not prove whether anti-cheat runs. DLL injection may be prohibited."}


def _profile_defaults() -> dict:
    return {"gamemode": False, "mangohud": False, "selected_proton": "Steam default",
            "tested_runtime": None, "tested_result": "unverified"}


def profile(game_folder: Path) -> dict:
    if not game_folder.is_dir() or game_folder.is_symlink():
        raise ValueError("Select an existing game folder")
    output = _profile_defaults()
    location = _profile_file(game_folder)
    if location.exists():
        if location.is_symlink() or location.stat().st_size > 8192:
            raise ValueError("Unsafe Proton profile")
        data = json.loads(location.read_text())
        if not isinstance(data, dict):
            raise ValueError("Invalid Proton profile")
        for key in output:
            if key in data:
                output[key] = data[key]
    return output


def save_profile(game_folder: Path, payload: dict) -> dict:
    if not game_folder.is_dir() or game_folder.is_symlink():
        raise ValueError("Select a valid game folder")
    if not isinstance(payload, dict) or set(payload) - set(_profile_defaults()):
        raise ValueError("Unknown Proton profile option")
    result = _profile_defaults()
    result.update(payload)
    if type(result["gamemode"]) is not bool or type(result["mangohud"]) is not bool:
        raise ValueError("Invalid wrapper preference")
    if not isinstance(result["selected_proton"], str) or len(result["selected_proton"]) > 100:
        raise ValueError("Invalid Proton selection")
    if result["tested_runtime"] is not None and (
            not isinstance(result["tested_runtime"], str) or
            len(result["tested_runtime"]) > 64):
        raise ValueError("Invalid tested runtime")
    if result["tested_result"] not in (
            "unverified", "files_present", "detected_in_game",
            "rendering_confirmed", "failed"):
        raise ValueError("Unsupported runtime test status")
    location = _profile_file(game_folder)
    location.parent.mkdir(parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(prefix=".profile-", dir=location.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(result, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, location)
    finally:
        Path(staging).unlink(missing_ok=True)
    return result


def launch_preview(game_folder: Path, alias: str, existing: str | None = None) -> dict:
    """Use existing Steam merge logic, prepend only the user's opted-in wrappers."""
    import amdnr_launcher as core
    from steam_user_launch import preview_launch_options
    settings = profile(game_folder)
    current = existing
    if current is None:
        detected = core.steam_launch_options_for_directory(game_folder, alias)
        if detected.get("status") not in ("found", "empty", "ok"):
            return {"status": "needs_review", "reason": detected.get("reason"),
                    "launch_options": None}
        current = detected.get("existing") or "%command%"
    # Reuse the main launch-option reader merge; never manipulate Steam VDF.
    merged = preview_launch_options(current, alias)
    if merged.get("status") not in ("added", "merged"):
        return {"status": "needs_review", "reason": merged.get("reason"),
                "launch_options": None}
    command = merged["preview"]
    wrappers = []
    for option, binary in (("gamemode", "gamemoderun"), ("mangohud", "mangohud")):
        if settings[option]:
            if shutil.which(binary) is None:
                return {"status": "missing_wrapper", "reason": binary + " not installed",
                        "launch_options": None}
            wrappers.append(binary)
    if wrappers:
        # Prefix at command boundary, preserve all variables and game args.
        at = command.find("%command%")
        if at < 0:
            return {"status": "needs_review", "reason": "Missing %command% placeholder",
                    "launch_options": None}
        command = command[:at] + " ".join(wrappers) + " " + command[at:]
    return {"status": "ok", "launch_options": command,
            "note": "Copy this into Steam; no launch settings were modified."}


def compatibility(executable: Path, steam_roots: list[Path]) -> dict:
    root = executable.resolve().parent
    probe = gpu_probe()
    ac = anti_cheat_scan(root)
    proc = game_running(executable)
    proton = proton_tools(steam_roots)
    profile_info = profile(root)
    verdict = "untested"
    blockers = []
    if ac["potential_anti_cheat"]:
        blockers.append("Potential anti-cheat detected; verify game policy before installation")
    if proc["running"]:
        blockers.append("Game may be running; quit it before changing DLLs")
    if profile_info["tested_result"] == "rendering_confirmed":
        verdict = "user_confirmed"
    return {"gpu": probe, "proton_tools": proton, "anti_cheat": ac,
            "game_process": proc, "profile": profile_info,
            "verdict": verdict, "blockers": blockers,
            "daniel_080": "NeuralHub not supported by current Proton GPU bridge",
            "note": "No static GPU or Proton profile guarantees runtime initialization."}


def _redact(value: str) -> str:
    home = str(Path.home())
    if home and home != "/":
        value = value.replace(home, "$HOME")
    return TOKEN_RE.sub(lambda m: m.group(1) + "=<REDACTED>", value)


def support_bundle(executable: Path, output_dir: Path | None = None) -> dict:
    """Explicit local support ZIP with redaction, bounded logs, no Steam secrets."""
    import amdnr_launcher as core
    if not executable.is_file() or executable.is_symlink():
        raise ValueError("Select a Windows game executable")
    root = executable.resolve().parent
    directory = output_dir or (_config_root().parent / "amdnr" / "support")
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("Unsafe support output folder")
    target = directory / ("amdnr-support-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") +
                          "-" + os.urandom(3).hex() + ".zip")
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "gpu": gpu_probe(),
        "installed": core.installation_report(executable),
        "doctor": core.doctor_report(executable, None),
        "anti_cheat": anti_cheat_scan(root),
        "proton": proton_tools(core.steam_roots()),
        "runtime": core.runtime_diagnostics(executable),
        "note": "All data is local until you choose to share this ZIP."
    }
    collected = []
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr("report.json", _redact(json.dumps(report, indent=2, default=str)))
        for name in LOG_NAMES:
            log = root / name
            if log.is_symlink() or not log.is_file() or log.stat().st_size > MAX_LOG:
                continue
            try:
                text = log.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if name.lower().endswith(".ini"):
                # INI may include user-controlled secrets; collect keys only.
                text = "\n".join(line.split("=", 1)[0] + "=<REDACTED>" if
                                 "=" in line and not line.lstrip().startswith(("#", ";"))
                                 else line[:256] for line in text.splitlines())
            output.writestr("logs/" + name, _redact(text)[:MAX_LOG])
            collected.append(name)
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
    return {"file": str(target), "logs": collected, "local_only": True}


def analyze_mangohud_csv(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PERF_CSV:
        raise ValueError("Select a bounded MangoHud CSV")
    import statistics
    with path.open(newline="") as stream:
        lines = csv.DictReader(stream)
        if lines.fieldnames is None:
            raise ValueError("CSV has no headers")
        col = next((name for name in lines.fieldnames if name.lower() in
                    ("frametime", "frametime_ms", "frame_time")), None)
        if col is None:
            raise ValueError("No frame-time column found")
        values = []
        for i, row in enumerate(lines):
            if i > 500000:
                raise ValueError("Performance capture exceeds 500k rows")
            try:
                number = float(row[col])
            except (ValueError, KeyError, TypeError):
                continue
            if 0 < number < 1000:
                values.append(number)
    if not values:
        raise ValueError("No valid frame times")
    ordered = sorted(values)
    return {"frames": len(values), "average_ms": round(statistics.mean(values), 2),
            "median_ms": round(statistics.median(values), 2),
            "p95_ms": round(ordered[int((len(values) - 1) * 0.95)], 2),
            "p99_ms": round(ordered[int((len(values) - 1) * 0.99)], 2),
            "note": "MangoHud data is observational and does not prove which runtime rendered frames."}
