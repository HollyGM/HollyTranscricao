import builtins
import platform
from pathlib import Path
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


def test_self_test_transcribes_without_opening_the_window(monkeypatch, tmp_path, capsys):
    from hollytranscricao.backend import orchestrator

    def fake_pipeline(**kwargs):
        out = Path(kwargs["output_md_dir"])
        paths = {fmt: str(out / f"r.{fmt}") for fmt in ("md", "srt", "txt")}
        for path in paths.values():
            Path(path).write_text("O juiz abriu a sessão.", encoding="utf-8")
        assert kwargs["apply_noise_reduction"] is True
        return paths

    monkeypatch.setattr(orchestrator, "run_transcription_pipeline", fake_pipeline)
    window_opened = Mock(side_effect=AssertionError("abriu a janela"))
    monkeypatch.setattr(main_module, "QApplication", window_opened)
    argv = ["HollyTranscricao", "--autoteste", str(tmp_path / "a.m4a")]
    monkeypatch.setattr(main_module.sys, "argv", argv)

    assert main_module.main() == 0
    assert "AUTOTESTE OK" in capsys.readouterr().out


def test_self_test_reports_failure(monkeypatch, tmp_path, capsys):
    from hollytranscricao.backend import orchestrator

    failing = Mock(side_effect=RuntimeError("FFmpeg ausente"))
    monkeypatch.setattr(orchestrator, "run_transcription_pipeline", failing)
    argv = ["HollyTranscricao", "--autoteste", str(tmp_path / "a.m4a")]
    monkeypatch.setattr(main_module.sys, "argv", argv)

    assert main_module.main() == 1
    assert "AUTOTESTE FALHOU: FFmpeg ausente" in capsys.readouterr().out
