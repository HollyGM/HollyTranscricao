import errno
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from hollytranscricao.backend import exporters
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


@pytest.mark.parametrize("without_hardlinks", [False, True])
def test_concurrent_exports_preserve_both_results_for_every_format(
    tmp_path, monkeypatch, without_hardlinks
):
    barrier = Barrier(2)
    real_publish = exporters._publish_exclusive
    original_names = {"shared_transcricao.md", "shared.srt", "shared_transcricao.txt"}

    def simultaneous_publish(temp_name, path):
        # Both writers select the original name before either can publish it.
        # Retries use a numbered name and must not wait on the barrier again.
        if path.name in original_names:
            barrier.wait(timeout=5)
        real_publish(temp_name, path)

    monkeypatch.setattr(exporters, "_publish_exclusive", simultaneous_publish)
    if without_hardlinks:
        def unsupported_link(source, destination):
            raise OSError(errno.EOPNOTSUPP, "hardlinks unavailable")

        monkeypatch.setattr(exporters.os, "link", unsupported_link)

    def export(text):
        return write_outputs(
            str(tmp_path),
            "shared",
            md_content=text,
            segments=[{"start": 0.0, "end": 1.0, "speaker": "Locutor", "text": text}],
            write_md=True,
            write_srt=True,
            write_txt=True,
            diarized=False,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(export, ["primeira gravação", "segunda gravação"]))

    for kind in ("md", "srt", "txt"):
        assert first[kind] != second[kind]
        assert "primeira gravação" in Path(first[kind]).read_text(encoding="utf-8")
        assert "segunda gravação" in Path(second[kind]).read_text(encoding="utf-8")
    assert len(list(tmp_path.iterdir())) == 6
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("link_error", [errno.EXDEV, errno.EOPNOTSUPP])
def test_filesystem_without_hardlinks_uses_exclusive_atomic_rename(
    tmp_path, monkeypatch, link_error
):
    def unsupported_link(source, destination):
        raise OSError(link_error, "hardlinks unavailable")

    monkeypatch.setattr(exporters.os, "link", unsupported_link)
    source = tmp_path / "complete.tmp"
    source.write_text("new complete result", encoding="utf-8")
    existing = tmp_path / "result.md"
    existing.write_text("previous result", encoding="utf-8")

    with pytest.raises(FileExistsError):
        exporters._publish_exclusive(str(source), existing)
    assert existing.read_text(encoding="utf-8") == "previous result"
    assert source.read_text(encoding="utf-8") == "new complete result"

    published = exporters._atomic_write(existing, "new complete result")

    assert published != existing
    assert published.read_text(encoding="utf-8") == "new complete result"
    assert existing.read_text(encoding="utf-8") == "previous result"
    assert not list(tmp_path.glob(".*.tmp"))


def test_failed_publication_removes_temporary_file_and_preserves_previous_result(
    tmp_path, monkeypatch
):
    existing = tmp_path / "result.md"
    existing.write_text("previous result", encoding="utf-8")

    def failed_publish(source, destination):
        raise OSError(errno.ENOSPC, "destination full")

    monkeypatch.setattr(exporters, "_publish_exclusive", failed_publish)

    with pytest.raises(OSError, match="destination full"):
        exporters._atomic_write(existing, "new result")

    assert existing.read_text(encoding="utf-8") == "previous result"
    assert list(tmp_path.iterdir()) == [existing]


def test_dangling_symlink_is_preserved_as_an_existing_output_path(tmp_path):
    reserved = tmp_path / "shared_transcricao.md"
    try:
        reserved.symlink_to(tmp_path / "missing.md")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    result = write_outputs(str(tmp_path), "shared", md_content="new result", segments=[])

    assert reserved.is_symlink()
    assert result["md"] != str(reserved)
    assert Path(result["md"]).read_text(encoding="utf-8") == "new result"
