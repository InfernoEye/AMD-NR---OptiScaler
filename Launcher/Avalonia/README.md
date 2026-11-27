# Avalonia launcher

> **Community ROCm bridge (experimental):** The optional **Experimental Linux ROCm Bridge**
> screen can now download and verify AMDNR-Linux v0.3.7 by hassanm0301 and
> invoke its original GPL setup/installation scripts after separate approvals.
> Neither its source nor binaries are copied into our repository or bundled in
> this AppImage. The bridge remains separately managed and unverified by us in
> Subnautica 2. See [third-party acknowledgements](THIRD_PARTY_ACKNOWLEDGEMENTS.md)
> for its license, exact release and authorship.
>
> **Scope:** This is the Linux/Proton edition of the AMDNR launcher,
> not a general gaming utility. Follow the official Windows launcher's
> install/repair/extension workflows wherever possible. See
> [Scope and Windows parity](SCOPE_AND_PARITY.md) for what is implemented,
> blocked, and still needs in-game validation. The Windows launcher is untouched.
>
> **New user workflow:** Choose your game and its Windows executable, then
> open **Install → Quick Install Latest Verified AMDNR**. The Linux launcher
> selects an eligible official upstream ZIP and verifies its SHA-256 before
> installation. For existing installs, use **Repair / Update / Recovery**;
> originals are backed up and updates record recovery journals. For
> broken proxy loading, use **Try Next Proxy** and copy the returned Steam
> `WINEDLLOVERRIDES` preview if necessary. Neither Steam config nor
> Proton compatibility selection is modified automatically.
>
> **Linux distribution builds:** self-contained AppImage and portable tarball
> CI are defined in
> [linux-distributions.yml](../../.github/workflows/linux-distributions.yml),
> with an experimental Flatpak manifest under `packaging/flatpak`.
> These use the independent Linux source and Python backend, not the
> original Windows installer. Developers can still use `dotnet run`.
>
> **Linux-only troubleshooting:** the Compatibility page detects GPU/Proton
> information and potential anti-cheat warnings without claiming the
> Windows DLL will run. Doctor can create a locally stored, redacted
> AMDNR support bundle; it is not a separate benchmarking tool.

## Local distro dependencies and pinned runtime recovery

The experimental bridge now checks the host's **libelf.so.1** and
**libnuma.so.1** without loading them or changing packages. When missing,
Avalonia displays the detected distro and a **copy-only**, user-reviewed
package-manager command (Debian/Ubuntu, Arch, Fedora or openSUSE). The
launcher never runs `sudo`, `apt`, `pacman`, `dnf` or `zypper`.

**Important limitation:** The community AMDNR-Linux v0.3.7 bridge prepares a
**private, pinned ROCm 7.2.4 runtime**. The host's installed libelf/libnuma
files cannot safely replace its exact private runtime just because they have
the same library name. Installing distro libraries alone will **not** solve
a missing pinned upstream `.deb` archive.

To handle upstream Ubuntu archive URLs that now return HTTP 404, bridge
preparation first reuses a byte-for-byte, SHA-256-matching `.deb` from
`/var/cache/apt/archives` where available, then retries official Ubuntu
mirrors and verifies the same upstream SHA-256 before letting the original,
unmodified community preparation script consume it. A bad/corrupt existing
cache entry blocks preparation; unknown files, host libraries, and arbitrary
new package versions are not substituted. No game files or Steam/Proton
settings are changed during this step.

The pinned prerequisite archive names and checksums originate from
`hassanm0301/AMDNR-Linux/linux/fetch-rocm.py` in the separately verified
`linux-v0.3.7` release. Mirror recovery does not alter its source or
license obligations. If all mirrors fail, the launcher stops with an
actionable explanation instead of hiding an HTTP 404.

## Guided ROCm bridge preparation (launcher-only)

The optional ROCm bridge page now starts with an automatic, **read-only**
inspection of the selected Windows executable's Steam library, available AMD
GPU device nodes (`/sys/class/drm`, `/dev/kfd`, and `/dev/dri/renderD*`),
installed Proton tool directories, and a bounded search for
`d3dcompiler_47.dll`. The search avoids symlinks, caps traversal count and
duration, prefers the selected game folder, and verifies a native **x64 PE**
header before proposing a compiler. PE structure is **not proof** of Microsoft
origin, permission to copy, or runtime compatibility. A user must verify
provenance and may instead browse to their own compiler manually.

The UI walks through three separate stages:
**(1) Detect & Check** (no writes);
**(2) Prepare Dependencies** (requires explicit approval for external
GPL-licensed scripts and separately pinned downloads); and
**(3) Review Changes & Install** (a separate approval, with fresh conflict
checks and managed backups). A collapsed Restore section remains available.
Steam launch options are always shown as **copy-only** text; nothing
automatically changes Steam or the Proton prefix. Using the external wrapper
later can modify the game's **existing** Proton prefix, as disclosed in UI.

