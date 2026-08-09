from hollytranscricao.version import APP_NAME, APP_SLUG, __version__


def test_public_and_technical_names_are_stable():
    assert APP_NAME == "HollyTranscrição"
    assert APP_SLUG == "HollyTranscricao"
    assert __version__ == "2.0.0"
