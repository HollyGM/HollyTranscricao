from pathlib import Path

from hollytranscricao.backend.exporters import (
    render_markdown,
    render_srt,
    write_outputs,
)


def _segments():
    return [
        {"start": 0.0, "end": 1.2, "speaker": "Locutor", "text": "Olá."},
        {"start": 1.2, "end": 2.0, "speaker": "Locutor", "text": ""},
        {"start": 2.0, "end": 3.4, "speaker": "Locutor", "text": "Tudo bem?"},
    ]


def test_srt_numbering_has_no_gaps():
    rendered = render_srt(_segments())
    assert "\n2\n00:00:02,000" in rendered
    assert "\n3\n" not in rendered


def test_markdown_escapes_filename_and_table_cells():
    content = render_markdown(
        original_filename='audio"\nmalicioso.wav',
        result={
            "segments": [{"start": 0, "end": 1, "speaker": "Pessoa | A", "text": "Teste."}],
            "duration": 1,
            "diarized": True,
            "backend": "teste",
            "model": "teste",
        },
        metadata={"recording_type": "reuniao"},
    )
    assert 'arquivo: "audio\\"\\nmalicioso.wav"' in content
    assert "| Pessoa \\| A |" in content
    assert "tipo_gravacao: reuniao" in content


def test_outputs_are_atomic_portable_and_never_overwritten(tmp_path: Path):
    first = write_outputs(
        str(tmp_path),
        "CON: reunião?",
        md_content="# primeira",
        segments=_segments(),
        write_md=True,
        write_srt=True,
        write_txt=True,
        diarized=False,
    )
    second = write_outputs(
        str(tmp_path),
        "CON: reunião?",
        md_content="# segunda",
        segments=_segments(),
        write_md=True,
        write_srt=True,
        write_txt=True,
        diarized=False,
    )

    assert first["md"] != second["md"]
    assert Path(first["md"]).read_text(encoding="utf-8") == "# primeira"
    assert Path(second["md"]).read_text(encoding="utf-8") == "# segunda"
    assert ":" not in Path(first["md"]).name
    assert not list(tmp_path.glob(".*.tmp"))
