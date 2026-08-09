from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel

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
