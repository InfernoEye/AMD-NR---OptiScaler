# External projects, acknowledgements and reuse policy

## AMDNR-Linux — community Linux compatibility research

Project: https://github.com/hassanm0301/AMDNR-Linux

Credit to **hassanm0301 and the AMDNR-Linux contributors** for their experimental
Linux ROCm/HIP bridge, Linux runtime validation, and practical Proton compatibility
research. Their published notes are useful references for our Linux compatibility
investigations, including GPU driver dependencies, runtime initialization and the
limits of controlled versus in-game testing.

**Relationship to this launcher as of this acknowledgement:** AMDNR-Linux is a
**research/reference project**. We have **not copied, linked, redistributed, or
integrated its source code or bridge binaries** into the independent Avalonia
launcher. Acknowledging a project does not imply endorsement, sponsorship or
that its runtime is already supported by our launcher.

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
