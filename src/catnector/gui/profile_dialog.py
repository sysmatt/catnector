"""Editing one rig profile.

The form is generated from hamlib's own capabilities rather than
hand-maintained: pick a radio and catnector already knows whether it is
serial or network, which baud rates are legal *for that rig*, and what it
can and cannot do. Better than making the operator know their own baud rate
(docs/PLANNING.md §8.3).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from ..profiles import ATTACH, MANAGED, RigProfile
from ..rig import RigCaps, RigModel, dump_caps, list_models
from ..serialports import check_port, list_serial_ports


class ProfileDialog(QDialog):
    """Create or edit a rig profile."""

    def __init__(
        self,
        profile: RigProfile | None = None,
        models: list[RigModel] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rig profile")
        self._profile = profile or RigProfile(name="New rig")
        self._caps: RigCaps | None = None

        self.name = QLineEdit(self._profile.name)

        self.model = QComboBox()
        self.model.setEditable(True)  # 300+ entries; let people type
        self.model.completer().setCompletionMode(QComboBox.PopupCompletion)
        self.model.completer().setFilterMode(Qt.MatchContains)
        for entry in models if models is not None else self._load_models():
            self.model.addItem(entry.label, entry.model)

        self.connection = QComboBox()
        self.connection.addItem("Let catnector manage the radio", MANAGED)
        self.connection.addItem("Attach to a rigctld I am already running", ATTACH)

        self.device = QComboBox()
        self.device.setEditable(True)
        self.device.addItems(list_serial_ports())

        self.speed = QComboBox()
        self.host = QLineEdit(self._profile.host)
        self.port = QSpinBox()
        self.port.setRange(0, 65535)
        self.port.setSpecialValueText("automatic")
        self.port.setValue(self._profile.port)
        self.rigctld_path = QLineEdit(self._profile.rigctld_path)
        self.rigctld_path.setPlaceholderText("bundled or found on PATH")

        self.summary = QLabel()
        self.summary.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Radio", self.model)
        form.addRow("Connection", self.connection)
        form.addRow("Serial port", self.device)
        form.addRow("Speed", self.speed)
        form.addRow("Host", self.host)
        form.addRow("Port", self.port)
        form.addRow("rigctld", self.rigctld_path)
        self._form = form

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.summary)
        layout.addWidget(buttons)

        self.model.currentIndexChanged.connect(self._model_changed)
        self.connection.currentIndexChanged.connect(self._refresh_fields)

        self._select_model(self._profile.model)
        self.connection.setCurrentIndex(0 if self._profile.connection == MANAGED else 1)
        self._model_changed()
        if self._profile.device:
            self.device.setCurrentText(self._profile.device)
        if self._profile.serial_speed:
            self.speed.setCurrentText(str(self._profile.serial_speed))

    @staticmethod
    def _load_models() -> list[RigModel]:
        try:
            return list_models()
        except Exception:
            return []

    def _select_model(self, model: int) -> None:
        index = self.model.findData(model)
        if index >= 0:
            self.model.setCurrentIndex(index)

    # ------------------------------------------------------- caps-driven UI

    def _model_changed(self) -> None:
        model = self.model.currentData()
        self._caps = None
        if isinstance(model, int):
            try:
                self._caps = dump_caps(model)
            except Exception:
                self._caps = None

        self.speed.clear()
        if self._caps:
            # Only the rates legal for *this* radio, where hamlib knows them;
            # a generic list rather than an empty one where it does not.
            self.speed.addItems(str(rate) for rate in self._caps.offered_speeds)
            if self.speed.count():
                self.speed.setCurrentIndex(self.speed.count() - 1)
        self._refresh_fields()

    def _refresh_fields(self) -> None:
        attach = self.connection.currentData() == ATTACH
        serial = bool(self._caps and self._caps.needs_device) and not attach
        network = bool(self._caps and self._caps.is_network) or attach

        for widget, visible in (
            (self.device, serial),
            (self.speed, serial),
            (self.host, network),
            (self.port, network),
            (self.rigctld_path, not attach),
        ):
            widget.setVisible(visible)
            label = self._form.labelForField(widget)
            if label is not None:
                label.setVisible(visible)

        self.summary.setText(self._describe())

    def _describe(self) -> str:
        if self.connection.currentData() == ATTACH:
            return (
                "catnector will connect to a rigctld you are already "
                "running, and will not start or stop it. Use this to share "
                "one radio with WSJT-X or a logger."
            )
        if self._caps is None:
            return "Capabilities for this radio could not be read."
        bits = [f"{self._caps.port_type or 'unknown'} connection"]
        if self._caps.can_get_ptt:
            bits.append(
                "reports PTT, so catnector can wait rather than retune during a transmission"
            )
        else:
            bits.append("cannot report PTT, so the transmit guard will not apply")
        if not self._caps.can_set_freq:
            bits.append("cannot have its frequency set — this radio will not work")
        return ". ".join(bits).capitalize() + "."

    # ---------------------------------------------------------------- result

    def profile(self) -> RigProfile:
        speed = self.speed.currentText()
        return RigProfile(
            name=self.name.text().strip() or "Unnamed rig",
            model=int(self.model.currentData() or 1),
            connection=self.connection.currentData(),
            device=self.device.currentText().strip() if self.device.isVisible() else "",
            serial_speed=int(speed) if speed.isdigit() and self.speed.isVisible() else None,
            host=self.host.text().strip() or "127.0.0.1",
            port=self.port.value(),
            rigctld_path=self.rigctld_path.text().strip(),
        )

    def accept(self) -> None:
        """Refuse to save a profile that obviously cannot work."""
        profile = self.profile()
        if self._caps and self._caps.needs_device and not profile.is_attach:
            check = check_port(profile.device)
            if not check.usable:
                QMessageBox.warning(self, "Serial port", check.advice)
                return
        super().accept()
