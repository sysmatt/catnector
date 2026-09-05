"""Generate the application icon.

Kept as code so the icon is reproducible and can be regenerated at any size,
rather than a binary blob nobody can edit. Run after changing it::

    python packaging/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPen

BACKGROUND = QColor("#14212e")
DIAL = QColor("#8fb8d6")
MARKER = QColor("#f0a202")

SIZES = (16, 32, 48, 64, 128, 256, 512)


def draw(size: int) -> QImage:
    """A tuning dial: the one thing catnector does, drawn plainly."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    radius = size * 0.18
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(BACKGROUND))
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    inset = size * 0.24
    dial = QRectF(inset, inset, size - inset * 2, size - inset * 2)

    pen = QPen(DIAL)
    pen.setWidthF(max(size * 0.055, 1.0))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # An open arc, not a closed ring: a dial with a scale, not a target.
    painter.drawArc(dial, -55 * 16, 290 * 16)

    pen.setColor(MARKER)
    pen.setWidthF(max(size * 0.075, 1.0))
    painter.setPen(pen)
    centre = size / 2
    painter.drawLine(int(centre), int(inset * 0.55), int(centre), int(inset * 1.15))

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(MARKER))
    dot = size * 0.085
    painter.drawEllipse(QRectF(centre - dot, centre - dot, dot * 2, dot * 2))
    painter.end()
    return image


def main() -> int:
    QGuiApplication(sys.argv)
    target = Path(__file__).resolve().parent
    draw(256).save(str(target / "catnector.png"))
    # Windows executables take .ico only; Qt writes it, so no extra tooling.
    draw(256).save(str(target / "catnector.ico"), "ICO")
    print(f"wrote {target / 'catnector.png'} and catnector.ico")
    for size in SIZES:
        directory = target / "icons" / f"{size}x{size}"
        directory.mkdir(parents=True, exist_ok=True)
        draw(size).save(str(directory / "catnector.png"))
    print(f"wrote {len(SIZES)} sizes under {target / 'icons'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