Detected Proton installations do **not** prove which Proton version the game
actually uses. No GPU/Proton compatibility or in-game rendering result is
inferred from a successful hardware scan. Existing AMDNR backup/installation
markers and ReShade/proxy files continue to block bridge installation rather
than being automatically removed.

For manual read-only preflight:

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --bridge-discover-json --exe "/path/to/game-Win64-Test.exe"
```

All changes for this wizard are limited to `Launcher/Avalonia/`, including
`bridge_discovery.py` and regression tests in `tests/test_community_bridge.py`.

## Experimental AMDNR-Linux ROCm bridge

The **Experimental Linux ROCm Bridge** action on the selected game's details page
(or the Compatibility page) is an opt-in adapter for the *separately maintained*
[hassanm0301/AMDNR-Linux](https://github.com/hassanm0301/AMDNR-Linux)
project. It is not equivalent to the original AMDNR ZIP installer, and the
rendering bridge is not authored or shipped by this repository.

The adapter uses the pinned **linux-v0.3.7** archive with SHA-256
`7e4ddb01a352a824bbf6009cfd8a1c0728267679e4a170d33fc8e01f91b84423`.
It verifies the archive, extracts safe entries to a user-local cache, calls the
unmodified release's `linux/setup.py prepare`, and uses the same release's
`linux/manage.py` for explicitly approved installation and removal. The
staged package and original source remain under
`${XDG_CACHE_HOME:-~/.cache}/amdnr-linux/community-bridge/0.3.7/`.

**Requirements:** Python 3.12+ with `zstandard` installed (or Python 3.14+
with built-in zstd), a native x64 Microsoft `d3dcompiler_47.dll` obtained
from the user's own game, AMD Vulkan and ROCm-capable GPU permissions, a
Wine 11-based Proton such as GE-Proton11-9, multiple GB of disk space, and the
separately downloaded dependencies. AMDNR-Linux's reported game testing used
RX 9070 XT and does not establish support for RX 6000, Steam Deck or Subnautica 2.
The community release's exact requirements and license notices control the
preparation; neither the optional adapter nor our CI proves the GPU bridge works.

**Safety:** The adapter does not modify Steam options, change Proton choice,
or change game files as part of read-only status or package preparation. An
explicit install action can write the selected game folder using the community
installer's own journal and backups. It refuses recorded AMDNR installs, ReShade
configuration and occupied proxy/D3D12 DLL slots. Close the game first and use
the original manager to restore an existing installation rather than deleting
DLLs by hand. The resulting wrapper option is a **copy-only preview**. On the
next game launch, that wrapper can change files inside the current Proton
prefix, with the community installer keeping its own recovery journal.
Inspect the instructions before copying it into Steam yourself.

The Subnautica 2 experimental branch shown in user screenshots contains a
`Subnautica2-Win64-Test.exe` under `Subnautica2/Binaries/Win64/`, and
existing ReShade and `dxgi.dll` files. Its top-level `Subnautica2.exe`
is not necessarily the rendering process. Confirm the inner executable,
preserve existing mods and backups, and resolve conflicts through the
appropriate uninstaller before attempting this separate bridge. The
adapter deliberately does not auto-clean conflicts or override hooks.

For advanced **read-only** status, run:

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --bridge-status-json --exe "/path/to/Game-Win64-Test.exe"
```

All community files are downloaded separately after consent; users distributing
a prepared combined installation must comply with the original GPL/LGPL,
upstream AMDNR, Microsoft compiler and ROCm asset terms.

## Windows-inspired Linux UI (in progress)

The independent Avalonia interface now supports artwork-forward **Grid** and
compact **List** library views. Grid uses left-hand workspace navigation;
List moves navigation to a horizontal top bar, as in the visual reference
provided for the official Windows launcher. On narrow windows, top navigation
is used automatically without changing the saved Grid/List preference.

The selected preference persists under the user's XDG configuration directory.
Both views use the same library data, filters, detected executables and
installation records; switching views never changes game files or Steam options.
The UI is a Linux-only implementation; no Windows launcher code was copied.

The second UI pass adds artwork-backed game details, visible focus outlines
for keyboard/controller button navigation, and responsive Settings cards for
general preferences, upstream research credits, and verified launcher updates.
A five-step skippable Linux-specific introduction appears on first run; it can
be replayed from Settings. Introduction and view preferences are user-local
under the XDG configuration directory, separate from game files.

## Reference UI corrections (November 2026)

Based on screenshots of the official Windows launcher, this pass corrects
two important problems found in the initial Avalonia redesign:

