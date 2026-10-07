import builtins
import platform
from unittest.mock import Mock

from hollytranscricao import main as main_module


def test_apple_silicon_startup_does_not_initialize_native_engines(monkeypatch):
    """Falhas de GPU devem ficar limitadas ao processo do motor de transcrição."""
    monkeypatch.setattr(main_module.sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"mlx", "mlx_whisper", "faster_whisper", "torch"}:
            raise AssertionError(f"Motor nativo inicializado no startup: {name}")
        return original_import(name, *args, **kwargs)

    app = Mock()
    app.exec.return_value = 0
    window = Mock()
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(main_module, "QApplication", lambda args: app)
    monkeypatch.setattr(main_module, "QIcon", lambda path: Mock())
    monkeypatch.setattr(main_module, "MainWindow", lambda: window)
    monkeypatch.setattr(main_module, "load_stylesheet", lambda current_app: None)

    assert main_module.main() == 0
    window.show.assert_called_once_with()
    app.exec.assert_called_once_with()
