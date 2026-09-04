"""GUI tests, run offscreen.

These are shallow on purpose: they check that the window wires up, that
profile CRUD reaches the file, and that a real connection to the dummy rig
drives the display. Anything deeper belongs in the layers underneath, which
are tested without Qt.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from catnector.gui.mainwindow import MainWindow, format_frequency
from catnector.profiles import RigProfile, load_profiles, save_profiles


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("CATNECTOR_CONFIG_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def window(qtbot, config):
    widget = MainWindow()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


@pytest.mark.parametrize(
    ("hz", "expected"),
    [(14195000, "14.195.000 Hz"), (7074000, "7.074.000 Hz"), (None, "—"), (0, "—")],
)
def test_frequency_is_grouped_the_way_operators_read_it(hz, expected):
    assert format_frequency(hz) == expected


def test_window_offers_the_dummy_rig_with_no_config(window):
    """Catnector must be demonstrable with no radio and no setup."""
    assert window.profile_box.count() == 1
    assert "Dummy" in window.profile_box.itemText(0)
    assert window.connect_button.text() == "Connect"


def test_the_builtin_profile_cannot_be_edited_or_removed(window):
    assert not window.edit_button.isEnabled()
    assert not window.remove_button.isEnabled()


def test_profiles_from_disk_are_listed(window, config):
    save_profiles(config / "rigs.ini", [RigProfile(name="Shack FT-991", model=1035)])
    window.reload_profiles()
    names = [window.profile_box.itemText(i) for i in range(window.profile_box.count())]
    assert "Shack FT-991" in names


def test_removing_a_profile_reaches_the_file(window, config, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    save_profiles(config / "rigs.ini", [RigProfile(name="Doomed", model=1035)])
    window.reload_profiles()
    window.profile_box.setCurrentText("Doomed")
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    window._remove_profile()
    assert load_profiles(config / "rigs.ini") == []


def test_config_folder_is_created_on_launch(window, config):
    assert (config / "rigs.ini").exists()
    assert (config / "sites.ini").exists()


@pytest.mark.hamlib
def test_connecting_to_the_dummy_rig_drives_the_display(window, qtbot):
    """The whole stack: window -> worker thread -> rigctld -> dummy rig."""
    with qtbot.waitSignal(window._worker.connected, timeout=20000):
        window._toggle_connection()
    assert window.connect_button.text() == "Disconnect"

    qtbot.waitUntil(lambda: window.frequency_label.text() != "—", timeout=10000)
    assert "Hz" in window.frequency_label.text()
    assert window.hamlib_label.text() not in ("", "—")

    with qtbot.waitSignal(window._worker.state_changed, timeout=10000):
        window._worker.set_frequency(14195000)
    qtbot.waitUntil(lambda: window.frequency_label.text() == "14.195.000 Hz", timeout=10000)

    with qtbot.waitSignal(window._worker.disconnected, timeout=10000):
        window._toggle_connection()
    assert window.connect_button.text() == "Connect"
    assert window.frequency_label.text() == "—"
