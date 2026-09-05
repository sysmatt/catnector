#!/usr/bin/env bash
# Build a Linux AppImage from the PyInstaller one-directory bundle.
#
# AppImage rather than a bare binary or a .deb: one file, no installation, no
# package manager, and it runs across distributions — which is what Linux
# hams expect of desktop ham software.
#
#     ./packaging/build_appimage.sh
#
# appimagetool does not need to be installed: if it is not on PATH it is
# downloaded into build/ on first use. It is itself an AppImage, so it would
# normally need FUSE to run — APPIMAGE_EXTRACT_AND_RUN avoids that, since
# newer distributions no longer ship libfuse2.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

version="$(python -c 'import tomllib,pathlib;print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"
arch="$(uname -m)"
appdir="build/catnector.AppDir"

if [ ! -d dist/catnector ]; then
    echo "dist/catnector is missing — run pyinstaller first:" >&2
    echo "  pyinstaller packaging/catnector.spec --noconfirm" >&2
    exit 1
fi

rm -rf "$appdir"
mkdir -p "$appdir/usr/lib" "$appdir/usr/share/applications" \
         "$appdir/usr/share/icons/hicolor/256x256/apps"

cp -a dist/catnector "$appdir/usr/lib/catnector"
install -m 755 packaging/AppRun "$appdir/AppRun"
install -m 644 packaging/catnector.desktop "$appdir/catnector.desktop"
install -m 644 packaging/catnector.desktop \
    "$appdir/usr/share/applications/catnector.desktop"
install -m 644 packaging/catnector.png "$appdir/catnector.png"
install -m 644 packaging/catnector.png \
    "$appdir/usr/share/icons/hicolor/256x256/apps/catnector.png"

tool="$(command -v appimagetool || true)"
if [ -z "$tool" ]; then
    tool="build/appimagetool-${arch}.AppImage"
    if [ ! -x "$tool" ]; then
        echo "downloading appimagetool"
        curl -fsSL -o "$tool" \
            "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${arch}.AppImage"
        chmod +x "$tool"
    fi
fi

output="dist/catnector-${version}-${arch}.AppImage"
ARCH="$arch" APPIMAGE_EXTRACT_AND_RUN=1 "$tool" --no-appstream "$appdir" "$output"
echo "built $output"
