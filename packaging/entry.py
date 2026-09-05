"""Frozen-application entry point.

A separate launcher rather than `catnector/__main__.py`: PyInstaller runs the
given script as `__main__` with no package context, so the relative imports
inside the package would fail.
"""

from __future__ import annotations

import sys

from catnector.cli import main

if __name__ == "__main__":
    sys.exit(main())
