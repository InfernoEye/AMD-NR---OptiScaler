# External projects, acknowledgements and reuse policy

## AMDNR-Linux — community Linux compatibility research

Project: https://github.com/hassanm0301/AMDNR-Linux

Credit to **hassanm0301 and the AMDNR-Linux contributors** for their experimental
Linux ROCm/HIP bridge, Linux runtime validation, and practical Proton compatibility
research. Their published notes are useful references for our Linux compatibility
investigations, including GPU driver dependencies, runtime initialization and the
limits of controlled versus in-game testing.

**Current integration:** Our independent launcher now has an **optional,
consent-gated adapter** in `Launcher/Avalonia/community_bridge.py`. It can
download and verify the original AMDNR-Linux **linux-v0.3.7** release archive
(SHA-256 `7e4ddb01a352a824bbf6009cfd8a1c0728267679e4a170d33fc8e01f91b84423`),
execute that release's own `linux/setup.py prepare`, and invoke its
`linux/manage.py install/uninstall` only with explicit user approval.
These original community programs and binaries remain in a user-local cache,
separate from our launcher's source and redistributable packages.

No AMDNR-Linux source code, HIP bridge, patched vkd3d-proton binaries, ROCm
runtime, or model weights were copied into our repository or bundled in our
AppImage. Invoking a separately fetched GPL work is not a claim that the
programs are our own. The original source, notices and companion corresponding
vkd3d source archive are linked from the upstream release page:
https://github.com/hassanm0301/AMDNR-Linux/releases/tag/linux-v0.3.7 .
Preserve those files and license notices if distributing a combined installation.

**Validation status:** The opt-in adapter and its conflict checks are under
automated launcher CI, but our integration has **not** been run against the
required RX 9070 XT and Wine 11 hardware, and Subnautica 2 has not been
verified to work. A user-supplied native Microsoft shader compiler and
separate verified runtime preparation are required. The adapter refuses
unmanaged game hooks and existing AMDNR installations rather than silently
overwriting them; it does not edit Steam settings automatically.

The GPL-3.0-or-later license covers the bridge and community scripts, while
the patched vkd3d libraries are LGPL-2.1-or-later and other upstream runtime,
compiler and model assets retain their own licenses. This acknowledgement
does not imply endorsement by the community maintainers or authors.

### License and future integrations

AMDNR-Linux publishes a GNU General Public License, version 3 (GPL-3.0),
at https://github.com/hassanm0301/AMDNR-Linux/blob/main/LICENSE .
GPL-3.0 permits use, modification and redistribution subject to its conditions,
including source availability, preservation of notices, and copyleft requirements
for covered derivative/combined works when distributed. It is not equivalent to
public domain, and a credit line alone does not satisfy those conditions.

Before adopting any code or binaries, verify the **specific file's provenance
and license**, third-party assets and any linked components, assess license
compatibility with the distribution, preserve original notices, record exact
upstream revisions/changes, and provide corresponding source where required.
If those obligations cannot be met, do not copy the component. Original,
independently authored integration informed by published behavior can be
considered separately.

When a component is actually incorporated, **update this file and the user-facing
credits** to explicitly identify:
- Upstream project and contributors
- Component/file(s) incorporated and exact upstream revision or release
- Applicable license(s), license locations, local modifications and source links
- How to obtain corresponding source where legally required

Do not mark an unimplemented ROCm bridge or unverified neural rendering
functionality as shipped or tested.

## AMDNR upstream and runtime authors

AMDNR game packages are sourced separately from the official
https://github.com/3zwr1/AMD-NR---OptiScaler releases and checked before use.
The Linux launcher is independent of the original Windows launcher.
Runtime authors retain their respective credits and licenses; this file does not
grant permission to redistribute proprietary or third-party runtime assets.
