#!/usr/bin/env bash
# Build an independent, portable AppDir from the self-contained Avalonia publish.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PUBLISH="$1"
OUTPUT="$2"
PYTHON_EXE="${3:?Pass the uv-managed CPython executable path as argument 3}"
mkdir -p "$OUTPUT/usr/bin" "$OUTPUT/usr/lib/amdnr" \
  "$OUTPUT/usr/share/amdnr" "$OUTPUT/usr/share/applications" \
  "$OUTPUT/usr/share/icons/hicolor/128x128/apps"
cp -a "$PUBLISH/." "$OUTPUT/usr/lib/amdnr/"
# Bundle relocatable CPython and its full stdlib. Never depend on a tester's
# system Python version or on Python being installed at all.
if [ ! -x "$PYTHON_EXE" ]; then
  echo "Managed Python executable not found: $PYTHON_EXE" >&2
  exit 1
fi
PYTHON_ROOT="$(dirname "$(dirname "$(readlink -f "$PYTHON_EXE")")")"
if [ ! -d "$PYTHON_ROOT/lib" ]; then
  echo "Managed Python installation lacks a standard library: $PYTHON_ROOT" >&2
  exit 1
fi
cp -a "$PYTHON_ROOT" "$OUTPUT/usr/lib/amdnr-python"
if [ ! -e "$OUTPUT/usr/lib/amdnr-python/bin/python3" ]; then
  ln -s "$(basename "$PYTHON_EXE")" "$OUTPUT/usr/lib/amdnr-python/bin/python3"
fi
mkdir -p "$OUTPUT/usr/bin"
cat > "$OUTPUT/usr/bin/python3" <<'PYSH'
#!/usr/bin/env sh
set -eu
if [ -n "${APPDIR:-}" ]; then BASE="$APPDIR"; else BASE="$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)"; fi
exec "$BASE/usr/lib/amdnr-python/bin/python3" "$@"
PYSH
chmod +x "$OUTPUT/usr/bin/python3"
"$OUTPUT/usr/bin/python3" -c 'import ssl, zipfile, sqlite3; print("Bundled Python OK")'
cp "$ROOT/Launcher/Avalonia/"*.py "$OUTPUT/usr/share/amdnr/"
cp "$ROOT/Launcher/Avalonia/VERSION" "$OUTPUT/usr/share/amdnr/"
cp -a "$ROOT/Launcher/Avalonia/model-tools" "$OUTPUT/usr/share/amdnr/"
cp "$ROOT/packaging/linux/amdnr-linux.desktop" "$OUTPUT/usr/share/applications/"
python3 "$ROOT/packaging/linux/make_icon.py" \
  "$OUTPUT/usr/share/icons/hicolor/128x128/apps/amdnr-linux.png"
ln -sf usr/share/applications/amdnr-linux.desktop "$OUTPUT/amdnr-linux.desktop"
ln -sf usr/share/icons/hicolor/128x128/apps/amdnr-linux.png "$OUTPUT/amdnr-linux.png"
cat > "$OUTPUT/AppRun" <<'SH'
#!/usr/bin/env sh
set -eu
if [ -n "${APPDIR:-}" ]; then BASE="$APPDIR"; else BASE="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"; fi
export AMDNR_AVALONIA_BACKEND="$BASE/usr/share/amdnr/amdnr_launcher.py"
export PATH="$BASE/usr/bin:$PATH"
exec "$BASE/usr/lib/amdnr/Amdnr.Avalonia" "$@"
SH
chmod +x "$OUTPUT/AppRun" "$OUTPUT/usr/lib/amdnr/Amdnr.Avalonia"
cat > "$OUTPUT/usr/bin/amdnr-launcher" <<'SH'
#!/usr/bin/env sh
set -eu
BASE="$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)"
export AMDNR_AVALONIA_BACKEND="$BASE/usr/share/amdnr/amdnr_launcher.py"
exec "$BASE/usr/lib/amdnr/Amdnr.Avalonia" "$@"
SH
chmod +x "$OUTPUT/usr/bin/amdnr-launcher"
echo "Prepared AppDir: $OUTPUT"
