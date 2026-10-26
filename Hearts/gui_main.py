"""Graphical Hearts: ``python gui_main.py`` (needs ``pip install -r requirements-gui.txt``)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from gui.qt.app import main

if __name__ == "__main__":
    raise SystemExit(main())
