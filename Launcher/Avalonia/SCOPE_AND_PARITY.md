# Linux launcher scope and Windows parity rules

The Linux launcher is **an AMDNR installer and runtime manager**, not a
general-purpose gaming suite, GPU benchmarking application, or replacement
for Steam, Heroic, Lutris, GameMode, MangoHud, or the Proton settings UI.

Its primary workflow should match the official AMDNR Windows launcher:

1. Discover an installed game and identify the correct Windows executable.
2. Select a verified release directly from the official AMDNR repository.
3. Preview safe changes and apply managed installation/updates.
4. Set up compatible AMDNR runtime/model extensions where required.
5. Check file integrity, diagnose AMDNR runtime problems and safely repair.
6. Restore original game files and managed backups on removal.

Linux-specific features are justified only to support that workflow: Steam
launch-option previews, per-game Proton compatibility readiness, DLL override
selection, explicit anti-cheat warnings, GPU/runtime checks, and installing
the launcher on Linux.

The original Windows launcher is **not modified** by this development branch.
Game payloads and runtime components use official `3zwr1/AMD-NR---OptiScaler`
releases and verified SHA-256 assets. Fork-hosted downloads are permitted
only for the independent **Linux launcher executable**, never for upstream
AMDNR game packages. The optional third-party Mochi model source remains
clearly opt-in and verified; it is not misrepresented as official.

The Linux app does not set Steam's Proton version or silently rewrite Steam
config. It does not bundle ROCm driver installation, bypass anti-cheat, or
make unsupported NeuralHub 0.8.0 run merely by copying ZIPs. Compatibility
claims must say whether a runtime's files exist, AMDNR detects it, or actual
neural rendering has been tested.

## Feature status

| Windows parity / Linux capability | Linux status | Remaining validation |
| --- | --- | --- |
| Steam/custom game discovery | Implemented | Steam test coverage |
| Heroic/Lutris install discovery | Implemented from local metadata | More installation variants |
| Differential library updates | Implemented | Large library performance |
| Official AMDNR release downloads | Implemented with SHA-256 | Live upstream availability |
| Managed install/uninstall & backups | Implemented | Real game interruption tests |
| Safe AMDNR repair/updates | Implemented with transaction journal | Real package upgrades, power loss |
| Proxy retry & launch override preview | Implemented | Test ReShade and game-specific DLLs |
| Installed dashboard | Implemented | UI polish |
| INI editor | Implemented | Verify game-specific formats |
| Local ASI and official extension management | Implemented | Runtime integration |
| Mochi preparation | Verified by user on Deadlock | Inference performance on other GPUs |
| Daniel legacy releases | Version-selected package setup | Runtime initialization under Proton |
| Daniel 0.8 NeuralHub | **Blocked** | Missing compatible Proton GPU bridge |
| GPU/Proton/anti-cheat diagnostics | Implemented (informational) | Hardware and varied Steam installs |
| Local redacted support bundle | Implemented | Privacy audit on logs |
| Linux AppImage/Flatpak CI definitions | Implemented | Actual artifact build and smoke launch |
| Linux launcher self-update | Implemented for user-owned AppImages | Tagged release and restart test |
| Compact keyboard / controller interface | Keyboard/compact mode implemented | Full controller navigation still needed |

Unrelated standalone frame-time analysis was removed from Doctor. Any
performance-monitoring integration must remain optional and tied directly
to diagnosing AMDNR behavior rather than becoming a second application.
