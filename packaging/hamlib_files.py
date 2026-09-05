"""Find the hamlib binaries a build should bundle.

Used by the PyInstaller spec. Run it by hand to see what a build would pick
up::

    python packaging/hamlib_files.py

Only the *executables* are collected. PyInstaller's own dependency analysis
follows them to `libhamlib.so.4` and friends and places those at the bundle
root under their sonames, so staging the libraries here as well would ship
every one of them twice — about 17 MB of duplication.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

#: Bundled so the operator never installs hamlib themselves. `rigctl` is
#: needed as well as `rigctld`: the rig picker and the capability-driven
#: setup form are built from `rigctl -l` and `--dump-caps`.
PROGRAMS = ("rigctld", "rigctl")


def _executable(name: str) -> Path | None:
    found = shutil.which(name + (".exe" if os.name == "nt" else ""))
    return Path(found) if found else None


def collect(stage: Path | None = None) -> list[tuple[str, str]]:
    """``(source, destination)`` pairs for PyInstaller's ``binaries``.

    Staged into a build directory first so the bundled filenames are stable
    regardless of how the host packaged hamlib.
    """
    stage = stage or Path("build") / "hamlib-stage"
    found = {name: path for name in PROGRAMS if (path := _executable(name)) is not None}
    if not found:
        return []

    stage.mkdir(parents=True, exist_ok=True)
    pairs = []
    for source in found.values():
        staged = stage / source.name
        if not staged.exists() or staged.stat().st_mtime < source.stat().st_mtime:
            shutil.copy2(source, staged)
        pairs.append((str(staged), "bin"))
    return pairs


if __name__ == "__main__":
    collected = collect()
    if not collected:
        print("no hamlib binaries found — the build will rely on PATH at runtime")
    for source, destination in collected:
        size = Path(source).stat().st_size / 1_000_000
        print(f"  {destination}/{Path(source).name:<20} {size:6.1f} MB")
    print("  hamlib's shared libraries are added by PyInstaller's own analysis")
