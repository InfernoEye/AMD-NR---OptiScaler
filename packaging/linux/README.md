# Linux distribution packaging

The scripts package ONLY the independent Avalonia/Linux backend
(`Launcher/Avalonia/`) and its MIT-licensed model tools. They do
not bundle the Windows launcher or any NVIDIA binaries.

Build the self-contained executable and portable AppDir:

    dotnet publish Launcher/Avalonia/Amdnr.Avalonia.csproj -c Release -r linux-x64 --self-contained true -p:PublishSingleFile=true -o dist/publish
    uv python install 3.12 --install-dir dist/managed-python
    bash packaging/linux/build-appdir.sh dist/publish dist/AMDNR-Linux.AppDir dist/managed-python

The portable AppDir bundles a managed CPython 3.12 runtime (including the standard library), the Python backend, model tools, and a self-contained .NET 10 Avalonia launcher. No system Python or .NET SDK is required to start it. The AppImage still requires a compatible x86_64 Linux system, glibc, graphical desktop libraries, GPU drivers, Steam/Proton where applicable, and working filesystem permissions. Game runtime compatibility is not guaranteed.

For AppImage, install a trusted checksum-verified appimagetool and run:

    ARCH=x86_64 appimagetool --appimage-extract-and-run dist/AMDNR-Linux.AppDir dist/AMDNR-Linux-x86_64.AppImage

CI pins the upstream appimagetool published SHA-256 before running it. The first beta is an explicitly marked GitHub prerelease only after the package CI job succeeds; it ships AppImage, tarball, and SHA-256 checksums.

For Flatpak, see `packaging/flatpak/org.amdnr.LinuxLauncher.yml`. It
bundles the independent backend and .NET executable. Because AMDNR must
modify games on custom Steam library disks, its Flatpak sandbox asks for
broad filesystem access. Review these permissions before installation.
A sandbox is not a GPU driver compatibility bridge and cannot bypass
anti-cheat restrictions.
