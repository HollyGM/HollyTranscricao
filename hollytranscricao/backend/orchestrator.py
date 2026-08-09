"""Pipeline completo de transcrição.

Etapas:
1. Extrair/converter áudio para WAV 16 kHz mono.
2. (Opcional) Reduzir ruído via DeepFilterNet ou FFmpeg.
3. Transcrever via backend escolhido (MLX-Whisper na GPU ou Faster-Whisper na CPU).
4. Aplicar correções determinísticas seguras e, em gravações jurídicas,
   regras especializadas auditáveis.
5. Exportar Markdown estruturado, SRT e TXT.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from typing import Any

from hollytranscricao.backend.audio_extractor import extract_and_convert_audio
from hollytranscricao.backend.exporters import render_markdown, write_outputs
from hollytranscricao.backend.noise_reduction import clean_audio
from hollytranscricao.backend.postprocess import correct_segments

logger = logging.getLogger(__name__)


def run_transcription_pipeline(
    input_file_path: str,
    output_md_dir: str,
    hf_token: str | None = None,
    whisper_model: str = "large-v3-turbo",
    initial_prompt: str | None = None,
    apply_noise_reduction: bool = False,
    backend: str = "mlx",
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    recording_type: str = "",
    write_md: bool = True,
    write_srt: bool = False,
    write_txt: bool = False,
    progress_callback: Callable[[str], None] | None = None,
    eta_callback: Callable[[float, str], None] | None = None,
) -> dict[str, str]:
    """Executa o pipeline completo. Retorna um dicionário com os caminhos gerados."""

    temp_dir = tempfile.mkdtemp(prefix="hollytranscricao_")

    try:
        # ── Passo 1: Extração / Conversão ──
        if progress_callback:
            progress_callback("Passo 1/3: Extraindo áudio em WAV 16 kHz mono...")
        logger.info("Extraindo áudio de: %s", input_file_path)
        audio_wav_path = extract_and_convert_audio(input_file_path, temp_dir)
        working_audio_path = audio_wav_path

        # ── Passo 2: Redução de ruído ──
        noise_reduction_applied = False
        if apply_noise_reduction:
            if progress_callback:
                progress_callback("Passo 2/3: Reduzindo ruído (DeepFilterNet/FFmpeg)...")
            cleaned_wav_path, noise_reduction_applied = clean_audio(audio_wav_path, temp_dir)
            working_audio_path = cleaned_wav_path
        else:
            if progress_callback:
                progress_callback("Passo 2/3: Redução de ruído desativada.")

        # ── Passo 3: Transcrição ──
        backend_label = "MLX-Whisper (GPU)" if backend == "mlx" else "Faster-Whisper (CPU)"
        if progress_callback:
            progress_callback(f"Passo 3/3: Transcrevendo com {backend_label}...")

        # Duração do áudio para estimar tempo (barato via soundfile)
        audio_duration = _probe_duration(working_audio_path)

        transcription_result = _run_backend(
            backend=backend,
            audio_path=working_audio_path,
            model_size=whisper_model,
            hf_token=hf_token,
            initial_prompt=initial_prompt,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            audio_duration=audio_duration,
            progress_callback=progress_callback,
            eta_callback=eta_callback,
        )

        # Correções do vocabulário são gerais. As regras jurídicas só rodam
        # quando o usuário classifica explicitamente a gravação nessa categoria.
        specialized_review = recording_type == "audiencia_oitiva"
        corrections = correct_segments(
            transcription_result.get("segments", []),
            vocabulary=initial_prompt or "",
            specialized=specialized_review,
        )
        transcription_result["corrections"] = corrections
        if corrections and progress_callback:
            total = sum(corrections.values())
            progress_callback(
                f"Revisão automática: {total} correção(ões) auditável(is) aplicada(s)."
            )

        # ── Geração de saída ──
        formats_requested = [
            name
            for name, on in [("Markdown", write_md), ("SRT", write_srt), ("TXT", write_txt)]
            if on
        ]
        if progress_callback:
            progress_callback(
                f"Gerando: {', '.join(formats_requested) or '(nenhum formato selecionado)'}..."
            )

        original_filename = os.path.basename(input_file_path)
        base_name = os.path.splitext(original_filename)[0]

        # Markdown só é renderizado quando solicitado (operação custosa em audiências longas)
        md_content = ""
        if write_md:
            md_content = render_markdown(
                original_filename=original_filename,
                result=transcription_result,
                metadata={
                    "noise_reduction": noise_reduction_applied,
                    "hf_token": bool(hf_token and hf_token.strip()),
                    "recording_type": recording_type or "nao_informado",
                },
            )

        paths = write_outputs(
            output_dir=output_md_dir,
            base_name=base_name,
            md_content=md_content,
            segments=transcription_result["segments"],
            write_md=write_md,
            write_srt=write_srt,
            write_txt=write_txt,
            diarized=bool(transcription_result.get("diarized")),
        )

        if progress_callback:
            files_list = "\n  - ".join(os.path.basename(p) for p in paths.values()) or "(nenhum)"
            progress_callback(f"Concluído. Arquivos gerados:\n  - {files_list}")

        logger.info("Pipeline finalizado: %s", paths)
        return paths

    except Exception as exc:
        logger.exception("Falha no pipeline.")
        if progress_callback:
            progress_callback(f"ERRO CRÍTICO: {exc}")
        raise
    finally:
        try:
            shutil.rmtree(temp_dir)
        except OSError as exc:
            logger.warning("Não removeu temp dir %s: %s", temp_dir, exc)


# Fatores medidos no MacBook Air M5 (10 núcleos, 16 GB), amostra de 103 s,
# large-v3-turbo com word_timestamps:
#   MLX-Whisper na GPU  → 10,6x realtime (9,8 s)
#   WhisperX na CPU     →  0,7x realtime (int8)
# O valor antigo (14x) prometia o dobro da velocidade real: a barra chegava a
# 98% e ficava parada lá pelo resto do processamento, o que dava a impressão
# de travamento. Preferir subestimar a velocidade a superestimar.
_FACTOR_MLX = 9.5
_FACTOR_CPU = 0.7

# Carregar os pesos na GPU e compilar os kernels Metal custa um tempo fixo que
# não depende da duração do áudio, e domina a estimativa em arquivos curtos.
_MLX_STARTUP_SECONDS = 9.0


def _probe_duration(audio_path: str) -> float:
    try:
        import soundfile as sf

        with sf.SoundFile(audio_path) as f:
            return len(f) / float(f.samplerate)
    except Exception:  # noqa: BLE001
        return 0.0


def _emit_eta(eta_callback, duration: float, factor: float, label: str, overhead: float = 0.0):
    if eta_callback and duration > 0:
        eta_callback(max(5.0, overhead + duration / factor), label)


def _run_backend(
    *,
    backend: str,
    audio_path: str,
    model_size: str,
    hf_token: str | None,
    initial_prompt: str | None,
    min_speakers: int | None,
    max_speakers: int | None,
    audio_duration: float = 0.0,
    progress_callback: Callable[[str], None] | None = None,
    eta_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Despacha para o backend escolhido, com fallback automático em CPU."""
    if backend == "mlx":
        try:
            from hollytranscricao.backend.mlx_transcriber import transcribe_audio_mlx

            # A primeira ETA é apenas para o Whisper (MLX)
            _emit_eta(
                eta_callback,
                audio_duration,
                _FACTOR_MLX,
                "MLX-Whisper · GPU",
                overhead=_MLX_STARTUP_SECONDS,
            )
            return transcribe_audio_mlx(
                audio_path=audio_path,
                model_size=model_size,
                initial_prompt=initial_prompt,
                hf_token=hf_token,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
                progress_callback=progress_callback,
                eta_callback=eta_callback,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Backend MLX falhou. Tentando Faster-Whisper em CPU.")
            if progress_callback:
                # Aviso GRITANTE: o fallback de CPU é ~20x mais lento que a GPU.
                progress_callback(
                    "⚠️ ERRO: A GPU (MLX) FALHOU — caindo para CPU (Faster-Whisper), que é "
                    "MUITO mais lento. Motivo: " + str(exc)
                )
                if audio_duration > 0:
                    cpu_min = audio_duration / _FACTOR_CPU / 60.0
                    progress_callback(
                        f"⚠️ Na CPU este áudio pode levar ~{cpu_min:.0f} min "
                        f"(na GPU levaria ~{audio_duration / _FACTOR_MLX / 60.0:.1f} min). "
                        "Recomendado CANCELAR e me reportar o erro acima."
                    )

    from hollytranscricao.backend.transcriber import transcribe_audio

    _emit_eta(eta_callback, audio_duration, _FACTOR_CPU, "Faster-Whisper · CPU")
    return transcribe_audio(
        audio_path=audio_path,
        model_size=model_size,
        hf_token=hf_token,
        initial_prompt=initial_prompt,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
        progress_callback=progress_callback,
        eta_callback=eta_callback,
    )
