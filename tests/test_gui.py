"""GUI tests, run offscreen.

These are shallow on purpose: they check that the window wires up, that
profile CRUD reaches the file, and that a real connection to the dummy rig
drives the display. Anything deeper belongs in the layers underneath, which
are tested without Qt.
"""

from __future__ import annotations

import threading

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


@pytest.mark.protocol
def test_the_window_signs_in_to_a_site_and_shows_who_it_is(qtbot, window, config, mock_site):
    """Window -> token -> discovery -> handshake -> identity on screen."""
    from catnector.site import SiteProfile, encode, save_sites

    token = encode(mock_site.host, "gui-token")
    save_sites(config / "sites.ini", [SiteProfile(name="Reference", token=token)])
    window.reload_sites()
    assert window.site_box.count() == 1

    with qtbot.waitSignal(window._site.welcomed, timeout=20000):
        window._toggle_site()

    assert "K2TTA" in window.identity_label.text()
    assert mock_site.host in window.identity_label.text()
    assert "Connected" in window.site_status_label.text()
    assert window.site_connect_button.text() == "Disconnect"

    window._site.disconnect_from()
    qtbot.waitUntil(lambda: not window._site.online, timeout=10000)
    assert window.identity_label.text() == "—"


@pytest.mark.protocol
def test_follow_state_reaches_the_display_and_is_cleared(
    qtbot, window, config, mock_site, site_post
):
    from catnector.site import SiteProfile, encode, save_sites

    save_sites(
        config / "sites.ini",
        [SiteProfile(name="Reference", token=encode(mock_site.host, "gui2"))],
    )
    window.reload_sites()
    with qtbot.waitSignal(window._site.welcomed, timeout=20000):
        window._toggle_site()

    with qtbot.waitSignal(window._site.follow_state_changed, timeout=15000):
        site_post(mock_site.base, "/mock/follow_state", {"following": "W1ABC"})
    assert window.following_label.text() == "W1ABC"

    with qtbot.waitSignal(window._site.follow_state_changed, timeout=15000):
        site_post(mock_site.base, "/mock/follow_state", {"following": None})
    assert window.following_label.text() == "—"
    window._site.disconnect_from()


def test_a_damaged_token_is_refused_before_it_is_saved(qtbot, window):
    """The dialog will not enable OK for a token that cannot work."""
    from PySide6.QtWidgets import QDialogButtonBox

    from catnector.gui.token_dialog import TokenDialog
    from catnector.site import encode

    dialog = TokenDialog(window)
    qtbot.addWidget(dialog)
    ok = dialog.buttons.button(QDialogButtonBox.Ok)

    good = encode("example.org", "secret")
    dialog.token.setPlainText(good[:-2])
    assert not ok.isEnabled()
    assert "damaged" in dialog.feedback.text().lower()

    dialog.token.setPlainText(good)
    assert ok.isEnabled()
    assert "example.org" in dialog.feedback.text()
    assert dialog.profile().name == "example.org"


@pytest.mark.hamlib
@pytest.mark.protocol
def test_the_mvp_loop_a_site_tunes_the_radio(qtbot, window, config, mock_site, site_post):
    """Site -> safety envelope -> rig, and telemetry back the other way.

    This is what catnector exists to do.
    """
    from catnector.site import SiteProfile, encode, save_sites

    save_sites(
        config / "sites.ini",
        [SiteProfile(name="Reference", token=encode(mock_site.host, "mvp"))],
    )
    window.reload_sites()

    with qtbot.waitSignal(window._worker.connected, timeout=20000):
        window._toggle_connection()
    with qtbot.waitSignal(window._site.welcomed, timeout=20000):
        window._toggle_site()

    # The site pushes a tune; the mock blocks until the client answers.
    result: dict = {}

    def push() -> None:
        result.update(
            site_post(
                mock_site.base,
                "/mock/set_rig",
                {"freq": 14195000, "mode": "USB", "source": "Following W1ABC"},
            )
        )

    thread = threading.Thread(target=push, daemon=True)
    thread.start()
    qtbot.waitUntil(lambda: bool(result), timeout=25000)
    thread.join(timeout=5)

    assert result["result"]["type"] == "ack"
    qtbot.waitUntil(lambda: window.frequency_label.text() == "14.195.000 Hz", timeout=15000)
    qtbot.waitUntil(lambda: "USB" in window.mode_label.text(), timeout=15000)
    assert "W1ABC" in window.control_label.text()

    # And the rig's new state is reported back up to the site.
    qtbot.waitUntil(
        lambda: any(r.get("freq") == 14195000 for r in _reports(mock_site, site_post)),
        timeout=15000,
    )

    window._site.disconnect_from()


def _reports(mock_site, site_post) -> list[dict]:
    import json
    import urllib.request

    with urllib.request.urlopen(f"{mock_site.base}/mock/status", timeout=10) as reply:
        status = json.load(reply)
    sessions = status.get("sessions") or []
    last = [s.get("last_report") for s in sessions if s.get("last_report")]
    return last


@pytest.mark.hamlib
@pytest.mark.protocol
def test_manual_mode_makes_a_tune_wait_for_the_operator(
    qtbot, window, config, mock_site, site_post
):
    from catnector.site import SiteProfile, encode, save_sites

    save_sites(
        config / "sites.ini",
        [SiteProfile(name="Reference", token=encode(mock_site.host, "manual"))],
    )
    window.reload_sites()
    with qtbot.waitSignal(window._worker.connected, timeout=20000):
        window._toggle_connection()
    with qtbot.waitSignal(window._site.welcomed, timeout=20000):
        window._toggle_site()

    window.tuning_mode.setCurrentIndex(1)  # "Ask me first"
    assert window._control.manual

    before = window.frequency_label.text()
    thread = threading.Thread(
        target=lambda: site_post(
            mock_site.base, "/mock/set_rig", {"freq": 14195000, "mode": "USB"}
        ),
        daemon=True,
    )
    thread.start()

    qtbot.waitUntil(lambda: window._control.pending is not None, timeout=20000)
    assert window.accept_button.isVisibleTo(window)
    assert window.frequency_label.text() == before, "nothing moves until accepted"
    assert "asks to tune" in window.control_label.text()

    with qtbot.waitSignal(window._control.apply_requested, timeout=10000):
        window.accept_button.click()
    qtbot.waitUntil(lambda: window.frequency_label.text() == "14.195.000 Hz", timeout=15000)
    thread.join(timeout=5)
    window._site.disconnect_from()