- **The introduction is an anchored walkthrough, not isolated windows.**
  Its steps navigate to actual Library, Installed, Install, Doctor, Settings and
  Help screens. Actual navigation and search controls are highlighted; Back,
  Next and Skip work without performing installs or modifying game files.
  The new walkthrough uses the user-local `onboarding-v2.txt` marker so
  users who saw the old disconnected version see the fixed tour once.
  Settings and Help can replay the tour. In List mode/narrow layouts,
  callouts anchor below the horizontal navigation.
- **The shell follows the official launcher hierarchy.** A compact AMD/NR
  identity and Grid/List controls share the fixed top toolbar. Grid uses an
  icon-labelled left sidebar; List puts navigation in the same top toolbar
  with horizontal overflow scrolling. The fixed footer holds status.
  On the Library page, games and search are prioritized, quick filter tabs
  are visible and advanced readiness auditing is folded away by default.
  Artwork cards have more prominent images and less intrusive actions.

These changes are written exclusively under `Launcher/Avalonia/`.
They are **not a claim of pixel-perfect Windows parity** and still require
a real Avalonia desktop screenshot review and Steam Deck/controller
interaction testing. No Windows launcher code or external project was changed.

## Current UI functionality and verification

- **English/Polish:** Language selector in Settings, saved under XDG configuration.
  Core navigation, library and common actions, onboarding and Help/FAQ have
  curated Polish translations. Remaining advanced diagnostic and installation
  descriptions still use English; localization is not yet complete end-to-end.
- **Library styling:** Grid/List with persisted selection, adaptive sidebar/top
  navigation, game artwork backdrop on the details screen, and hover/focus
  outlines. No game files or Steam launch settings change when switching views.
- **Controller:** Optional Linux joydev input handles directional focus,
  held-stick repeat, selection and back. The focused control scrolls into view.
  Device mappings, Steam Input configurations and real Steam Deck behavior
  still need hardware testing.
- **Neural configuration:** A guided preview shows only existing known keys
  in `[DlssNr]` and permits only their supported values. Unsupported or duplicate
  keys are never added. The original raw editor and explicit SHA-guarded Save
  with backup remain the only way to write changes. Nothing is auto-applied.
- **Help:** In-app English/Polish FAQ, Linux/Proton diagnostic guidance,
  explicit runtime limitations, and credits for external community research.
- **UI logic checks:** From the repository root, execute:
  `dotnet run --project Launcher/Avalonia/Amdnr.Avalonia.csproj -- --selftest-ui`.
  This checks INI preview preservation, duplicate/invalid setting rejection,
  and localization fallback without starting the GUI or touching game files.

**Not yet independently verified:** Linux desktop screenshots, screenshot
parity with the Windows launcher, live joystick/controller behavior,
Steam Deck 1280×800 layout, broad distro compatibility, or complete Polish
translation of every advanced page. Successful CI compilation does not
establish those results. Windows-only Anywhere/Desktop NR features remain
unsupported unless separately validated.

**Platform: Linux.** This is the independent Linux desktop launcher. The original Windows launcher remains under `Launcher/OpenSource/`.

**Preferred native GUI:** Avalonia / .NET 10. From the repository root:

```bash
dotnet run --project Launcher/Avalonia/Amdnr.Avalonia.csproj
```

Install the **.NET 10 SDK** and **Python 3.10+** first. Check with `dotnet --list-sdks`. The project targets `net10.0`, so an older SDK cannot compile it; a newer SDK may work if it supports targeting .NET 10. Run `dotnet --list-runtimes` to verify that `Microsoft.NETCore.App 10.x` is installed for framework-dependent launching. `dotnet run` automatically selects an appropriate installed SDK; no `global.json` pins a specific patch. The Avalonia UI uses the Linux Python installer as its backend. Run from the repository root, or set `AMDNR_AVALONIA_BACKEND` to an absolute path pointing to `amdnr_launcher.py`.

The Avalonia desktop provides a searchable Steam game library with cached artwork, selected-game details, executable selection, installation-record status, installation/uninstallation with backup restore, Wine DLL override guidance, Doctor preflight checks, and settings.

**Steam cover artwork:** the refresh scan checks Steam's custom `userdata/*/config/grid` covers, standard, nested and content-hash Steam caches, then official Steam CDN/store image metadata when needed. Downloaded images are kept under `${XDG_CACHE_HOME:-~/.cache}/amdnr/steam-artwork`. Set `AMDNR_NO_ARTWORK_DOWNLOAD=1` to disable network artwork fetches. Missing art can be assigned per game using **Change Cover Art** on the game's detail screen; these JPEG/PNG overrides are stored under `${XDG_DATA_HOME:-~/.local/share}/amdnr/artwork` without touching Steam files. Refresh always returns to the game library. Not every Steam title has an official cover. When none is found, the UI generates a readable title-based placeholder rather than a blank or single-letter tile; the artwork report continues to count these as missing real images. The install status is specific to the executable selected and the Linux launcher's own install records, not all third-party AMDNR installs. The Python backend remains available for **explicit command-line operations only**; its old Tkinter desktop interface has been removed. The Avalonia application is the only graphical launcher.

