"""The main window.

Intentionally slim: a rig picker, a connect button, a status indicator, and
what the radio is doing right now. The site half arrives in M3.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..control import Limits
from ..paths import config_dir, ensure_config_dir, rigs_path, sites_path
from ..profiles import (
    DUMMY_PROFILE_NAME,
    RigProfile,
    dummy_profile,
    load_profiles,
    save_profiles,
    with_unique_name,
)
from ..rig import RigHealth, RigState, dump_caps, list_models
from ..site import Phase, SessionInfo, SiteClient, SiteProfile, load_sites, save_sites
from .controller import TuneController
from .profile_dialog import ProfileDialog
from .telemetry import Telemetry
from .token_dialog import TokenDialog
from .worker import RigWorker


def format_frequency(hz: int | None) -> str:
    """14195000 -> '14.195.000' — grouped the way operators read frequencies."""
    if not hz:
        return "—"
    text = f"{hz:,}".replace(",", ".")
    return f"{text} Hz"


class MainWindow(QMainWindow):
    """Rig picker, connection state, and live rig readout."""

    _connect_requested = Signal(object)
    _disconnect_requested = Signal()
    # Rig commands cross a thread boundary and must go by signal: calling the
    # worker directly would touch its socket and timers from the GUI thread.
    _frequency_requested = Signal(int)
    _mode_requested = Signal(str, int)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("catnector")
        ensure_config_dir()

        self._profiles: list[RigProfile] = []
        self._sites: list[SiteProfile] = []
        self._models = self._load_models()

        self.profile_box = QComboBox()
        self.connect_button = QPushButton("Connect")
        self.edit_button = QPushButton("Edit…")
        self.add_button = QPushButton("Add…")
        self.remove_button = QPushButton("Remove")

        self.site_box = QComboBox()
        self.site_connect_button = QPushButton("Connect")
        self.add_site_button = QPushButton("Add…")
        self.remove_site_button = QPushButton("Remove")
        self.site_status_label = QLabel()
        self.identity_label = QLabel("—")
        self.following_label = QLabel("—")

        self.tuning_mode = QComboBox()
        self.tuning_mode.addItem("Tune automatically", False)
        self.tuning_mode.addItem("Ask me first", True)
        self.control_label = QLabel("—")
        self.control_label.setWordWrap(True)
        self.accept_button = QPushButton("Tune now")
        self.decline_button = QPushButton("Ignore")
        self.accept_button.setVisible(False)
        self.decline_button.setVisible(False)

        self.session_label = QLabel()
        self.rig_label = QLabel()
        self.frequency_label = QLabel("—")
        self.mode_label = QLabel("—")
        self.hamlib_label = QLabel("—")

        font = self.frequency_label.font()
        font.setPointSize(font.pointSize() + 8)
        self.frequency_label.setFont(font)
        self.frequency_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._build_layout()
        self._build_menu()
        self._start_worker()

        self.connect_button.clicked.connect(self._toggle_connection)
        self.add_button.clicked.connect(self._add_profile)
        self.edit_button.clicked.connect(self._edit_profile)
        self.remove_button.clicked.connect(self._remove_profile)
        self.profile_box.currentIndexChanged.connect(self._profile_selected)
        self.site_connect_button.clicked.connect(self._toggle_site)
        self.add_site_button.clicked.connect(self._add_site)
        self.remove_site_button.clicked.connect(self._remove_site)
        self.site_box.currentIndexChanged.connect(self._site_selected)
        self.tuning_mode.currentIndexChanged.connect(self._tuning_mode_changed)
        self.accept_button.clicked.connect(self._control.accept_pending)
        self.decline_button.clicked.connect(self._control.dismiss_pending)

        self.reload_profiles()
        self.reload_sites()
        self._set_status("Not connected", RigHealth.OFFLINE)

    # ------------------------------------------------------------- building

    @staticmethod
    def _load_models():
        try:
            return list_models()
        except Exception:
            return []

    def _build_layout(self) -> None:
        picker = QHBoxLayout()
        picker.addWidget(self.profile_box, 1)
        picker.addWidget(self.add_button)
        picker.addWidget(self.edit_button)
        picker.addWidget(self.remove_button)

        rig_box = QGroupBox("Rig")
        rig_layout = QVBoxLayout(rig_box)
        rig_layout.addLayout(picker)
        rig_layout.addWidget(self.connect_button)

        site_picker = QHBoxLayout()
        site_picker.addWidget(self.site_box, 1)
        site_picker.addWidget(self.add_site_button)
        site_picker.addWidget(self.remove_site_button)

        control_buttons = QHBoxLayout()
        control_buttons.addWidget(self.control_label, 1)
        control_buttons.addWidget(self.accept_button)
        control_buttons.addWidget(self.decline_button)

        site_readout = QFormLayout()
        site_readout.addRow("Signed in as", self.identity_label)
        site_readout.addRow("Following", self.following_label)
        site_readout.addRow("Remote tuning", self.tuning_mode)
        site_readout.addRow("Status", self.site_status_label)

        site_box = QGroupBox("Site")
        site_layout = QVBoxLayout(site_box)
        site_layout.addLayout(site_picker)
        site_layout.addWidget(self.site_connect_button)
        site_layout.addLayout(site_readout)
        site_layout.addLayout(control_buttons)
        self._site_group = site_box

        readout = QFormLayout()
        readout.addRow("Frequency", self.frequency_label)
        readout.addRow("Mode", self.mode_label)
        readout.addRow("Status", self.rig_label)
        readout.addRow("hamlib", self.hamlib_label)

        state_box = QGroupBox("Now")
        state_box.setLayout(readout)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(rig_box)
        layout.addWidget(state_box)
        layout.addWidget(site_box)
        layout.addWidget(self.session_label)
        layout.addStretch(1)
        self.setCentralWidget(central)
        self.resize(470, 560)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        reveal = QAction("Open config folder", self)
        reveal.triggered.connect(self._reveal_config)
        file_menu.addAction(reveal)

        reload_action = QAction("Reload profiles from disk", self)
        reload_action.triggered.connect(self.reload_profiles)
        file_menu.addAction(reload_action)

        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        about = QAction("About catnector", self)
        about.triggered.connect(self._about)
        self.menuBar().addMenu("&Help").addAction(about)

    def _start_worker(self) -> None:
        """Rig I/O gets its own thread; the GUI thread does none."""
        self._thread = QThread(self)
        self._worker = RigWorker()
        self._worker.moveToThread(self._thread)

        self._connect_requested.connect(self._worker.connect_to)
        self._disconnect_requested.connect(self._worker.disconnect_from)
        self._frequency_requested.connect(self._worker.set_frequency)
        self._mode_requested.connect(self._worker.set_mode)
        self._worker.connected.connect(self._on_connected)
        self._worker.disconnected.connect(self._on_disconnected)
        self._worker.state_changed.connect(self._on_state)
        self._worker.failed.connect(self._on_failed)
        # The worker must be destroyed on the thread it lives on, or Qt
        # complains that its timers are being stopped from another thread.
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

        # The site connection is event-driven and never blocks, so unlike the
        # rig it belongs on the GUI thread (docs/PLANNING.md §8.4).
        self._site = SiteClient(self)
        self._site.phase_changed.connect(self._on_site_phase)
        self._site.welcomed.connect(self._on_welcomed)
        self._site.closed.connect(self._on_site_closed)
        self._site.failed.connect(self._on_site_failed)
        self._site.follow_state_changed.connect(self._on_follow_state)

        # The safety envelope sits between the site and the radio (§10).
        self._control = TuneController(self)
        self._site.set_rig_received.connect(self._control.submit)
        self._control.apply_requested.connect(self._apply_tune)
        self._control.accepted.connect(self._ack_tune)
        self._control.refused.connect(self._nack_tune)
        self._control.announced.connect(self._on_announcement)
        self._control.pending_changed.connect(self._on_pending_tune)

        self._telemetry = Telemetry(self)
        self._worker.state_changed.connect(self._telemetry.rig_state_changed)
        self._telemetry.report_ready.connect(self._site.send)

    # -------------------------------------------------------------- profiles

    @property
    def current_profile(self) -> RigProfile | None:
        index = self.profile_box.currentIndex()
        if 0 <= index < len(self._profiles):
            return self._profiles[index]
        return None

    def reload_profiles(self) -> None:
        """Re-read rigs.ini. The file is meant to be hand-edited."""
        stored = load_profiles(rigs_path())
        self._profiles = [dummy_profile(), *stored]
        remembered = self.profile_box.currentText()
        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        for profile in self._profiles:
            self.profile_box.addItem(profile.name)
        index = self.profile_box.findText(remembered)
        self.profile_box.setCurrentIndex(max(index, 0))
        self.profile_box.blockSignals(False)
        self._profile_selected()

    def _persist(self) -> None:
        save_profiles(rigs_path(), self._profiles)

    def _profile_selected(self) -> None:
        profile = self.current_profile
        built_in = profile is not None and profile.name == DUMMY_PROFILE_NAME
        self.edit_button.setEnabled(profile is not None and not built_in)
        self.remove_button.setEnabled(profile is not None and not built_in)
        if profile is not None:
            self.session_label.setText(profile.describe())

    def _add_profile(self) -> None:
        dialog = ProfileDialog(models=self._models, parent=self)
        if dialog.exec() != ProfileDialog.Accepted:
            return
        profile = with_unique_name(self._profiles, dialog.profile())
        self._profiles.append(profile)
        self._persist()
        self.reload_profiles()
        self.profile_box.setCurrentText(profile.name)

    def _edit_profile(self) -> None:
        profile = self.current_profile
        if profile is None or profile.name == DUMMY_PROFILE_NAME:
            return
        dialog = ProfileDialog(profile, models=self._models, parent=self)
        if dialog.exec() != ProfileDialog.Accepted:
            return
        self._profiles[self.profile_box.currentIndex()] = dialog.profile()
        self._persist()
        self.reload_profiles()

    def _remove_profile(self) -> None:
        profile = self.current_profile
        if profile is None or profile.name == DUMMY_PROFILE_NAME:
            return
        confirm = QMessageBox.question(
            self, "Remove profile", f"Remove the profile '{profile.name}'?"
        )
        if confirm != QMessageBox.Yes:
            return
        self._profiles.remove(profile)
        self._persist()
        self.reload_profiles()

    # ------------------------------------------------------------ connection

    @property
    def connected(self) -> bool:
        return self.connect_button.text() == "Disconnect"

    def _toggle_connection(self) -> None:
        if self.connected:
            self._disconnect_requested.emit()
            return
        profile = self.current_profile
        if profile is None:
            return
        self.connect_button.setEnabled(False)
        self._set_status(f"Connecting to {profile.name}…", RigHealth.OFFLINE)
        self._connect_requested.emit(profile)

    def _on_connected(self, peer) -> None:
        self._site.set_rig_available(True)
        self._control.limits = Limits(caps=self._caps_for_current_profile())
        self.connect_button.setEnabled(True)
        self.connect_button.setText("Disconnect")
        self.hamlib_label.setText(
            f"{peer.version_text}{' (VFO mode)' if peer.vfo_mode else ''}"
        )
        self._set_status("Connected", RigHealth.OK)

    def _on_disconnected(self, reason: str) -> None:
        self._site.set_rig_available(False)
        self._control.reset()
        self.connect_button.setEnabled(True)
        self.connect_button.setText("Connect")
        self.frequency_label.setText("—")
        self.mode_label.setText("—")
        self.hamlib_label.setText("—")
        self._set_status(reason or "Not connected", RigHealth.OFFLINE)

    def _caps_for_current_profile(self):
        """Frequency limits come from hamlib, per rig, with no radio needed."""
        profile = self.current_profile
        if profile is None:
            return None
        try:
            return dump_caps(profile.model, profile.rigctld_path or None)
        except Exception:
            return None

    def _on_state(self, state: RigState) -> None:
        self._control.set_rig_state(state)
        self.frequency_label.setText(format_frequency(state.freq_hz))
        mode = state.mode or "—"
        if state.passband_hz:
            mode = f"{mode} / {state.passband_hz} Hz"
        self.mode_label.setText(mode)
        if state.health is RigHealth.OK:
            self._set_status("Connected", RigHealth.OK)
        else:
            self._set_status(state.detail or state.health.value, state.health)

    def _on_failed(self, message: str) -> None:
        self.connect_button.setEnabled(True)
        QMessageBox.warning(self, "Rig", message)

    def _set_status(self, text: str, health: RigHealth) -> None:
        colour = {RigHealth.OK: "#2e7d32", RigHealth.ERROR: "#c62828"}.get(health, "#757575")
        self.rig_label.setText(text)
        self.rig_label.setStyleSheet(f"color: {colour};")

    # ---------------------------------------------------------------- sites

    @property
    def current_site(self) -> SiteProfile | None:
        index = self.site_box.currentIndex()
        if 0 <= index < len(self._sites):
            return self._sites[index]
        return None

    def reload_sites(self) -> None:
        stored = load_sites(sites_path())
        self._sites = stored
        remembered = self.site_box.currentText()
        self.site_box.blockSignals(True)
        self.site_box.clear()
        for site in self._sites:
            self.site_box.addItem(site.name)
        index = self.site_box.findText(remembered)
        self.site_box.setCurrentIndex(max(index, 0))
        self.site_box.blockSignals(False)
        self._site_selected()

    def _site_selected(self) -> None:
        site = self.current_site
        self.remove_site_button.setEnabled(site is not None)
        self.site_connect_button.setEnabled(site is not None)
        if site is not None and not self._site.online:
            self.site_status_label.setText(f"Not connected to {site.host}")

    def _add_site(self) -> None:
        dialog = TokenDialog(self)
        if dialog.exec() != TokenDialog.Accepted:
            return
        profile = dialog.profile()
        self._sites = [s for s in self._sites if s.name != profile.name]
        self._sites.append(profile)
        save_sites(sites_path(), self._sites)
        self.reload_sites()
        self.site_box.setCurrentText(profile.name)

    def _remove_site(self) -> None:
        site = self.current_site
        if site is None:
            return
        confirm = QMessageBox.question(
            self, "Remove site", f"Remove the site '{site.name}' and its token?"
        )
        if confirm != QMessageBox.Yes:
            return
        self._sites.remove(site)
        save_sites(sites_path(), self._sites)
        self.reload_sites()

    def _toggle_site(self) -> None:
        if self._site.phase in (
            Phase.ONLINE,
            Phase.CONNECTING,
            Phase.DISCOVERING,
            Phase.HANDSHAKING,
        ):
            self._site.disconnect_from()
            return
        site = self.current_site
        if site is None:
            return
        try:
            token = site.decoded()
        except Exception as exc:
            QMessageBox.warning(self, "Token", str(exc))
            return
        self._site.set_rig_snapshot(self._rig_snapshot())
        self._site.connect_to(token, site_name=site.name)

    def _rig_snapshot(self) -> dict:
        """The rig block sent in `hello` (SPEC.md §7.1)."""
        profile = self.current_profile
        state = self._worker.last_state
        return {"profile": profile.name if profile else "", "health": state.health.value}

    def _on_site_phase(self, phase: str) -> None:
        busy = phase in (
            Phase.DISCOVERING.value,
            Phase.CONNECTING.value,
            Phase.HANDSHAKING.value,
        )
        self.site_connect_button.setText(
            "Disconnect" if phase == Phase.ONLINE.value or busy else "Connect"
        )
        messages = {
            Phase.DISCOVERING.value: "Looking up the site…",
            Phase.CONNECTING.value: "Connecting…",
            Phase.HANDSHAKING.value: "Signing in…",
            Phase.STOPPED.value: "Disconnected — needs your attention",
            Phase.OFFLINE.value: "Not connected",
        }
        if phase in messages:
            self.site_status_label.setText(messages[phase])
        if phase != Phase.ONLINE.value:
            self.identity_label.setText("—")
            self.following_label.setText("—")
            self._telemetry.stop()
            self._control.reset()

    def _on_welcomed(self, session: SessionInfo) -> None:
        profile = self.current_profile
        self._telemetry.configure(
            session.telemetry_interval_ms, profile.name if profile else ""
        )
        self._telemetry.start()
        # A callsign is a label, never an identifier (SPEC.md §7.2).
        self.identity_label.setText(f"{session.identity} at {session.host}")
        self.site_status_label.setText(
            f"Connected — reporting every {session.telemetry_interval_ms} ms"
        )
        self.site_status_label.setStyleSheet("color: #2e7d32;")

    def _on_site_closed(self, code: int, explanation: str, terminal: bool) -> None:
        self.site_status_label.setStyleSheet("color: #c62828;" if terminal else "")
        if terminal:
            # Never silently drop to a disconnected state with no reason
            # (docs/PLANNING.md §5).
            QMessageBox.warning(self, "Disconnected", explanation)
            self.site_status_label.setText("Disconnected — reconnect manually")
        else:
            self.site_status_label.setText(f"{explanation} Reconnecting…")

    def _on_site_failed(self, message: str) -> None:
        self.site_status_label.setText(message)

    def _on_follow_state(self, following) -> None:
        """Display only — catnector derives no behaviour from it."""
        self.following_label.setText(following or "—")
        self._control.following = following

    def _tuning_mode_changed(self) -> None:
        self._control.manual = bool(self.tuning_mode.currentData())
        if not self._control.manual:
            self._control.dismiss_pending()

    def _apply_tune(self, request) -> None:
        """Reached only after the envelope in §10 has allowed it."""
        self._frequency_requested.emit(request.freq_hz)
        if request.mode:
            self._mode_requested.emit(request.mode, request.passband_hz or 0)

    def _ack_tune(self, message_id: str) -> None:
        self._site.accept({"id": message_id})

    def _nack_tune(self, message_id: str, reason: str, detail: str) -> None:
        # A refusal the site can show to whoever pressed the button beats
        # silence, which would leave them believing the radio moved.
        self._site.reject({"id": message_id}, reason, detail)

    def _on_announcement(self, text: str, seconds: int) -> None:
        if not text:
            self.control_label.setText("—")
            self.control_label.setStyleSheet("")
            return
        if seconds > 0:
            self.control_label.setText(f"{text} — in {seconds}s")
            self.control_label.setStyleSheet("color: #c62828; font-weight: bold;")
        else:
            self.control_label.setText(text)
            self.control_label.setStyleSheet("")

    def _on_pending_tune(self, request) -> None:
        waiting = request is not None
        self.accept_button.setVisible(waiting)
        self.decline_button.setVisible(waiting)
        if waiting:
            self.control_label.setText(
                f"{request.source or 'A site'} asks to tune to {request.describe()}"
            )
            self.control_label.setStyleSheet("font-weight: bold;")
        else:
            self.control_label.setText("—")
            self.control_label.setStyleSheet("")

    # ----------------------------------------------------------------- menu

    def _reveal_config(self) -> None:
        """§4 is about hand-copying these files; the path must be findable."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ensure_config_dir())))

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "About catnector",
            "\n".join(
                [
                    f"catnector {__version__}",
                    "",
                    "Stages your rig's frequency and mode from a spotting site.",
                    "It never keys the transmitter.",
                    "",
                    f"Configuration: {config_dir()}",
                    f"hamlib: {self.hamlib_label.text()}",
                ]
            ),
        )

    def closeEvent(self, event) -> None:
        self._site.disconnect_from()
        self._telemetry.stop()
        # Queued, so teardown runs on the worker's own thread; quit() is
        # processed after it, and deleteLater (wired at startup) frees the
        # worker there too rather than from this thread.
        self._disconnect_requested.emit()
        self._thread.quit()
        self._thread.wait(5000)
        super().closeEvent(event)
