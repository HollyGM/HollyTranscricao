"""Backend portátil de transcrição em CPU com Faster-Whisper."""

from __future__ import annotations

import gc
import logging
import os
from collections.abc import Callable
from typing import Any

from hollytranscricao.backend.mlx_transcriber import (
    _audio_duration,
    apply_pyannote_diarization,
    format_segments,
)

logger = logging.getLogger(__name__)


def _word_dict(word: Any, segment_start: float, segment_end: float) -> dict[str, Any]:
    start = word.start if word.start is not None else segment_start
    end = word.end if word.end is not None else segment_end
    return {
        "start": float(start),
        "end": float(end),
        "word": str(word.word or ""),
        "probability": float(word.probability or 0.0),
    }


def transcribe_audio(
    audio_path: str,
    model_size: str = "base",
    hf_token: str | None = None,
    initial_prompt: str | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    progress_callback: Callable[[str], None] | None = None,
    eta_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Transcreve em CPU e aplica diarização Pyannote quando solicitada."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "Faster-Whisper não está instalado. Reinstale as dependências do aplicativo."
        ) from exc

    if progress_callback:
        progress_callback(f"CPU: carregando modelo '{model_size}'...")

    cpu_threads = max(1, min(8, os.cpu_count() or 1))
    model = WhisperModel(
        model_size,
        device="cpu",
        compute_type="int8",
        cpu_threads=cpu_threads,
    )

    if progress_callback:
        progress_callback("CPU: transcrevendo com detecção automática de silêncio...")

    segment_iterator, info = model.transcribe(
        audio_path,
        language="pt",
        task="transcribe",
        initial_prompt=initial_prompt or None,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"threshold": 0.5, "min_silence_duration_ms": 500},
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
        compression_ratio_threshold=2.4,
        temperature=[0.0, 0.2, 0.4],
    )

    raw_segments = []
    for segment in segment_iterator:
        start = float(segment.start)
        end = float(segment.end)
        raw_segments.append(
            {
                "start": start,
                "end": end,
                "text": segment.text,
                "avg_logprob": segment.avg_logprob,
                "words": [_word_dict(word, start, end) for word in (segment.words or [])],
            }
        )

    del model
    gc.collect()

    diarized = False
    diarization_error: str | None = None
    if hf_token and hf_token.strip() and raw_segments:
        try:
            raw_segments = apply_pyannote_diarization(
                audio_path=audio_path,
                segments=raw_segments,
                hf_token=hf_token.strip(),
                min_speakers=min_speakers,
                max_speakers=max_speakers,
                progress_callback=progress_callback,
                eta_callback=eta_callback,
            )
            diarized = True
        except (ImportError, RuntimeError, OSError, ValueError) as exc:
            diarization_error = str(exc)
            logger.warning("Falha na diarização: %s", exc)
            if progress_callback:
                progress_callback(
                    "Aviso: a separação de interlocutores falhou; "
                    "a transcrição será mantida com locutor único."
                )

    duration = float(getattr(info, "duration", 0.0) or _audio_duration(audio_path))
    return {
        "duration": duration,
        "segments": format_segments(raw_segments, diarized=diarized),
        "diarized": diarized,
        "error_diarization": diarization_error,
        "backend": "faster-whisper",
        "model": model_size,
        "language": getattr(info, "language", "pt"),
    }