**Parity status:** This is the foundation of an independent native implementation, **not yet a 1:1 visual or functional match** for the Windows WPF launcher. Missing pieces include pixel-perfect styling and branded assets, full Windows-equivalent build variants and model/runtime configuration, equivalent diagnostic reporting, full store integrations and persistence, and Windows-only features. The original source-available WPF launcher has restrictive reuse terms; this implementation is written independently.

---
# Python installer backend (CLI only)

The former Python/Tkinter graphical launcher has been retired. **Use Avalonia for
all desktop UI features**:

```bash
dotnet run --project Launcher/Avalonia/Amdnr.Avalonia.csproj
```

The Python backend is still necessary for game discovery, downloads,
installation, recovery, diagnostics and the optional third-party bridge.
Invoke it only with an explicit CLI flag, such as:

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --list
python3 Launcher/Avalonia/amdnr_launcher.py --doctor-json
python3 Launcher/Avalonia/amdnr_launcher.py --bridge-status-json
```

Running the Python module **without an action** prints usage and exits with
status 2; it never creates a window or installs anything. No `python3-tk`
dependency is required. The normal backend needs Python 3.10+; experimental
community bridge preparation has additional version and runtime requirements
listed above.

The CLI supports the same explicit installation and recovery operations, but
does **not** silently configure Proton or install components. The project still
does not guarantee Windows neural rendering compatibility under Proton.


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

With a selected executable, the game screen shows a compact Linux installation record summary with the DLL alias and tracked-file count. **Show Tracked Files** expands an independently scrollable list. **Check File Integrity** opens Doctor. The window size stays under the user's control: expanding a list, switching pages, or opening game details never resizes it. All sections share a scrolling viewport with a generous 140-pixel trailing content spacer so the last controls can scroll clear of the bottom edge, even in a short window. Operation status appears in the header rather than a fixed bottom bar. The former duplicate installation action panel has been removed.

## Installation records and version provenance

The **Install** page now includes **Verify Installed Files**, a read-only inventory of the selected game's installation. It reports tracked file count, modified/missing files, missing original-file backups, proxy DLL alias and source ZIP filename. A new installation stores the source archive filename and SHA-256 digest in the existing v1 installation record. Older records remain compatible and display **Unknown (older install record)** for the source archive; no release version is inferred without evidence.

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --installation-json --exe "/path/to/game.exe"
```

This checks disk files but does not establish whether the game can initialize the Windows runtime under Proton. Missing original backups are reported rather than silently repaired or overwritten.

## Persistent custom game installations

Choose **Library → Add manually** to add a game installed outside Steam. Select its installation folder, enter an optional display name, and optionally browse to the Windows `.exe` to remember the executable immediately. Custom entries appear alongside Steam installations with a **CUSTOM GAME** label and use the same artwork, executable discovery, Doctor and installation workflow.

Custom games are saved under `${XDG_CONFIG_HOME:-~/.config}/amdnr/custom-games.json` and survive closing/restarting the launcher, Steam refreshes, and temporarily disconnected game drives. The custom list does not depend on Steam manifests. Select a custom game's **Edit / Remove Custom Game** action to change its name or forget it with a second explicit confirmation. Removing the library entry **never deletes game files or uninstalls AMDNR**. Game folder paths are chosen during addition; remove and re-add an entry to move it to another folder.

