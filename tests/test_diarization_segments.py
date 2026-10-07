from copy import deepcopy

import pytest

from hollytranscricao.backend.exporters import render_srt
from hollytranscricao.backend.mlx_transcriber import format_segments


def _exchange():
    return {
        "start": 0.0,
        "end": 5.0,
        "text": "A pergunta? Sim, a resposta.",
        "speaker": "SPEAKER_00",
        "words": [
            {"word": " A", "start": 0.1, "end": 0.3, "speaker": "SPEAKER_00"},
            {"word": " pergunta?", "start": 0.3, "end": 2.0, "speaker": "SPEAKER_00"},
            {"word": " Sim,", "start": 2.1, "end": 2.5, "speaker": "SPEAKER_01"},
            {"word": " a", "start": 2.5, "end": 2.7, "speaker": "SPEAKER_01"},
            {"word": " resposta.", "start": 2.7, "end": 4.9, "speaker": "SPEAKER_01"},
        ],
    }


def test_speaker_change_inside_whisper_segment_survives_export():
    original = _exchange()
    before = deepcopy(original)

    formatted = format_segments([original], diarized=True)

    assert [(part["speaker"], part["text"]) for part in formatted] == [
        ("Interlocutor 1", "A pergunta?"),
        ("Interlocutor 2", "Sim, a resposta."),
    ]
    assert [(part["start"], part["end"]) for part in formatted] == [(0.1, 2.0), (2.1, 4.9)]
    assert [word for part in formatted for word in part["words"]] == original["words"]
    assert " ".join(part["text"] for part in formatted) == original["text"]
    assert original == before
    subtitles = render_srt(formatted)
    assert "00:00:00,100 --> 00:00:02,000\n[Interlocutor 1] A pergunta?" in subtitles
    assert "00:00:02,100 --> 00:00:04,900\n[Interlocutor 2] Sim, a resposta." in subtitles


def test_word_labels_do_not_split_without_diarization():
    original = _exchange()

    formatted = format_segments([original], diarized=False)

    assert len(formatted) == 1
    assert formatted[0]["text"] == original["text"]
    assert (formatted[0]["start"], formatted[0]["end"]) == (0.0, 5.0)


def test_words_without_speaker_inherit_segment_label():
    original = _exchange()
    del original["words"][1]["speaker"]

    formatted = format_segments([original], diarized=True)

    assert [part["text"] for part in formatted] == ["A pergunta?", "Sim, a resposta."]
    assert [part["speaker"] for part in formatted] == ["Interlocutor 1", "Interlocutor 2"]


@pytest.mark.parametrize(
    "incomplete", ["missing_time", "invalid_time", "missing_text", "different_text"]
)
def test_incomplete_word_alignment_preserves_all_original_text_and_times(incomplete):
    original = _exchange()
    if incomplete == "missing_time":
        del original["words"][2]["start"]
    elif incomplete == "invalid_time":
        original["words"][2]["end"] = float("nan")
    elif incomplete == "missing_text":
        del original["words"][2]["word"]
    else:
        original["words"][2]["word"] = " Não,"

    formatted = format_segments([original], diarized=True)

    assert len(formatted) == 1
    assert formatted[0]["text"] == original["text"]
    assert (formatted[0]["start"], formatted[0]["end"]) == (0.0, 5.0)
    assert formatted[0]["words"] == original["words"]


def test_complete_uniform_word_label_corrects_segment_label_without_changing_times():
    original = _exchange()
    for word in original["words"]:
        word["speaker"] = "SPEAKER_01"

    formatted = format_segments([original], diarized=True)

    assert len(formatted) == 1
    assert formatted[0]["speaker"] == "Interlocutor 2"
    assert formatted[0]["text"] == original["text"]
    assert (formatted[0]["start"], formatted[0]["end"]) == (0.0, 5.0)


def test_segment_without_words_preserves_its_existing_label():
    original = _exchange()
    del original["words"]

    formatted = format_segments([original], diarized=True)

    assert len(formatted) == 1
    assert formatted[0]["speaker"] == "Interlocutor 1"
    assert formatted[0]["text"] == original["text"]
