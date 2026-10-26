"""Qt tests run headless; they are skipped when PySide6 / pytest-qt are not installed."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path_factory):  # type: ignore[no-untyped-def]
    """Tests never read or write the user's real settings (registry on Windows)."""
    try:
        from PySide6.QtCore import QSettings
    except ImportError:
        yield
        return
    folder = tmp_path_factory.mktemp("qsettings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(folder))
    yield


def pytest_ignore_collect(collection_path, config):  # type: ignore[no-untyped-def]
    if collection_path.name.startswith("test_qt_"):
        try:
            import PySide6  # noqa: F401
            import pytestqt  # noqa: F401
        except ImportError:
            return True
    return None
