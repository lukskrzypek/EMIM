"""Deleting a bot's statistics (report tab), the memory-file dialog (lobby) and the lobby captions."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from gui.core.log_cleanup import (
    delete_bot_records,
    delete_memory_file,
    list_memory_files,
    preview_bot_records,
)
from gui.core.report_service import load_report
from gui.qt.lobby.lobby_view import LobbyView
from gui.qt.lobby.memory_dialog import MemoryDialog
from gui.qt.lobby.seat_row import SeatRow
from gui.core.seat_config import SeatKind
from gui.qt.report.report_view import ReportView
from test_core_live_quality import _play


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _groq_logs(tmp_path: Path) -> tuple[Path, Path]:
    exchanges, illegal = tmp_path / "groq_exchanges.jsonl", tmp_path / "groq_illegal_moves.jsonl"
    rows = [
        {"model": "m/x", "name": "", "n": 1},
        {"model": "m/x", "name": "bold", "n": 2},
        {"model": "m/x", "n": 3},  # an old record without the field: an unnamed bot
        {"model": "m/y", "name": "bold", "n": 4},
    ]
    exchanges.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    illegal.write_text(json.dumps(rows[1]) + "\nnot json\n\n" + json.dumps(rows[0]) + "\n", encoding="utf-8")
    return exchanges, illegal


# ------------------------------------------------------------------ core: log records


def _mixed_log(tmp_path: Path) -> tuple[Path, list[str]]:
    """Two sessions in one log: 4 players with ``last_legal``, then 3 players with ``other_bot``."""
    first, second, log = tmp_path / "a.jsonl", tmp_path / "b.jsonl", tmp_path / "trajectories.jsonl"
    _play(4, seed=31, log=first)
    _play(3, seed=7, log=second)
    kept = _lines(second)
    kept = [line.replace('"model": "last_legal"', '"model": "other_bot"') for line in kept]
    log.write_text("\n".join(_lines(first) + kept) + "\n", encoding="utf-8")
    first.unlink()
    second.unlink()
    return log, kept


def test_deleting_a_bot_removes_its_deals_whole_so_the_report_stays_valid(tmp_path: Path) -> None:
    log, second_session = _mixed_log(tmp_path)
    assert preview_bot_records("last_legal", log) == (13, 39)  # 1 of 4 players -> 13 own moves

    gone = delete_bot_records("last_legal", log, None, None)
    assert (gone.trajectories, gone.other_trajectories, gone.total) == (13, 39, 52)
    assert _lines(log) == second_session  # the second session is untouched
    report = load_report(log).report
    assert report is not None and not report.skipped and set(report.models) == {"other_bot", "smart_bot"}
    assert delete_bot_records("last_legal", log, None, None).total == 0  # nothing left to remove
    assert preview_bot_records("nobody", log) == (0, 0)


def test_delete_bot_records_in_the_groq_logs_tells_named_and_unnamed_apart(tmp_path: Path) -> None:
    trajectories = tmp_path / "trajectories.jsonl"
    exchanges, illegal = _groq_logs(tmp_path)

    gone = delete_bot_records("m/x_bold", trajectories, exchanges, illegal)  # no such log: fine
    assert (gone.trajectories, gone.exchanges, gone.illegal) == (0, 1, 1)
    assert [json.loads(x)["n"] for x in _lines(exchanges)] == [1, 3, 4]
    assert _lines(illegal) == ["not json", "", json.dumps({"model": "m/x", "name": "", "n": 1})]  # junk kept

    gone = delete_bot_records("m/x", trajectories, exchanges, illegal)  # the unnamed one only
    assert (gone.exchanges, gone.illegal) == (2, 1)
    assert [json.loads(x)["n"] for x in _lines(exchanges)] == [4]
    assert not list(tmp_path.glob("*.tmp")) and not trajectories.exists()


def test_delete_bot_records_survives_missing_files_and_empty_labels(tmp_path: Path) -> None:
    assert delete_bot_records("x", tmp_path / "a", tmp_path / "b", None).total == 0
    log = tmp_path / "t.jsonl"
    log.write_text('{"model": "x"}\n', encoding="utf-8")
    assert delete_bot_records("", log, None, None).total == 0
    assert _lines(log) == ['{"model": "x"}']


# ------------------------------------------------------------------ report view


def _report(qtbot, log: Path) -> ReportView:  # type: ignore[no-untyped-def]
    view = ReportView(log)  # the bot's own logs are looked up next to the trajectory log
    qtbot.addWidget(view)
    view.resize(1100, 700)
    view.show()
    with qtbot.waitSignal(view.finished, timeout=10000):
        view.refresh()
    return view


def test_report_deletes_the_selected_bot_after_confirmation(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    log, second_session = _mixed_log(tmp_path)
    exchanges, illegal = _groq_logs(tmp_path)
    view = _report(qtbot, log)
    names = [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
    assert set(names) == {"last_legal", "other_bot", "smart_bot"}
    view.table.selectRow(names.index("last_legal"))
    assert view.selected_label() == "last_legal" and view.delete_button.isEnabled()

    asked: list[str] = []
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]

    def question(parent, title, text, *args):  # type: ignore[no-untyped-def]
        asked.append(text)
        return answers.pop(0)

    monkeypatch.setattr(QMessageBox, "question", question)

    before = _lines(log)
    view.delete_button.click()  # "No": nothing happens
    assert _lines(log) == before and view.table.rowCount() == 3
    assert "last_legal" in asked[0] and "13" in asked[0] and "39" in asked[0]

    with qtbot.waitSignal(view.finished, timeout=10000):
        view.delete_button.click()  # "Yes"
    assert _lines(log) == second_session
    shown = {view.table.item(r, 0).text() for r in range(view.table.rowCount())}
    assert shown == {"other_bot", "smart_bot"}
    assert "usunięto „last_legal”" in view.status.text() and "Rekordów w logu" in view.status.text()
    assert len(_lines(exchanges)) == 4  # nobody of those logs was named last_legal


def test_report_deletion_clears_the_groq_logs_of_that_bot(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    log, _ = _mixed_log(tmp_path)
    exchanges, illegal = _groq_logs(tmp_path)
    view = _report(qtbot, log)
    view.selected_label = lambda: "m/x_bold"  # type: ignore[method-assign]
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    with qtbot.waitSignal(view.finished, timeout=10000):
        view.delete_button.click()
    assert [json.loads(x)["n"] for x in _lines(exchanges)] == [1, 3, 4]
    assert "not json" in _lines(illegal) and "wymiany z API 1" in view.status.text()


def test_report_delete_button_needs_a_selection(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view = _report(qtbot, tmp_path / "missing.jsonl")  # no log: no rows
    assert view.table.rowCount() == 0 and not view.delete_button.isEnabled()
    assert view.selected_label() is None


# ------------------------------------------------------------------ core: memory files


def _memories(folder: Path) -> None:
    (folder / "memory_m_x.txt").write_text("rule one\nrule two", encoding="utf-8")
    (folder / "memory_m_x_bold.txt").write_text("", encoding="utf-8")
    (folder / "memory_.txt").write_text("not a bot", encoding="utf-8")
    (folder / "notes.txt").write_text("keep me", encoding="utf-8")
    (folder / "groq_exchanges.jsonl").write_text("{}\n", encoding="utf-8")


def test_memory_files_are_listed_and_deleted_only_inside_the_memory_dir(tmp_path: Path) -> None:
    _memories(tmp_path)
    files = list_memory_files(tmp_path)
    assert [f.name for f in files] == ["memory_m_x.txt", "memory_m_x_bold.txt"]
    assert [f.bot for f in files] == ["m_x", "m_x_bold"] and files[0].preview.endswith("rule two")
    assert list_memory_files(tmp_path / "missing") == []

    elsewhere = tmp_path / "sub"
    elsewhere.mkdir()
    (elsewhere / "memory_z.txt").write_text("x", encoding="utf-8")
    assert not delete_memory_file(elsewhere / "memory_z.txt", tmp_path)  # another folder
    assert not delete_memory_file(tmp_path / "notes.txt", tmp_path)  # not a memory file
    assert not delete_memory_file(tmp_path / "memory_.txt", tmp_path)
    assert not delete_memory_file(tmp_path / "memory_gone.txt", tmp_path)
    assert not delete_memory_file(tmp_path / ".." / "memory_m_x.txt", tmp_path)
    assert delete_memory_file(tmp_path / "memory_m_x.txt", tmp_path)
    assert [f.name for f in list_memory_files(tmp_path)] == ["memory_m_x_bold.txt"]
    assert (tmp_path / "notes.txt").exists() and (tmp_path / "memory_.txt").exists()


# ------------------------------------------------------------------ lobby dialog


def test_memory_dialog_deletes_the_chosen_files_after_confirmation(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _memories(tmp_path)
    dialog = MemoryDialog(tmp_path)
    qtbot.addWidget(dialog)
    assert dialog.listing.count() == 2 and not dialog.delete_button.isEnabled()

    dialog.listing.item(0).setSelected(True)
    assert dialog.delete_button.isEnabled() and "rule two" in dialog.preview.toPlainText()

    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    asked: list[str] = []

    def question(parent, title, text, *args):  # type: ignore[no-untyped-def]
        asked.append(text)
        return answers.pop(0)

    monkeypatch.setattr(QMessageBox, "question", question)
    dialog.delete_button.click()  # "No"
    assert (tmp_path / "memory_m_x.txt").exists() and dialog.listing.count() == 2
    assert "memory_m_x.txt" in asked[0]

    dialog.delete_button.click()  # "Yes"
    assert not (tmp_path / "memory_m_x.txt").exists() and (tmp_path / "memory_m_x_bold.txt").exists()
    assert dialog.listing.count() == 1 and "Usunięto: 1" in dialog.status.text()

    dialog.listing.selectAll()  # several at once
    answers.append(QMessageBox.StandardButton.Yes)
    dialog.delete_button.click()
    assert dialog.listing.count() == 0 and not (tmp_path / "memory_m_x_bold.txt").exists()
    assert (tmp_path / "notes.txt").exists()


def test_lobby_opens_the_memory_dialog_and_has_no_log_caption(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    opened: list[Path] = []
    monkeypatch.setattr(MemoryDialog, "exec", lambda self: opened.append(self.directory) or 0)
    lobby = LobbyView(memory_dir=tmp_path)
    qtbot.addWidget(lobby)
    assert not hasattr(lobby, "log_note")
    texts = [label.text() for label in lobby.findChildren(type(lobby.message))]
    assert not any("zapisywane" in t for t in texts)
    lobby.memory_button.click()
    assert opened == [tmp_path]


def test_game_view_has_no_memory_deletion(qtbot) -> None:  # type: ignore[no-untyped-def]
    from gui.qt.game_view import GameView

    assert not hasattr(GameView, "open_memory_dialog")


# ------------------------------------------------------------------ MC caption


def test_mc_caption_is_shown_for_smart_seats_only(qtbot) -> None:  # type: ignore[no-untyped-def]
    row = SeatRow(1, SeatKind.SMART)
    qtbot.addWidget(row)
    row.show()
    assert row.samples_hint.isVisible()
    assert "więcej" in row.samples_hint.text() and "dokładniej" in row.samples_hint.text()
    row.kind.setCurrentIndex(row.kind.findData(SeatKind.HUMAN))
    assert not row.samples_hint.isVisible() and not row.samples.isVisible()


def test_deleting_a_bot_also_clears_its_api_error_log(tmp_path: Path) -> None:
    api = tmp_path / "groq_api_errors.jsonl"
    rows = [{"model": "m/x", "name": "", "n": 1}, {"model": "m/x", "name": "bold", "n": 2}, {"model": "m/y", "n": 3}]
    api.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    gone = delete_bot_records("m/x_bold", tmp_path / "none.jsonl", None, None, api)
    assert (gone.api_errors, gone.total) == (1, 1)
    assert [json.loads(x)["n"] for x in _lines(api)] == [1, 3]


def test_report_deletion_reaches_the_api_error_log(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    log, _ = _mixed_log(tmp_path)
    api = tmp_path / "groq_api_errors.jsonl"
    api.write_text(json.dumps({"model": "m/x", "name": "bold"}) + "\n" + json.dumps({"model": "m/x"}) + "\n", encoding="utf-8")
    view = _report(qtbot, log)
    view.selected_label = lambda: "m/x_bold"  # type: ignore[method-assign]
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    with qtbot.waitSignal(view.finished, timeout=10000):
        view.delete_button.click()
    assert _lines(api) == [json.dumps({"model": "m/x"})] and "błędy API 1" in view.status.text()
