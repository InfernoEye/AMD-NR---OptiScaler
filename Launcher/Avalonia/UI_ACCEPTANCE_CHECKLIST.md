# Linux Launcher UI Acceptance Check — November 2026

This checklist is for the **independent Avalonia Linux launcher** only.
It compares against user-provided screenshots of the official Windows launcher,
but does not copy its code and does not imply Windows-only features work on Proton.

## Use the correct build

Use a development-branch package produced from
`feature/native-linux-launcher`, or build that branch locally.
The published `linux-v0.1.0-beta.1` AppImage predates the new shell and guided tour.
Do not assess the November UI redesign using that prerelease.

Record the tested commit, screen resolution, desktop session, scale factor,
Avalonia version, distro, and whether Steam Input is active.

## Guided introduction: first-run and replay

1. On a new profile, open the launcher. The first callout should appear
   **beside a highlighted Library navigation control**, not in a separate window.
2. Next highlights the actual **Grid** button in the global topbar.
3. Next highlights the real **Library search field**.
4. Next opens **Installed**, then **Install**, **Doctor**, **Settings**, and **Help**.
   Each page and its navigation control should be visible under the callout.
5. Check Back/Next/Skip and Escape. Finishing or skipping returns to Library.
   Replaying from Settings or Help starts from step one.
6. Confirm the tour never downloads, installs, repairs, uninstalls or edits Steam.
7. Test both Grid/sidebar mode and List/top-navigation mode, especially at
   1280×800. Check that the popup never obscures its highlighted target.

## Original-reference visual expectations

- A compact global top bar holds the AMD/NR identity and Grid/List view controls.
- Grid has a left navigation rail; List puts navigation in that **same** top bar.
- The sidebar uses WORKSPACE / SYSTEM groups, icons, and red active-state accents.
- Game artwork and library cards appear ahead of advanced technical diagnostics.
- The advanced library readiness audit is expandable, rather than always open.
- Game details use artwork and user-reviewed installation actions.
- Doctor uses two-column cards on wide windows and stacks them when narrow.
- Footer status is separate from scrollable content.
- English and Polish controls remain readable without clipping.

## Interaction and safety

- Search, Grid/List switching, navigation, filters and artwork selection operate
  without changing installation records or Steam options.
- Button focus is visible when navigating by keyboard or gamepad.
- Check keyboard Tab/Shift+Tab and real joystick/Steam Deck mappings.
- Inspect every page at 1280×800 and 100%/125%/150% display scaling.
- Verify installer actions still require explicit user confirmation.
- The independent guided INI controls only preview existing supported keys;
  Save still uses SHA conflict checks and independent backups.

## Evidence and known limits

The GitHub Actions build and Linux backend workflows confirm compilation and
existing backend checks, **not** actual GUI appearance, controller hardware,
GPU/Proton compatibility or in-game neural rendering.

Capture screenshots of Library Grid, Library List, selected game, Doctor,
Settings, and walkthrough steps if available. Compare them to the official
reference screenshots, then track layout, focus, clipping and contrast issues.
Only files under `Launcher/Avalonia/` may be changed to address them.
