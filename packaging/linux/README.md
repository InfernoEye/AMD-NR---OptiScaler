# Linux distribution packaging

The scripts package ONLY the independent Avalonia/Linux backend
(`Launcher/Avalonia/`) and its MIT-licensed model tools. They do
not bundle the Windows launcher or any NVIDIA binaries.

Build the self-contained executable and portable AppDir:

    dotnet publish Launcher/Avalonia/Amdnr.Avalonia.csproj -c Release -r linux-x64 --self-contained true -p:PublishSingleFile=true -o dist/publish
    bash packaging/linux/build-appdir.sh dist/publish dist/AMDNR-Linux.AppDir

The portable AppDir still needs system `python3` 3.10+ and Linux desktop
libraries, but it does not require the .NET SDK.

For AppImage, install a trusted checksum-verified appimagetool and run:

    ARCH=x86_64 appimagetool --appimage-extract-and-run dist/AMDNR-Linux.AppDir dist/AMDNR-Linux-x86_64.AppImage

CI pins the upstream appimagetool published SHA-256 before running it.

For Flatpak, see `packaging/flatpak/org.amdnr.LinuxLauncher.yml`. It
bundles the independent backend and .NET executable. Because AMDNR must
modify games on custom Steam library disks, its Flatpak sandbox asks for
broad filesystem access. Review these permissions before installation.
A sandbox is not a GPU driver compatibility bridge and cannot bypass
anti-cheat restrictions.
