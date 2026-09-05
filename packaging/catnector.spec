# PyInstaller spec for catnector.
#
# One directory on Linux (it becomes the AppImage's payload); one file on
# Windows, where a single .exe is what a non-developer expects to download.
# Set CATNECTOR_ONEFILE=1 to force the single-file form.
#
#     pyinstaller packaging/catnector.spec --noconfirm
#
# Unsigned on both platforms for now — see docs/PLANNING.md §9.1 for why, and
# what signing would cost.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

sys.path.insert(0, str(Path(SPECPATH)))
from hamlib_files import collect as collect_hamlib  # noqa: E402

ONEFILE = os.environ.get("CATNECTOR_ONEFILE", "1" if os.name == "nt" else "0") == "1"

hamlib_binaries = collect_hamlib(Path(SPECPATH).parent / "build" / "hamlib-stage")
if not hamlib_binaries:
    print("WARNING: no hamlib binaries bundled; this build needs hamlib installed")

analysis = Analysis(
    [str(Path(SPECPATH) / "entry.py")],
    pathex=[str(Path(SPECPATH).parent / "src")],
    binaries=hamlib_binaries,
    # Without the dist-info, importlib.metadata cannot report a version and
    # every bug report says "0.0.0+unknown".
    datas=copy_metadata("catnector"),
    hiddenimports=["catnector.gui.mainwindow"],
    # Qt modules catnector does not use, which otherwise add hundreds of
    # megabytes to a download aimed at people on domestic connections.
    excludes=[
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtTest",
        "PySide6.QtSql", "PySide6.QtPdf", "PySide6.QtOpenGL",
        "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
        "PySide6.QtSerialPort", "PySide6.QtSensors",
        "tkinter", "pytest", "unittest",
    ],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

if ONEFILE:
    executable = EXE(
        pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
        name="catnector",
        console=False,
        strip=False,
        upx=False,
        icon=str(Path(SPECPATH) / "catnector.ico"),
    )
else:
    executable = EXE(
        pyz, analysis.scripts, [],
        exclude_binaries=True,
        name="catnector",
        console=False,
        strip=False,
        upx=False,
        icon=str(Path(SPECPATH) / "catnector.ico"),
    )
    COLLECT(
        executable, analysis.binaries, analysis.datas,
        strip=False, upx=False, name="catnector",
    )
