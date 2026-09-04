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
from ..paths import config_dir, ensure_config_dir, rigs_path
from ..profiles import (
    DUMMY_PROFILE_NAME,
    RigProfile,
    dummy_profile,
    load_profiles,
    save_profiles,
    with_unique_name,
)
from ..rig import RigHealth, RigState, list_models
from .profile_dialog import ProfileDialog
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

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("catnector")
        ensure_config_dir()

        self._profiles: list[RigProfile] = []
        self._models = self._load_models()

        self.profile_box = QComboBox()
        self.connect_button = QPushButton("Connect")
        self.edit_button = QPushButton("Edit…")
        self.add_button = QPushButton("Add…")
        self.remove_button = QPushButton("Remove")

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

        self.reload_profiles()
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
        layout.addWidget(self.session_label)
        layout.addStretch(1)
        self.setCentralWidget(central)
        self.resize(460, 360)

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
        self._worker.connected.connect(self._on_connected)
        self._worker.disconnected.connect(self._on_disconnected)
        self._worker.state_changed.connect(self._on_state)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

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
        self.connect_button.setEnabled(True)
        self.connect_button.setText("Disconnect")
        self.hamlib_label.setText(
            f"{peer.version_text}{' (VFO mode)' if peer.vfo_mode else ''}"
        )
        self._set_status("Connected", RigHealth.OK)

    def _on_disconnected(self, reason: str) -> None:
        self.connect_button.setEnabled(True)
        self.connect_button.setText("Connect")
        self.frequency_label.setText("—")
        self.mode_label.setText("—")
        self.hamlib_label.setText("—")
        self._set_status(reason or "Not connected", RigHealth.OFFLINE)

    def _on_state(self, state: RigState) -> None:
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
        self._disconnect_requested.emit()
        self._thread.quit()
        self._thread.wait(3000)
        super().closeEvent(event)
