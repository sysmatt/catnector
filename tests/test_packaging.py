"""Packaging inputs.

Building a bundle needs PyInstaller and takes minutes, so it belongs in CI
(`.github/workflows/release.yml`) rather than here. What these check is the
part that silently rots: the spec's inputs, and the runtime's ability to find
what a bundle ships.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from catnector.rig.daemon import EXECUTABLE, _environment_for, bundle_root, bundled_dir

PACKAGING = Path(__file__).resolve().parent.parent / "packaging"


def test_the_packaging_inputs_exist():
    for name in (
        "catnector.spec",
        "entry.py",
        "hamlib_files.py",
        "AppRun",
        "catnector.desktop",
        "catnector.png",
        "catnector.ico",
        "build_appimage.sh",
    ):
        assert (PACKAGING / name).is_file(), name


def test_the_desktop_entry_is_well_formed():
    text = (PACKAGING / "catnector.desktop").read_text()
    assert text.startswith("[Desktop Entry]")
    for required in ("Type=Application", "Name=", "Exec=", "Icon=", "Categories="):
        assert required in text
    assert "HamRadio" in text


def test_the_entry_point_avoids_relative_imports():
    """PyInstaller runs the script as __main__ with no package context."""
    text = (PACKAGING / "entry.py").read_text()
    assert "from catnector.cli import main" in text
    assert "from ." not in text


@pytest.mark.hamlib
def test_the_collector_finds_the_programs_a_bundle_needs(tmp_path):
    sys.path.insert(0, str(PACKAGING))
    try:
        from hamlib_files import PROGRAMS, collect
    finally:
        sys.path.pop(0)

    collected = collect(tmp_path)
    names = {Path(source).stem for source, _ in collected}
    # rigctl matters as much as rigctld: the rig picker and the
    # capability-driven setup form are built from it.
    for program in PROGRAMS:
        assert program in names, f"{program} was not collected"
    assert all(destination == "bin" for _, destination in collected)


def test_nothing_is_bundled_when_running_from_source():
    assert bundle_root() is None
    assert bundled_dir().name == "bin"


def test_an_installed_rigctld_keeps_the_environment_it_was_installed_into():
    """Only *our* binaries get the bundle's library path forced on them."""
    outside = Path("/usr/bin") / EXECUTABLE
    environment = _environment_for(outside)
    assert environment.get("LD_LIBRARY_PATH") == __import__("os").environ.get("LD_LIBRARY_PATH")
