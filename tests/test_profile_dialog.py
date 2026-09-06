"""The rig profile editor.

These exist because it shipped broken: `QComboBox.PopupCompletion` does not
exist (the enum belongs to QCompleter), so the Add button raised on every
click and the primary way a new user configures a radio did nothing at all.
No test had ever constructed this dialog.

The lesson is cheap to encode: build every dialog at least once.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from catnector.gui.profile_dialog import ProfileDialog
from catnector.profiles import ATTACH, MANAGED, RigProfile
from catnector.rig import RigModel

MODELS = [
    RigModel(model=1, manufacturer="Hamlib", name="Dummy"),
    RigModel(model=1035, manufacturer="Yaesu", name="FT-991"),
    RigModel(model=4, manufacturer="FLRig", name=""),
]


@pytest.fixture
def dialog(qtbot):
    widget = ProfileDialog(models=MODELS)
    qtbot.addWidget(widget)
    return widget


def test_the_dialog_can_be_opened_at_all(dialog):
    """The regression test for the shipped bug."""
    assert dialog.model.count() == len(MODELS)
    assert dialog.profile().name


def test_editing_an_existing_profile_shows_its_values(qtbot):
    existing = RigProfile(
        name="Shack FT-991", model=1035, device="/dev/ttyUSB0", serial_speed=38400
    )
    widget = ProfileDialog(existing, models=MODELS)
    qtbot.addWidget(widget)
    assert widget.name.text() == "Shack FT-991"
    assert widget.model.currentData() == 1035
    assert widget.profile().model == 1035


def test_the_picker_never_shows_a_bare_model_number(dialog):
    for index in range(dialog.model.count()):
        label = dialog.model.itemText(index)
        assert label and not label.isdigit()


def test_a_new_profile_round_trips_through_the_dialog(dialog):
    dialog.name.setText("Club rig")
    produced = dialog.profile()
    assert produced.name == "Club rig"
    assert produced.connection in (MANAGED, ATTACH)


def test_attach_mode_hides_the_serial_fields(dialog):
    """Attaching to someone else's rigctld means catnector opens no port."""
    dialog.connection.setCurrentIndex(1)
    assert dialog.connection.currentData() == ATTACH
    assert dialog.host.isVisibleTo(dialog)
    assert not dialog.device.isVisibleTo(dialog)
    assert dialog.profile().is_attach


@pytest.mark.hamlib
def test_choosing_a_serial_rig_offers_only_its_own_speeds(qtbot):
    """The capability-driven part of the form (docs/PLANNING.md §8.3)."""
    widget = ProfileDialog(models=MODELS)
    qtbot.addWidget(widget)
    widget.model.setCurrentIndex(widget.model.findData(1035))  # FT-991
    speeds = [int(widget.speed.itemText(i)) for i in range(widget.speed.count())]
    assert speeds, "a serial rig must never be offered an empty speed list"
    assert 9600 in speeds
    assert widget.device.isVisibleTo(widget)


@pytest.mark.hamlib
def test_choosing_a_network_rig_hides_the_serial_fields(qtbot):
    widget = ProfileDialog(models=MODELS)
    qtbot.addWidget(widget)
    widget.model.setCurrentIndex(widget.model.findData(4))  # FLRig
    assert not widget.device.isVisibleTo(widget)
    assert widget.host.isVisibleTo(widget)


@pytest.mark.hamlib
def test_the_summary_says_whether_the_ptt_guard_will_apply(qtbot):
    """Setup is where an operator should learn this, not mid-QSO."""
    widget = ProfileDialog(models=MODELS)
    qtbot.addWidget(widget)
    widget.model.setCurrentIndex(widget.model.findData(1035))
    assert "ptt" in widget.summary.text().lower()
