import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from hollytranscricao.gui import main_window
from hollytranscricao.gui.main_window import MainWindow
from hollytranscricao.version import APP_NAME, __version__


def test_window_identity_and_token_privacy(tmp_path):
    app = QApplication.instance() or QApplication([])
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))

    window = MainWindow()
    labels = {label.text() for label in window.findChildren(QLabel)}

    assert window.windowTitle() == f"{APP_NAME} {__version__}"
    assert any("HOLLYTRANSCRIÇÃO" in text for text in labels)
    assert not any("ADVOCACIA" in text for text in labels)

    window.hf_token_input.setText("hf_nao_deve_ser_salvo")
    window._save_settings()
    assert window.settings.value("hf_token") is None

    window.close()
    app.processEvents()


@pytest.fixture
def controlled_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_window, "QSettings", lambda *args: settings)
    for method in ("information", "warning", "critical"):
        monkeypatch.setattr(main_window.QMessageBox, method, Mock())

    workers = []

    class FakeWorker(QObject):
        progress_signal = Signal(str)
        finished_signal = Signal(dict)
        error_signal = Signal(str)
        cancelled_signal = Signal()
        eta_signal = Signal(float, str)

        def __init__(self, **options):
            super().__init__()
            self.options = options
            self.running = False
            workers.append(self)

        def start(self):
            self.running = True

        def isRunning(self):
            return self.running

    monkeypatch.setattr(main_window, "TranscriptionWorker", FakeWorker)
    window = MainWindow()
    window.output_dir_input.setText(str(tmp_path / "exports"))
    yield window, workers
    for worker in workers:
        worker.running = False
    window.close()
    app.processEvents()


@pytest.mark.parametrize("completion", ["finished", "error", "cancelled"])
def test_active_worker_rejects_new_file_and_second_start(
    controlled_window, tmp_path, monkeypatch, completion
):
    window, workers = controlled_window
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    first.touch()
    second.touch()
    select_file = Mock(return_value=(str(second), ""))
    monkeypatch.setattr(main_window.QFileDialog, "getOpenFileName", select_file)

    window.drop_zone.set_file(str(first))
    window._start_processing()
    active_worker = window.worker
    assert not window.drop_zone.isEnabled()
    assert not window.process_btn.isEnabled()

    QTest.mouseClick(window.drop_zone, Qt.MouseButton.LeftButton)
    window.drop_zone.set_file(str(second))
    window._on_file_selected(str(second))
    window._start_processing()

    select_file.assert_not_called()
    assert window.selected_file_path == str(first)
    assert not window.process_btn.isEnabled()
    assert window.worker is active_worker
    assert len(workers) == 1

    active_worker.running = False
    if completion == "finished":
        active_worker.finished_signal.emit({"md": str(tmp_path / "first.md")})
    elif completion == "error":
        active_worker.error_signal.emit("Falha simulada")
    else:
        active_worker.cancelled_signal.emit()

    assert window.drop_zone.isEnabled()
    assert window.drop_zone.acceptDrops()
    assert window.process_btn.isEnabled()
    assert not window.cancel_btn.isEnabled()
    window.drop_zone.set_file(str(second))
    window._start_processing()
    assert window.selected_file_path == str(second)
    assert len(workers) == 2


@pytest.mark.parametrize("home_prefix", [False, True])
def test_output_directory_is_normalized_before_worker_start(
    controlled_window, tmp_path, monkeypatch, home_prefix
):
    window, workers = controlled_window
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "input.wav"
    source.touch()
    expected = tmp_path / "exports"
    requested = f"~/{os.path.relpath(expected, Path.home())}" if home_prefix else "exports"
    window.output_dir_input.setText(requested)
    window.drop_zone.set_file(str(source))

    window._start_processing()

    assert expected.is_dir()
    assert window.output_dir_input.text() == str(expected)
    assert workers[0].options["output_md_dir"] == str(expected)


@pytest.mark.parametrize(
    ("formats", "selected", "label"),
    [
        (["srt", "md"], "md", "Abrir Markdown (.md)"),
        (["srt"], "srt", "Abrir legenda (.srt)"),
        (["txt"], "txt", "Abrir texto (.txt)"),
    ],
)
def test_open_button_identifies_and_opens_generated_format(
    controlled_window, tmp_path, monkeypatch, formats, selected, label
):
    window, _ = controlled_window
    paths = {kind: str(tmp_path / f"output.{kind}") for kind in formats}
    for path in paths.values():
        Path(path).touch()
    open_url = Mock(return_value=True)
    monkeypatch.setattr(main_window.QDesktopServices, "openUrl", open_url)

    window._on_worker_finished(paths)
    assert window.open_md_btn.isEnabled()
    assert window.open_md_btn.text() == label
    window._open_generated_md()
    assert Path(open_url.call_args.args[0].toLocalFile()) == Path(paths[selected])
