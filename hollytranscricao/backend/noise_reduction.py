import logging
import os
import shutil
import subprocess
from contextlib import suppress

from hollytranscricao.backend.audio_extractor import resolve_ffmpeg

logger = logging.getLogger(__name__)


def clean_audio(
    input_wav_path: str, output_dir: str, force_ffmpeg: bool = False
) -> tuple[str, bool]:
    """
    Remove ruído do arquivo de áudio utilizando DeepFilterNet (IA) ou FFmpeg afftdn (fallback).

    Args:
        input_wav_path: Caminho do arquivo WAV de 16kHz mono de entrada.
        output_dir: Diretório onde o arquivo limpo será salvo.
        force_ffmpeg: Se True, ignora DeepFilterNet e usa o filtro do FFmpeg diretamente.

    Returns:
        Um tuple contendo:
        - Caminho do arquivo de áudio limpo (WAV 16kHz mono).
        - Booleano indicando se o tratamento inteligente foi aplicado com sucesso.
    """
    if not os.path.exists(input_wav_path):
        raise FileNotFoundError(f"Arquivo WAV não encontrado: {input_wav_path}")

    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_wav_path))[0]
    output_wav_path = os.path.join(output_dir, f"{base_name}_cleaned.wav")

    # Se já existir o arquivo limpo anterior, removemos
    if os.path.exists(output_wav_path):
        with suppress(OSError):
            os.remove(output_wav_path)

    applied_smart_denoise = False
    ffmpeg = resolve_ffmpeg()

    if not force_ffmpeg:
        try:
            logger.info("Tentando aplicar redução de ruído via DeepFilterNet...")
            # Importa dinamicamente para não carregar PyTorch quando não for usado.
            import torch
            from df.enhance import enhance, init_df, load_audio, save_audio

            # Inicializar modelo DeepFilterNet (baixa automaticamente os pesos na primeira execução)
            # Nota: DeepFilterNet roda melhor na CPU do Mac ou via MPS se suportado.
            # Por padrão, ele gerencia o dispositivo de execução.
            device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
            logger.info(f"DeepFilterNet utilizando dispositivo: {device}")

            model, df_state, _ = init_df()
            model = model.to(device)

            # DeepFilterNet opera nativamente em 48 kHz e faz resampling internamente.
            audio, _ = load_audio(input_wav_path, sr=model.config.sr)
            audio = audio.to(device)

            # Aplicar filtro
            enhanced_audio = enhance(model, df_state, audio)

            # Salvar áudio temporário (pode estar em 48kHz)
            temp_output = os.path.join(output_dir, f"{base_name}_temp_df.wav")
            save_audio(temp_output, enhanced_audio.to("cpu"), sr=model.config.sr)

            # Converter de volta para 16kHz mono para WhisperX
            command = [
                ffmpeg,
                "-nostdin",
                "-y",
                "-i",
                temp_output,
                "-ar",
                "16000",
                "-ac",
                "1",
                output_wav_path,
            ]
            subprocess.run(  # noqa: S603 - executável resolvido por shutil.which
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=True,
                shell=False,
            )

            # Limpar arquivo temporário
            if os.path.exists(temp_output):
                os.remove(temp_output)

            logger.info("Redução de ruído via DeepFilterNet concluída com sucesso.")
            applied_smart_denoise = True
            return output_wav_path, applied_smart_denoise

        except (ImportError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
            logger.warning("Falha ao usar DeepFilterNet (%s). Usando FFmpeg...", exc)

    # Fallback: Usar o filtro afftdn do FFmpeg
    try:
        logger.info("Aplicando redução de ruído clássica via FFmpeg afftdn...")
        # afftdn é um denoiser de FFT muito leve e eficiente no FFmpeg
        command = [
            ffmpeg,
            "-nostdin",
            "-y",
            "-i",
            input_wav_path,
            "-af",
            "afftdn=nf=-25",  # nf=-25 define o piso de ruído desejado
            "-ar",
            "16000",
            "-ac",
            "1",
            output_wav_path,
        ]

        process = subprocess.run(  # noqa: S603 - executável resolvido por shutil.which
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )

        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg afftdn falhou: {process.stderr}")

        logger.info("Redução de ruído via FFmpeg concluída.")
        return output_wav_path, applied_smart_denoise

    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.error("Todas as tentativas de redução de ruído falharam: %s", exc)
        # Mantém o áudio original para não interromper a transcrição.
        shutil.copy(input_wav_path, output_wav_path)
        return output_wav_path, False
