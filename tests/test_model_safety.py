import signal

from hollytranscricao.backend.mlx_transcriber import (
    MLX_MODEL_MAP,
    MLX_MODEL_REVISIONS,
    _resolve_repo,
)
from hollytranscricao.gui.worker import TranscriptionWorker


def test_only_curated_models_are_exposed_by_mlx_backend():
    assert list(MLX_MODEL_MAP) == ["large-v3-turbo", "large-v2"]
    assert set(MLX_MODEL_REVISIONS) == set(MLX_MODEL_MAP)
    assert all(len(revision) == 40 for revision in MLX_MODEL_REVISIONS.values())
    assert _resolve_repo("unknown") == MLX_MODEL_MAP["large-v3-turbo"]


def test_native_crash_message_keeps_recovery_actionable():
    native_signal = getattr(signal, "SIGBUS", signal.SIGTERM)
    message = TranscriptionWorker._native_failure_message(-native_signal)

    assert signal.Signals(native_signal).name in message
    assert "permaneceu aberto" in message
    assert "Large V3 Turbo" in message
