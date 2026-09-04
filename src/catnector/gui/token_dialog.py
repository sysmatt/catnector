"""Adding a site by pasting a token.

One paste and catnector is configured: the token carries the endpoint
hostname, so there is no separate "enter the server URL" step (SPEC.md §4.1).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..site import SiteProfile, TokenError, decode


class TokenDialog(QDialog):
    """Paste a token, confirm what it points at, name it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a site")

        self.token = QPlainTextEdit()
        self.token.setPlaceholderText("cnx1_…")
        self.token.setFixedHeight(70)
        self.name = QLineEdit()
        self.name.setPlaceholderText("named automatically from the token")

        self.feedback = QLabel()
        self.feedback.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Token", self.token)
        form.addRow("Name", self.name)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Paste the token your site gave you. It carries the address, so "
                "there is nothing else to fill in."
            )
        )
        layout.addLayout(form)
        layout.addWidget(self.feedback)
        layout.addWidget(self.buttons)

        self.token.textChanged.connect(self._validate)

    def _validate(self) -> None:
        text = self.token.toPlainText().strip()
        if not text:
            self.feedback.setText("")
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        try:
            token = decode(text)
        except TokenError as exc:
            # A damaged token reads differently from a rejected one, and the
            # operator can act on the difference.
            self.feedback.setText(str(exc))
            self.feedback.setStyleSheet("color: #c62828;")
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return

        self.feedback.setStyleSheet("color: #2e7d32;")
        self.feedback.setText(f"This token connects to {token.host}.")
        if not self.name.text().strip():
            self.name.setText(token.host)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)

    def profile(self) -> SiteProfile:
        text = self.token.toPlainText().strip()
        name = self.name.text().strip() or decode(text).host
        return SiteProfile(name=name, token=text)
