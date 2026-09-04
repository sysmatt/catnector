"""Catnector's PySide6 interface."""

from __future__ import annotations

import sys


def run(argv: list[str] | None = None) -> int:
    """Start the application. Imports Qt lazily so ``--version`` stays cheap."""
    from PySide6.QtWidgets import QApplication

    from .mainwindow import MainWindow

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("catnector")
    app.setOrganizationName("catnector")

    window = MainWindow()
    window.show()
    return app.exec()


__all__ = ["run"]
