from hollytranscricao.backend.postprocess import correct_segments, correct_text


def test_specialized_rules_are_opt_in():
    generic, generic_report = correct_text("Eu com signo este documento.")
    specialized, specialized_report = correct_text("Eu com signo este documento.", specialized=True)

    assert generic == "Eu com signo este documento."
    assert generic_report == {}
    assert specialized == "Eu consigno este documento."
    assert specialized_report == {"com signo → consigno": 1}


def test_vocabulary_rules_are_general_and_auditable():
    segments = [{"text": "A re negociação começa amanhã."}]
    report = correct_segments(segments, vocabulary="renegociação")

    assert segments[0]["text"] == "A renegociação começa amanhã."
    assert report == {"re negociação → renegociação": 1}
