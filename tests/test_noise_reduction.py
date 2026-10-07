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
