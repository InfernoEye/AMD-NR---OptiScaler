# Avalonia launcher

**Platform: Linux.** This is the independent Linux desktop launcher. The original Windows launcher remains under `Launcher/OpenSource/`.

**Preferred native GUI:** Avalonia / .NET 10. From the repository root:

```bash
dotnet run --project Launcher/Avalonia/Amdnr.Avalonia.csproj
```

Install the **.NET 10 SDK** and **Python 3.10+** first. Check with `dotnet --list-sdks`. The project targets `net10.0`, so an older SDK cannot compile it; a newer SDK may work if it supports targeting .NET 10. Run `dotnet --list-runtimes` to verify that `Microsoft.NETCore.App 10.x` is installed for framework-dependent launching. `dotnet run` automatically selects an appropriate installed SDK; no `global.json` pins a specific patch. The Avalonia UI uses the Linux Python installer as its backend. Run from the repository root, or set `AMDNR_AVALONIA_BACKEND` to an absolute path pointing to `amdnr_launcher.py`.

The Avalonia desktop provides a searchable Steam game library with cached artwork, selected-game details, executable selection, installation-record status, installation/uninstallation with backup restore, Wine DLL override guidance, Doctor preflight checks, and settings.

**Steam cover artwork:** the refresh scan checks Steam's custom `userdata/*/config/grid` covers, standard, nested and content-hash Steam caches, then official Steam CDN/store image metadata when needed. Downloaded images are kept under `${XDG_CACHE_HOME:-~/.cache}/amdnr/steam-artwork`. Set `AMDNR_NO_ARTWORK_DOWNLOAD=1` to disable network artwork fetches. Missing art can be assigned per game using **Change Cover Art** on the game's detail screen; these JPEG/PNG overrides are stored under `${XDG_DATA_HOME:-~/.local/share}/amdnr/artwork` without touching Steam files. Refresh always returns to the game library. Not every Steam title has an official cover. When none is found, the UI generates a readable title-based placeholder rather than a blank or single-letter tile; the artwork report continues to count these as missing real images. The install status is specific to the executable selected and the Linux launcher's own install records, not all third-party AMDNR installs. The Python/Tk implementation below remains as a fallback CLI and UI.

**Parity status:** This is the foundation of an independent native implementation, **not yet a 1:1 visual or functional match** for the Windows WPF launcher. Missing pieces include pixel-perfect styling and branded assets, full Windows-equivalent build variants and model/runtime configuration, equivalent diagnostic reporting, full store integrations and persistence, and Windows-only features. The original source-available WPF launcher has restrictive reuse terms; this implementation is written independently.

---
# Native Linux launcher (experimental)

Run the independent Python/Tk launcher from this directory:

```bash
python3 Launcher/Avalonia/amdnr_launcher.py
```

Requirements: Linux, Python **3.10+**, and `python3-tk` for the GUI (on Debian/Ubuntu: `sudo apt install python3-tk`). No .NET or Wine is required to run the manager itself. A Windows game running through **Steam Proton** or Wine is still needed for the installed Windows graphics DLLs.

The manager can detect standard Steam libraries (including Flatpak Steam), show installed games, select a game's Windows executable, install files from a **locally downloaded, trusted AMDNR release ZIP**, back up files it replaces, and uninstall while restoring backups. It does **not** download arbitrary runtimes, bypass anti-cheat, or guarantee that the Windows neural runtime will run under Proton.


## Browse and download upstream builds

The **Install** page now has a **Load Builds** button that lists versioned, complete AMDNR ZIP release assets from the upstream GitHub repository (`3zwr1/AMD-NR---OptiScaler`). Select the version and choose **Download Selected ZIP**. Downloading is explicitly user initiated and does not install DLLs into any game.

The release downloader checks the upstream `SHA256SUMS.txt` manifest, verifies the ZIP checksum and file size, and caches validated packages under `${XDG_CACHE_HOME:-~/.cache}/amdnr/releases/<tag>/`. Downloads with missing checksums, invalid archives, or unexpected names are refused. The existing **Browse** option remains available for releases acquired separately.

CLI equivalents:

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --releases-json
python3 Launcher/Avalonia/amdnr_launcher.py --download-release TAG --release-asset AMDNR-vVERSION.zip
```

The version and asset name come from the release catalog; they are not game-name-specific. Only complete upstream AMDNR release ZIPs are supported by this workflow. Optional model packs and Windows executables are not offered as installable packages. **Downloading and installing the Windows DLL files does not establish Proton or neural-runtime compatibility.**

## Selecting a game executable

Select a Steam game from the library. Avalonia scans its Windows executables and **automatically selects a high-confidence candidate**, including when there is only one non-suspicious EXE. If multiple executables look equally plausible, it asks you to choose instead. Developer tools, editors, setup programs, and anti-cheat binaries receive lower rankings. Use **Change Executable**, **Browse EXE**, or **Rescan** to override a selection. Manual choices are remembered across launches in `${XDG_CONFIG_HOME:-~/.config}/amdnr/game-executables/`, keyed by game installation directory rather than game title. Missing/stale saved paths are ignored. **An automatic selection is a heuristic, not proof of the correct game binary:** review the destination before installation; installing DLLs still requires a separate click.

The CLI supports the same scan:

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --exes-json "/path/to/steamapps/common/Game"
```

With a selected executable, the game screen shows a compact Linux installation record summary with the DLL alias and tracked-file count. **Show Tracked Files** expands an independently scrollable list so a large installation does not hide the rest of the game controls. **Check File Integrity** opens Doctor. The main view retains extra scrolling space above its bottom status bar.

## Installation records and version provenance

The **Install** page now includes **Verify Installed Files**, a read-only inventory of the selected game's installation. It reports tracked file count, modified/missing files, missing original-file backups, proxy DLL alias and source ZIP filename. A new installation stores the source archive filename and SHA-256 digest in the existing v1 installation record. Older records remain compatible and display **Unknown (older install record)** for the source archive; no release version is inferred without evidence.

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --installation-json --exe "/path/to/game.exe"
```

This checks disk files but does not establish whether the game can initialize the Windows runtime under Proton. Missing original backups are reported rather than silently repaired or overwritten.

## Linux Doctor

On **Doctor**, choose **Run Installation Diagnostics** to perform read-only checks of Steam libraries, the selected game EXE, the selected release ZIP and the Linux launcher's installation record. If recorded files exist, their SHA-256 hashes are compared against the installation record to identify missing or modified files.

The same report is available at the command line:

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --doctor-json --exe "/path/to/game.exe" --archive "/path/to/AMDNR.zip"
```

These checks do **not** establish GPU compatibility, Proton execution success, or anti-cheat compatibility.

## Diagnose missing game artwork

The game library now shows a **Missing Art** filter and a count of unresolved covers. For an exact list of games that remain unresolved after searching Steam caches and official artwork sources, run:

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --artwork-report --download-artwork
```

This produces JSON with totals and game names (no local installation paths). Some older/unlisted/removed Steam titles have no available official cover. Use **Change Cover Art** on the game's details to assign a JPG or PNG directly; the selected artwork is stored outside the game and Steam directories.

## Command-line operation

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --list
python3 Launcher/Avalonia/amdnr_launcher.py --install /path/to/AMDNR.zip --exe "/path/to/Game/Binaries/Win64/Game-Win64-Shipping.exe"
python3 Launcher/Avalonia/amdnr_launcher.py --uninstall --exe "/path/to/Game/Binaries/Win64/Game-Win64-Shipping.exe"
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

Run smoke tests with `python3 -m unittest discover -s Launcher/Avalonia/tests -v`. No GPU or game is required for these tests.
