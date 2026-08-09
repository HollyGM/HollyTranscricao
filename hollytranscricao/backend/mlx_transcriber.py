"""Backend de transcrição via MLX-Whisper rodando 100% na GPU do Apple Silicon.

Use este módulo quando o objetivo for máxima velocidade em Apple Silicon.
Para diarização (separação de vozes) o pipeline ainda recorre ao Pyannote via
Pyannote, pois o MLX-Whisper foca somente em transcrição.
"""

from __future__ import annotations

import bisect
import gc
import logging
import os
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Dois perfis deliberadamente simples. O Turbo é a opção segura para uso
# geral; o V2 integral permite comparar gravações difíceis com outro treinamento.
MLX_MODEL_MAP = {
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v2": "mlx-community/whisper-large-v2-mlx",
}
MLX_MODEL_REVISIONS = {
    "large-v3-turbo": "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb",
    "large-v2": "cce86229e2765266197fef869ce9f7e2550067ab",
}


def _resolve_repo(model_size: str) -> str:
    return MLX_MODEL_MAP.get(model_size, MLX_MODEL_MAP["large-v3-turbo"])


def prepare_mlx_model(
    model_size: str,
    hf_token: str | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> str:
    """Garante que o modelo esteja completo antes de iniciar a estimativa.

    O ``mlx_whisper.transcribe`` baixa pesos implicitamente. Em uma primeira
    execução isso fazia a barra esgotar e exibir "Finalizando" durante minutos.
    Antecipar o download mantém a barra indeterminada até o modelo estar pronto.
    """
    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError
    except ImportError as exc:
        raise RuntimeError("huggingface-hub não está instalado no aplicativo.") from exc

    repo = _resolve_repo(model_size)
    revision = MLX_MODEL_REVISIONS.get(
        model_size, MLX_MODEL_REVISIONS["large-v3-turbo"]
    )
    token = hf_token.strip() if hf_token and hf_token.strip() else None

    try:
        local_path = snapshot_download(
            repo_id=repo,
            revision=revision,
            token=token,
            local_files_only=True,
        )
        if progress_callback:
            progress_callback(f"MLX: Modelo '{model_size}' já está disponível neste Mac.")
        return str(local_path)
    except LocalEntryNotFoundError:
        pass

    if progress_callback:
        approximate_size = "3,1 GB" if model_size == "large-v2" else "1,6 GB"
        progress_callback(
            f"MLX: Baixando o modelo '{model_size}' pela primeira vez "
            f"(aprox. {approximate_size}). A barra permanecerá animada durante o download..."
        )

    local_path = snapshot_download(repo_id=repo, revision=revision, token=token)
    if progress_callback:
        progress_callback(f"MLX: Download de '{model_size}' concluído e verificado.")
    return str(local_path)


def transcribe_audio_mlx(
    audio_path: str,
    model_size: str = "large-v3-turbo",
    initial_prompt: str | None = None,
    hf_token: str | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    progress_callback: Callable[[str], None] | None = None,
    eta_callback: Callable[[float, str], None] | None = None,
    model_path: str | None = None,
) -> dict[str, Any]:
    """Transcreve áudio com MLX-Whisper e, opcionalmente, aplica diarização Pyannote.

    Retorna o mesmo formato de dicionário que ``transcriber.transcribe_audio``
    para que o orchestrator possa intercambiar os backends sem alterações.
    """
    try:
        import mlx_whisper
    except ImportError as exc:
        raise RuntimeError(
            "mlx-whisper não está instalado. Instale com: pip install mlx-whisper"
        ) from exc

    repo = model_path or _resolve_repo(model_size)

    if progress_callback:
        progress_callback(f"MLX: Carregando modelo '{model_size}' na GPU do Apple Silicon...")

    decode_options: dict[str, Any] = {
        "language": "pt",
        "task": "transcribe",
        "word_timestamps": True,
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.6,
        "compression_ratio_threshold": 2.4,
        "temperature": (0.0, 0.2, 0.4),
        # Descarta texto "inventado" pelo Whisper em trechos de silêncio longo
        # (requer word_timestamps=True). Essencial para fidelidade em audiências.
        "hallucination_silence_threshold": 2.0,
    }
    if initial_prompt:
        decode_options["initial_prompt"] = initial_prompt

    if progress_callback:
        progress_callback("MLX: Transcrevendo áudio na GPU (Metal Performance Shaders)...")

    raw = mlx_whisper.transcribe(
        audio_path,
        path_or_hf_repo=repo,
        **decode_options,
    )

    # Libera a memória da GPU (Unified Memory) que o MLX usou
    # para que o PyTorch (MPS) consiga rodar o Pyannote sem dar Out of Memory.
    try:
        import mlx.core as mx

        if hasattr(mx, "clear_cache"):  # MLX >= 0.22
            mx.clear_cache()
        else:  # MLX antigo
            mx.metal.clear_cache()
    except (ImportError, RuntimeError, AttributeError) as exc:
        logger.debug("Não foi possível limpar o cache do MLX: %s", exc)

    duration = float(raw.get("duration") or _audio_duration(audio_path))
    segments_raw: list[dict[str, Any]] = list(raw.get("segments", []))

    diarized = False
    error_diarization: str | None = None

    if hf_token and hf_token.strip() and segments_raw:
        try:
            segments_raw = apply_pyannote_diarization(
                audio_path=audio_path,
                segments=segments_raw,
                hf_token=hf_token.strip(),
                min_speakers=min_speakers,
                max_speakers=max_speakers,
                progress_callback=progress_callback,
                eta_callback=eta_callback,
            )
            diarized = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falha na diarização Pyannote sobre saída MLX: %s", exc)
            error_diarization = str(exc)
            if progress_callback:
                progress_callback(
                    f"Aviso: diarização falhou ({str(exc)[:80]}). Mantendo locutor único."
                )

    formatted = format_segments(segments_raw, diarized=diarized)

    gc.collect()

    return {
        "duration": duration,
        "segments": formatted,
        "diarized": diarized,
        "error_diarization": error_diarization,
        "backend": "mlx",
        "model": model_size,
    }


def _audio_duration(path: str) -> float:
    try:
        import soundfile as sf

        with sf.SoundFile(path) as f:
            return len(f) / float(f.samplerate)
    except Exception:  # noqa: BLE001
        return 0.0


def apply_pyannote_diarization(
    audio_path: str,
    segments: list[dict[str, Any]],
    hf_token: str,
    min_speakers: int | None,
    max_speakers: int | None,
    progress_callback: Callable[[str], None] | None,
    eta_callback: Callable[[float, str], None] | None = None,
) -> list[dict[str, Any]]:
    """Aplica Pyannote para atribuir locutor a cada segmento já transcrito."""
    os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")

    import inspect

    import torch
    from pyannote.audio import Pipeline

    # Usar GPU se disponível para evitar que o Pyannote demore horas
    device_name = "mps" if torch.backends.mps.is_available() else "cpu"

    if progress_callback:
        progress_callback(f"Pyannote: Identificando interlocutores ({device_name.upper()})...")

    if eta_callback:
        duration = _audio_duration(audio_path)
        # Fatores MEDIDOS no MacBook Air M5 sobre 103 s de áudio:
        #   MPS, limites automáticos      → 6,1x realtime (16,9 s)
        #   MPS, max_speakers definido    → 2,1x realtime (48,3 s)
        # Um teto alto de locutores explode o custo do agrupamento; o valor
        # antigo (10x fixo) errava por quase 5x e deixava a barra travada em 98%.
        if device_name != "mps":
            factor = 1.0
        elif max_speakers and int(max_speakers) > 4:
            factor = 2.0
        else:
            factor = 5.5
        eta_callback(max(5.0, duration / factor), f"Pyannote ({device_name.upper()})")

    # pyannote.audio 4.x usa `token`; versões 3.x usavam `use_auth_token`. Detectar e adaptar.
    try:
        params = inspect.signature(Pipeline.from_pretrained).parameters
    except (TypeError, ValueError):
        params = {}
    auth_kwarg = "token" if "token" in params else "use_auth_token"

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        **{auth_kwarg: hf_token},
    )
    pipeline.to(torch.device(device_name))

    diarize_kwargs: dict[str, Any] = {}
    if min_speakers:
        diarize_kwargs["min_speakers"] = int(min_speakers)
    if max_speakers:
        diarize_kwargs["max_speakers"] = int(max_speakers)

    # Pyannote 4.x usa torchcodec para decodificar áudio quando recebe um path.
    # No macOS frequentemente o torchcodec falha por ausência das libs nativas do
    # FFmpeg no rpath. Solução oficial recomendada no warning do pyannote:
    # carregar o waveform em memória com soundfile e passar como dict.
    import soundfile as sf

    waveform, sample_rate = sf.read(audio_path, dtype="float32", always_2d=False)
    if waveform.ndim == 1:
        # (samples,) → (1, samples) para o formato esperado pelo pyannote (channels, time)
        tensor = torch.from_numpy(waveform).unsqueeze(0)
    else:
        # soundfile devolve (samples, channels); pyannote espera (channels, samples)
        tensor = torch.from_numpy(waveform.T)

    audio_input = {"waveform": tensor, "sample_rate": int(sample_rate)}
    try:
        diarization = pipeline(audio_input, **diarize_kwargs)
    except Exception as e:
        if "out of memory" in str(e).lower() and device_name == "mps":
            if progress_callback:
                progress_callback(
                    "Aviso: memória de vídeo esgotada. Tentando Pyannote na CPU; "
                    "esta etapa será mais lenta."
                )
            if eta_callback:
                duration = _audio_duration(audio_path)
                eta_callback(max(5.0, duration / 1.0), "Pyannote (CPU Fallback)")

            # Limpa VRAM do PyTorch e joga o modelo para CPU
            torch.mps.empty_cache()
            pipeline.to(torch.device("cpu"))
            diarization = pipeline(audio_input, **diarize_kwargs)
        else:
            raise e

    # pyannote 4.x retorna DiarizeOutput (com .exclusive_speaker_diarization,
    # ideal para transcrição porque não tem sobreposição de turnos);
    # pyannote 3.x retornava direto um Annotation.
    annotation = getattr(diarization, "exclusive_speaker_diarization", None)
    if annotation is None:
        annotation = getattr(diarization, "speaker_diarization", diarization)

    turns: list[tuple] = sorted(
        (turn.start, turn.end, speaker)
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    )
    turn_starts = [t[0] for t in turns]
    # Fim máximo acumulado à esquerda: permite parar a varredura para trás assim
    # que nenhum turno anterior possa mais alcançar o início do segmento.
    max_end_prefix: list[float] = []
    running = 0.0
    for _, t_end, _ in turns:
        running = max(running, t_end)
        max_end_prefix.append(running)

    def speaker_for(start: float, end: float) -> str | None:
        """Retorna o locutor com maior sobreposição temporal com o intervalo.

        Varre apenas a vizinhança do intervalo em vez da lista inteira: numa
        audiência de 3 h são ~40 mil palavras contra ~2 mil turnos, e a busca
        linear original custava dezenas de milhões de iterações em Python puro.
        """
        best: str | None = None
        best_overlap = 0.0
        mid_hit: str | None = None
        mid = (start + end) / 2.0

        # Primeiro turno que começa depois do fim do segmento: nada dali pra
        # frente pode sobrepor.
        hi = bisect.bisect_left(turn_starts, end)
        for i in range(hi - 1, -1, -1):
            t_start, t_end, spk = turns[i]
            if max_end_prefix[i] <= start:
                break  # nenhum turno anterior alcança este segmento
            overlap = min(end, t_end) - max(start, t_start)
            # ">=" e não ">": a varredura vai do fim para o começo, então
            # deixar o empate ser sobrescrito faz vencer o turno mais antigo —
            # o mesmo desempate da busca linear que este trecho substituiu.
            if overlap > 0.0 and overlap >= best_overlap:
                best_overlap = overlap
                best = spk
            if mid_hit is None and t_start <= mid <= t_end:
                mid_hit = spk

        return best if best_overlap > 0.0 else mid_hit

    for seg in segments:
        spk = speaker_for(float(seg.get("start", 0.0)), float(seg.get("end", 0.0)))
        if spk is not None:
            seg["speaker"] = spk

        # Também propaga para palavras se existirem
        for word in seg.get("words", []) or []:
            w_spk = speaker_for(
                float(word.get("start", seg.get("start", 0.0))),
                float(word.get("end", seg.get("end", 0.0))),
            )
            if w_spk is not None:
                word["speaker"] = w_spk

    del pipeline
    gc.collect()
    return segments


def format_segments(segments: list[dict[str, Any]], diarized: bool) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue

        speaker_raw = seg.get("speaker")
        if speaker_raw:
            try:
                speaker_id = int(str(speaker_raw).split("_")[-1]) + 1
                speaker_name = f"Interlocutor {speaker_id}"
            except (ValueError, IndexError):
                speaker_name = str(speaker_raw)
        else:
            speaker_name = "Locutor"

        words = seg.get("words") or []
        # avg_logprob → confiança média (0..1)
        avg_logprob = seg.get("avg_logprob")
        confidence = None
        if isinstance(avg_logprob, (int, float)):
            import math

            confidence = max(0.0, min(1.0, math.exp(float(avg_logprob))))

        formatted.append(
            {
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
                "speaker": speaker_name,
                "speaker_raw": speaker_raw,
                "text": text,
                "words": words,
                "confidence": confidence,
            }
        )

    return formatted
