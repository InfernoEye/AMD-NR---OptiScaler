# AMDNR native Linux desktop (Avalonia, in development)

**Preferred native GUI:** Avalonia / .NET 8. From the repository root:

```bash
dotnet run --project linux/avalonia/Amdnr.Linux.Desktop.csproj
```

Install the **.NET 8 SDK** and **Python 3.10+** first. The Avalonia UI uses the Linux Python installer as its backend. Run from the repository root, or set `AMDNR_LINUX_BACKEND` to an absolute path pointing to `amdnr_linux_launcher.py`.

The Avalonia screen provides a game library, installation/uninstallation with backup restore, Wine DLL override guidance, Doctor preflight checks, and settings. The Python/Tk implementation below remains as a fallback CLI and UI.

**Parity status:** This is the foundation of an independent native implementation, **not yet a 1:1 visual or functional match** for the Windows WPF launcher. Missing pieces include pixel-perfect styling and branded assets, the full Windows release/build picker and automatic downloads, equivalent diagnostic reporting, full store integrations and persistence, and Windows-only features. The original source-available WPF launcher has restrictive reuse terms; this implementation is written independently.

---
# Native Linux launcher (experimental)

Run the independent Python/Tk launcher from this directory:

```bash
python3 linux/amdnr_linux_launcher.py
```

Requirements: Linux, Python **3.10+**, and `python3-tk` for the GUI (on Debian/Ubuntu: `sudo apt install python3-tk`). No .NET or Wine is required to run the manager itself. A Windows game running through **Steam Proton** or Wine is still needed for the installed Windows graphics DLLs.

The manager can detect standard Steam libraries (including Flatpak Steam), show installed games, select a game's Windows executable, install files from a **locally downloaded, trusted AMDNR release ZIP**, back up files it replaces, and uninstall while restoring backups. It does **not** download arbitrary runtimes, bypass anti-cheat, or guarantee that the Windows neural runtime will run under Proton.

## Command-line operation

```bash
python3 linux/amdnr_linux_launcher.py --list
python3 linux/amdnr_linux_launcher.py --install /path/to/AMDNR.zip --exe "/path/to/Game/Binaries/Win64/Game-Win64-Shipping.exe"
python3 linux/amdnr_linux_launcher.py --uninstall --exe "/path/to/Game/Binaries/Win64/Game-Win64-Shipping.exe"
```

For a different proxy name add `--alias version.dll` (see `--help`). The installer prints a Steam launch option such as:

```text
WINEDLLOVERRIDES="dxgi=n,b" %command%
```

Enter that in the game's Steam **Properties > General > Launch Options**. Keep your existing launch options as needed. For a manually configured Wine prefix, set the same DLL override in your Wine configuration instead. The override must correspond to the actual installed DLL name.

**Select the real game EXE, not a launcher or anti-cheat executable.** For Unreal Engine games it is commonly under `Binaries/Win64`. The launcher installs alongside the chosen EXE. It copies supported payload files from the ZIP adjacent to `OptiScaler.dll` and beneath its directory, renaming that DLL to the selected proxy name. Other ZIP contents (executables, scripts, installers) are deliberately not installed.

## Safety and limitations

- Existing files are moved to `AMDNR_backup/linux-launcher`; the install record is `.amdnr-linux-install.json` beside the selected EXE. Keep both until after uninstall.
- Reinstalling into a directory with a recorded installation is refused until you uninstall. Existing backup folders are never silently overwritten.
- Uninstall keeps modified installed files rather than deleting user changes; it reports any conflicts and leaves a partial record.
- Archives with traversal paths or symlinks are rejected; there is a 2 GiB uncompressed payload limit. Only install releases you trust.
- The GUI does **not** provide upstream's Gallery, chat, auto-updater, full runtime selection, OptiPatcher, AMDNR Anywhere, or full Windows game-store discovery.
- Upstream's WPF launcher cannot run natively on Linux. This launcher is a separate implementation and does not use or modify its source code.
- **Installing a Windows DLL is not proof of rendering compatibility.** The GPU runtime, HIP/ROCm integration, DXVK/vkd3d-proton, Wine prefix, driver, and the particular AMD GPU all matter. AMDNR Anywhere uses a Windows capture host and is not supported by this native manager.
- Steam games with anti-cheat may disallow injected DLLs. Avoid modifying protected online games.

Run smoke tests with `python3 -m unittest discover -s linux/tests -v`. No GPU or game is required for these tests.
