from pathlib import Path
from types import SimpleNamespace

import pytest

from hollytranscricao.backend import noise_reduction
from hollytranscricao.backend.exporters import render_markdown


@pytest.mark.parametrize("returncode, expected_applied", [(0, True), (1, False)])
def test_noise_reduction_metadata_matches_ffmpeg_result(
    tmp_path, monkeypatch, returncode, expected_applied
):
    original = tmp_path / "source.wav"
    original.write_bytes(b"original audio")
    monkeypatch.setattr(noise_reduction, "resolve_ffmpeg", lambda: "/test/ffmpeg")

    def fake_ffmpeg(command, **kwargs):
        assert "afftdn=nf=-25" in command
        if returncode == 0:
            Path(command[-1]).write_bytes(b"cleaned audio")
        return SimpleNamespace(returncode=returncode, stderr="test conversion failure")

    monkeypatch.setattr(noise_reduction.subprocess, "run", fake_ffmpeg)

    output, applied = noise_reduction.clean_audio(str(original), str(tmp_path), force_ffmpeg=True)

    assert applied is expected_applied
    assert Path(output).read_bytes() == (b"cleaned audio" if applied else b"original audio")
    assert original.read_bytes() == b"original audio"
    markdown = render_markdown(
        original_filename=original.name,
        result={"segments": [], "duration": 1},
        metadata={"noise_reduction": applied},
    )
    assert f"tratamento_ruido: {'sim' if expected_applied else 'nao'}" in markdown


def test_without_deepfilternet_torch_is_never_imported(tmp_path, monkeypatch):
    """Sem o complemento DeepFilterNet, a redução de ruído vai direto ao FFmpeg
    sem carregar o PyTorch (que custava cerca de 3 s e fica fora do app)."""
    import builtins

    original = tmp_path / "source.wav"
    original.write_bytes(b"original audio")
    monkeypatch.setattr(noise_reduction, "resolve_ffmpeg", lambda: "/test/ffmpeg")
    monkeypatch.setattr(noise_reduction, "deepfilternet_available", lambda: False)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "df"}:
            raise AssertionError(f"importou {name} sem necessidade")
        return real_import(name, *args, **kwargs)

    def fake_ffmpeg(command, **kwargs):
        assert "afftdn=nf=-25" in command
        Path(command[-1]).write_bytes(b"cleaned audio")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(noise_reduction.subprocess, "run", fake_ffmpeg)

    output, applied = noise_reduction.clean_audio(str(original), str(tmp_path))

    assert applied is True
    assert Path(output).read_bytes() == b"cleaned audio"


def test_progress_names_the_noise_reduction_actually_used(tmp_path, monkeypatch):
    from hollytranscricao.backend import orchestrator

    messages = []
    monkeypatch.setattr(orchestrator, "deepfilternet_available", lambda: False)
    wav = str(tmp_path / "a.wav")
    monkeypatch.setattr(orchestrator, "extract_and_convert_audio", lambda *a: wav)
    monkeypatch.setattr(orchestrator, "clean_audio", lambda *a: (wav, True))
    result = {"segments": [], "duration": 1}
    monkeypatch.setattr(orchestrator, "_run_backend", lambda **k: result)
    monkeypatch.setattr(orchestrator, "write_outputs", lambda **k: {})
    orchestrator.run_transcription_pipeline(
        input_file_path=str(tmp_path / "x.wav"),
        output_md_dir=str(tmp_path),
        apply_noise_reduction=True,
        write_md=False,
        progress_callback=messages.append,
        work_dir=str(tmp_path),
    )
    assert "Passo 2/3: Reduzindo ruído (FFmpeg)..." in messages
    assert not any("DeepFilterNet" in m for m in messages)