Equivalent command-line operations:

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --custom-games-json
python3 Launcher/Avalonia/amdnr_launcher.py --add-custom-game "/path/to/game" --custom-name "My Game"
python3 Launcher/Avalonia/amdnr_launcher.py --rename-custom-game "/path/to/game" --custom-name "New Name"
python3 Launcher/Avalonia/amdnr_launcher.py --remove-custom-game "/path/to/game"
```

The registry only stores the game's display name and local installation folder. Game installation files are never modified when adding, editing, or forgetting the entry.

## Configuration editor, extensions, health and release management

**Game details → Configure AMDNR** opens the actual UTF-8 `OptiScaler.ini`
beside the selected Windows EXE. The editor displays discovered INI sections and
supports raw edits without guessing unsupported setting names. On explicit Save
it creates a timestamped backup under
`${XDG_STATE_HOME:-~/.local/state}/amdnr/config-backups/` and refuses changes
when the file has been edited since opening. Unknown INI keys and comments
remain in the editor. Edits to launcher-installed INI files intentionally show
as **modified** in a subsequent integrity check; they are not silently
overwritten during uninstall.

**Game details → Manage Extensions** reads `plugins/*.asi` and `plugins/*.dll`
from the selected executable's folder. The supported loader is OptiScaler's
`[Plugins] LoadAsiPlugins=true`. Enable/Disable is an explicit, backed-up INI
change. **Import Local .ASI** copies a user-chosen plugin into the game
`plugins` directory without replacing existing files. The launcher tracks a
SHA-256 digest of each imported plugin in
`${XDG_STATE_HOME:-~/.local/state}/amdnr/managed-extensions/`. It only
offers removal for its own unmodified imports; third-party and changed
plugins are left untouched. Plugin loading is not verified at runtime.
Only import plugins from trusted sources, especially for multiplayer or
anti-cheat-protected games.

**Installed → Verify All Installed Files** runs the existing hash-based
installation check on demand for each indexed AMDNR installation and reports
healthy/needs-attention states, missing or modified files and missing
backups. The normal Installed view remains fast and metadata-only.

**Installed → Check Available Versions** fetches upstream release metadata and
shows published packages alongside installed archive names. A chosen ZIP can
be downloaded and SHA-256 verified for a **manual** update. The installer does
not replace an existing installation automatically: review the current
installation, preserve backups, and uninstall/restore before installing a
different package. There is no automated rollback yet, and old installer
records may not identify a release tag exactly.

**Settings** saves the default proxy DLL, absolute release download directory,
and whether to display prerelease versions in the release picker at
`${XDG_CONFIG_HOME:-~/.config}/amdnr/launcher-settings.json`. These settings
are read on startup. They do not trigger library rescans.

CLI equivalents:

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --settings-json
python3 Launcher/Avalonia/amdnr_launcher.py --ini-json --exe "/path/to/game.exe"
python3 Launcher/Avalonia/amdnr_launcher.py --extensions-json --exe "/path/to/game.exe"
python3 Launcher/Avalonia/amdnr_launcher.py --installed-games-json
```

## Installed Games dashboard

Select **Installed** in the sidebar for a compact inventory of AMDNR
installation records associated with saved game executables. The dashboard
reads the existing differential library index and only checks each selected
executable's adjacent `.amdnr-linux-install.json` record. It shows the
recorded proxy DLL, tracked file count, original archive name (when known),
and flags unreadable or malformed records. Use **Open Game** to manage the
selected installation or **Open Folder** to inspect its location.

This page **does not** perform Steam discovery, recursively scan games, hash
DLLs, change game files, or prove that the installation works under Proton.
For a real integrity check, use Doctor or **Verify Installed Files**.

Terminal equivalent:

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --installed-games-json
```

Games without a remembered Windows EXE are not included until selected or
analyzed; offline custom games remain in the Library but cannot have their
installed files checked while their drives are unavailable.

## Per-game quick setup

The selected-game page includes a **GAME SETUP / QUICK ACTIONS** panel:
it displays readiness without rescanning, offers **Copy EXE Path** and **Open
Game Folder**, and reads the game's existing Steam Launch Options from the
local user configuration (`Steam/userdata/<profile>/config/localconfig.vdf`)
without modifying it. The launcher shows both the **existing options** and
a **final copyable preview**, inserting the AMDNR DLL override while preserving
other environment variables, wrappers, and game arguments. If the original
contains `WINEDLLOVERRIDES`, the target DLL is merged without discarding other
DLL settings. Missing or conflicting Steam profiles and complex override
expressions produce a warning instead of an unsafe automatic merge.

For an existing recorded AMDNR installation, the override uses the recorded
proxy DLL rather than an unrelated default selection. ASI plugins are
explicitly shown as requiring a compatible loader, not a DLL override.
No game files or Steam settings are changed while reading or copying options.
The Steam options reader is a small per-game lookup, **not** a library rescan.

Read the same preview from a terminal:

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --steam-user-options-json \
  "/path/to/steamapps/common/Game" --alias dxgi.dll
```

The **Install** page now updates its launch-options preview immediately when
the proxy DLL choice changes. Copying options only copies text; the launcher
does not edit Steam settings automatically. Anti-cheat and Proton/runtime
compatibility are not guaranteed.

## Differential library updates and remembered executables

Normal startup and **Refresh** now use a persistent game index stored at
`${XDG_STATE_HOME:-~/.local/state}/amdnr/library-index.json`.
Instead of crawling every game for executables, the launcher reads installed
Steam `appmanifest_*.acf` records and the saved custom-game registry, then
reconciles this index:

- Keep unchanged installed entries and their last known Windows `.exe`.
- Check that remembered `.exe` and cover-art files still exist; drop stale
  executable references without changing game files.
- Add newly installed Steam games and custom entries, and remove Steam entries
  whose installations/manifests have disappeared.
- Retain custom entries on temporarily disconnected drives. Explicit user
  executable preferences remain separate from this index.
- Opening a game with a valid indexed `.exe` reuses it immediately; the game's
  **Rescan** action can rebuild its candidates. The Library's
  **Rescan Library** performs the deeper all-games executable scan and updates
  both the audit snapshot and executable index.

The index is saved atomically with owner-only permissions. Normal Refresh does
**not** perform a full executable scan or replace the saved audit with newly
computed readiness results. Previously saved readiness can be out of date until
you explicitly rescan.

```bash
# Fast manifest reconciliation; also persists the index
python3 Launcher/Avalonia/amdnr_launcher.py --library-differential-json

# Full executable audit, only when requested
python3 Launcher/Avalonia/amdnr_launcher.py --library-audit-json
```

## Library readiness audit

On the **Library** page, select **Analyze Library** to perform an on-demand
executable audit of every detected Steam game and remembered custom
installation. It reads game files but does not modify them. The finished
results are saved atomically to
`${XDG_STATE_HOME:-~/.local/state}/amdnr/library-audit.json` and restored when
Avalonia starts again. Normal **Refresh**, restarting the launcher, and
switching screens **do not** rebuild or delete the saved results. Only clicking
**Analyze Library** initially or **Rescan Library** later triggers another
full audit. Newly discovered games may have no readiness label until the next
requested rescan, and saved results can become stale after game updates.

Each library row gains a readiness label. The filter can show **Windows ready**,
**Native Linux**, **Needs attention**, and **AMDNR recorded** entries. An
unavailable custom-game mount is marked as a missing folder without removing
the saved game. A game with multiple possible Windows executables is marked
**Choose Windows executable** rather than silently guessing. A saved manual
EXE takes precedence over Steam metadata, followed by a unique Steam launch
target, then scanner heuristics.

An **AMDNR recorded** label means that an installation record exists alongside
the selected executable. It is not a file integrity or runtime compatibility
check; use **Install → Verify Installed Files** or Doctor for an integrity check.

Read the JSON directly without starting the GUI:

```bash
# Explicit full scan: also saves its result
python3 Launcher/Avalonia/amdnr_launcher.py --library-audit-json

# Instant last-saved result: never scans game executables
python3 Launcher/Avalonia/amdnr_launcher.py --library-audit-cache-json
```

## Steam launch metadata (automatic Windows EXE selection)

For **Steam-managed** installations, the launcher first matches the game directory to an installed `steamapps/appmanifest_<AppID>.acf`. It then reads the matching AppID from Steam's **local, read-only** `appcache/appinfo.vdf` (v40/v41) or modern `appcache/appinfo/appinfo_XX.vdf` shards (v42). This requires no Steam credentials, no network requests, no additional Python packages, and no Steam console commands.

Steam's `config/launch` data can declare Windows and Linux launch targets, or platform-neutral **All OSes** launch options with no `oslist` field. An unlabeled launch entry is considered a Windows candidate only if it points to an existing `.exe`; an explicit Linux entry is never treated as Windows. The launcher prefers **one existing, ordinary Windows target** over filename-based guessing. If Steam describes its only installed Windows target using a named or typed launch option, that unique target is also accepted when it has no beta, DLC, or non-default-realm restriction. Multiple optional targets remain manual choices. It does not automatically select missing Windows files, beta-only entries, DLC/workshop tools, Steam runtime/tool entries, or ambiguous primary targets. **Saved manual executable choices always take precedence**, including those for custom non-Steam installations. If Steam's cache is absent, unrecognized or incomplete, existing filesystem scanning and manual selection still work.

To inspect a particular Steam installation:

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --steam-launch-json "/path/to/steamapps/common/Game"
python3 Launcher/Avalonia/amdnr_launcher.py --exe-scan-json "/path/to/steamapps/common/Game"
```

The first command reports cached launch metadata and whether Steam has a **present Windows executable** for the installation; the second shows how the combined Steam-plus-filesystem scanner would select an EXE. The Steam report also lists `metadata_sections`, `launch_entries`, `windows_declared`, `windows_missing`, `windows_invalid`, and `linux_declared` so you can distinguish a missing launch section from Windows paths that are declared but not installed. For example, Steam may declare a Windows `game/bin/win64/cs2.exe` and Linux `game/cs2.sh`, but a Linux-native installation may only contain the latter. In that case the Windows executable is **not** installed and cannot be selected as an AMDNR DLL target. Filesystem scans and cached launch definitions cannot prove runtime compatibility or bypass anti-cheat restrictions.

## Windows executable discovery

A detected Steam library entry is not necessarily a Windows/Proton game. Native Linux releases may contain ELF executables or shell launchers but no `.exe`. The game screen now reports those cases explicitly and **does not** offer the native binary as an AMDNR DLL installation target.

Windows EXE discovery scans deeper directory layouts, skips symlinks, and continues past unreadable directories. The scan is bounded to avoid unresponsive browsing. If no Windows EXE is found, the UI explains whether native Linux launchers were found or the scan was incomplete. You can still browse to a Windows EXE manually if the game's Steam launch configuration uses a separate Windows build.

```bash
python3 Launcher/Avalonia/amdnr_launcher.py --exe-scan-json "/path/to/steamapps/common/Game"
```

The JSON result contains `candidates`, `native`, `reason`, and `partial`. Suggestions use path structure, not hardcoded game names, and never verify actual Proton compatibility.

## Investigate games whose Windows executable was not detected

The separate, **read-only** diagnostic script `tools/analyze_executables.py` inspects installed game structures without modifying files, using the network, or hardcoding game names. It reports relative file paths, file-extension distributions, executable depth, PE/ELF/script signatures, suspicious extension mismatches, and what the launcher actually detected.

From the repository root, examine all games without an automatically selected or remembered executable:

```bash
python3 Launcher/Avalonia/tools/analyze_executables.py --missing-only > /tmp/amdnr-exe-layouts.json
```

Or examine a particular game, plus a working comparison if useful:

```bash
python3 Launcher/Avalonia/tools/analyze_executables.py \
  --game "/mnt/Games/SteamLibrary/steamapps/common/ProblemGame" \
  --game "/mnt/Games/SteamLibrary/steamapps/common/WorkingGame" \
  > /tmp/amdnr-exe-comparison.json
```

The script also accepts `--all` for all detected Steam installations, `--examples 40` for more candidates, and `--max-files 60000` for unusually large games. It never follows symlinks, reads only the first bytes of potential executable files, and caps traversal. **Nothing is uploaded**: the JSON is written locally. It deliberately omits absolute install paths, but game names and game-relative filenames can still be identifying; review the report before sharing. PE signatures found in files with unexpected extensions are **evidence to investigate**, not proof they are safe installation targets.

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


### Official AMDNR release components (Mochi / lmxxf / WrongGPU)

Open a selected Windows game's **Manage Extensions** screen. Under **Official AMDNR Components**, choose **Load Official Components**, select an archive, then **Download & Preview**. The Linux backend obtains component ZIPs exclusively from the official `3zwr1/AMD-NR---OptiScaler` release assets and verifies each against the release's `SHA256SUMS.txt`. Review the exact archive paths and conflicts before using **Install Previewed Component**. Byte-identical existing files are preserved. Differing regular files can only be replaced through a separately labeled **Back Up & Replace Conflicts** action; ordinary installation never overwrites existing files. Originals are backed up outside the game and restored on component removal only if the installed replacement is still unchanged. Symlinks and unsafe conflicts always block installation. Base AMDNR installation health checks may report replaced files as modified until the component is removed and originals are restored.

Launcher-managed release components are tracked separately from imported `.asi` plugins under XDG state. Removing a component first checks every recorded file digest and refuses to delete modified or missing files. Existing user/third-party components are never claimed as launcher-managed. Component archives are installed with the directory layout inside the ZIP, so preview the file paths and confirm they suit the selected game. This feature manages files only; Proton compatibility or model activation is not guaranteed. Catalog lookup is on-demand and never triggers a Steam library rescan.


### Guided Daniel neural runtime setup

The **Get Daniel 0.6.0** button in **Game → Manage Extensions** resolves
`v0.6.0-Runtime.zip` from the official upstream release
`Alpha0.3.5.5R4` (not the Linux launcher fork). It downloads and checks
the ZIP against that release's SHA-256 manifest, then previews installation.
Only the three `dlssnr_amd_pass*.dll` files, the
`dlssnr_on_amd_weights.bin` model, and optional attribution file are allowed.
These are installed **beside the selected game executable/OptiScaler.dll**;
the ZIP's own proxy, setup, or unrelated files are not installed.
Installation remains an explicit second click, and existing differing files
require the separate opt-in backup-and-replace flow. This is a separate
runtime choice from Mochi: Daniel does not fix a Mochi detection failure.

The runtime diagnostic screen distinguishes files copied successfully from
a runtime detected by AMDNR. `MochizukiNrRuntime.dll` being present does not
prove that the current OptiScaler binary recognizes or initializes Mochi;
in-game detection and Proton compatibility require independent testing.

### Preparing Mochi's local neural model under Linux

Official Mochi component archives include the runtime, shaders and ACO records
but **not** NVIDIA's neural model. In **Game → Manage Extensions**, use
**Prepare Mochi Model (Local NVIDIA DLL)** and select your own
`nvngx_dlssnr.dll` version **310.9.16** or **310.8.0**, or a ZIP containing
that DLL. The bundled MIT-licensed `model-tools` scripts originate from
`Overclockers/DLSSNR-AMD` (see `model-tools/LICENSE`).

Model preparation reads the DLL locally without loading it, checks the
source SHA-256 against the supported versions, verifies every extracted model
weight against the tool's known checksum lists, and then installs
`dlssnr-amd/dlssnr.bin` (and `dlssnr-small.bin` for 310.9.16).
The launcher does **not** distribute NVIDIA DLLs or extracted model weights.
Existing model files are never replaced automatically. Extraction needs
`bash`, `python3` and adequate scratch disk space. Restart your game after
preparing the model. In-game Mochi availability still depends on GPU,
graphics API, the installed AMDNR build and Proton behavior.


### Opt-in community download for Mochi model preparation

The Linux launcher offers **Use Unofficial Mirror & Prepare Mochi** as an
optional alternative to choosing a local NVIDIA DLL. It currently resolves
the separate `dlssnr-310.9.16-nvidia` GitHub release from `RankFTW/rhi-repo`, explicitly identified by its publisher as the **original NVIDIA-signed** binary. The unqualified `dlssnr-310.9.16` release contains a modified DLL that does not match the extractor’s supported source hash.
**This is an unofficial third-party mirror.** Neither NVIDIA nor AMDNR
operates it, and redistribution authorization has not been independently
established. The UI makes this distinction explicit; the user must choose
the community-source action to start a download. This does not ship an
NVIDIA binary within the Linux launcher or the project repository.

Before the model extractor runs, the launcher pins and verifies the archive
SHA-256 (`5277355f0578d36f2a25413d8c7ff4c6f9966cea5bad714305f23b20173e09f6`)
and the internal DLL SHA-256
(`2bc19bc09a7b89dd44f73e2ac0108fcc586e2154bdd0830f242f4f040e28789f`).
It also checks the fixed release asset's GitHub digest, expected byte length,
archive format and extracted member count/size. The source DLL is not loaded
or executed, only inspected by the bundled locally verified model extractor.
Both downloaded ZIP and DLL are deleted on completion or failure. A source
change or hash mismatch **fails closed**; users can still choose their own
supported local DLL/ZIP without using the community mirror. No direct
real-world model extraction and in-game initialization has been confirmed
by the Linux launcher CI tests.

### Browse and switch official Daniel runtime versions

In **Game → Manage Extensions → Browse Daniel Versions**, the Linux launcher
lists distinct versioned `vX.Y.Z-Runtime.zip` assets found in the complete
official `3zwr1/AMD-NR---OptiScaler` GitHub release history, newest first.
For example, the upstream releases contain Daniel **0.8.0**, **0.6.0**,
**0.5.1**, **0.5.0**, **0.4.x**, and **0.3.x** runtime archives.
The application does not invent a Daniel 0.9.0 release if no official ZIP
exists. Select a version and choose **Download & Preview**; installed
version selection is always explicit. SHA-256 verification uses the upstream
release manifest where available and a GitHub-published SHA-256 asset digest
where the historical release has no checksum manifest.

The launcher **does not stack multiple Daniel versions** in one game.
Use the existing **Remove Component** action to restore original files and
remove the current managed Daniel runtime *before* installing another version.
Removal rejects third-party modifications and missing backups; a failed
switch cannot silently overwrite a previously managed runtime. Installed
legacy versions may not be compatible with the newest AMDNR in-game binary.
Unversioned `Runtime.zip` and `Daniel-*-Manual-*.zip` are not treated as
dedicated runtime packages, since their version/layout semantics differ.

### Dedicated Daniel Neural Runtimes panel

**Game → Manage Extensions** now shows a separate **Daniel Neural Runtimes**
panel below the official Mochi/lmxxf/WrongGPU component manager. Daniel has
its own version picker, upstream release discovery, checked ZIP preview,
explicit install/backed-up replacement controls, and a dedicated installed
runtime list with managed removal.

**Daniel 0.8.0 is a NeuralHub host, not a 0.6.0-style pass-DLL runtime.**
Its official v0.8.0 ZIP does not contain the four required legacy filenames;
the older installer therefore reported a misleading "Empty component
archive". The interface now explains that 0.8.0 requires a separate
NeuralHub-specific installer and does not permit the legacy installation
path to overwrite game files. Earlier supported pass-DLL versions remain
available under the Daniel section; compatibility under Proton is not
guaranteed. The general component selector excludes Daniel packages.

### Version-driven Daniel setup (Linux)

The **Daniel Neural Runtimes** version list now loads automatically on opening
Extensions. **Set Up Selected Daniel** determines the installation procedure
from the chosen official package rather than having a hard-coded 0.6.0 button.
For supported pass-DLL archives it downloads, verifies the published SHA-256,
previews file differences and installs immediately when destinations are safe.
If a user-owned file differs, it offers the existing explicit backup-and-replace
step; it never silently overwrites or removes a different installed runtime.
The separate "Install Daniel" and "Auto Set Up Daniel 0.6.0" buttons are removed.

The 0.8.0 NeuralHub path is *not* falsely reported as installed: it requires
Windows AMD GPU services not currently provided by Proton's bridge. Its
upstream package is not compatible with the legacy pass-DLL installer.
Complete end-to-end 0.8.0 support therefore requires a genuinely working
Linux HIP/D3D12 bridge and real GPU validation, not just copying ZIP files.
The launcher reports this blocker for the selected version without changing
the game's files. Runtime availability is distinct from file installation.
