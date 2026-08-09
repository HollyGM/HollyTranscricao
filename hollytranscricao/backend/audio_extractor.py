import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)


def check_ffmpeg() -> bool:
    """Verifica se o FFmpeg está instalado no sistema."""
    return shutil.which("ffmpeg") is not None


def resolve_ffmpeg() -> str:
    """Retorna o executável real, sem depender de resolução tardia do PATH."""
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("FFmpeg não encontrado. Instale o FFmpeg e abra o aplicativo novamente.")
    return executable


def extract_and_convert_audio(input_path: str, output_dir: str) -> str:
    """
    Extrai o áudio de um arquivo de vídeo ou converte um áudio existente
    para o formato padrão: WAV, 16kHz, 1-channel (mono), 16-bit PCM.

    Args:
        input_path: Caminho completo do arquivo de áudio/vídeo de entrada.
        output_dir: Diretório onde o arquivo convertido será temporariamente salvo.

    Returns:
        Caminho completo do arquivo .wav gerado.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Arquivo de entrada não encontrado: {input_path}")

    ffmpeg = resolve_ffmpeg()

    os.makedirs(output_dir, exist_ok=True)

    # Gerar nome do arquivo de saída com base no nome original do arquivo
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    output_path = os.path.join(output_dir, f"{base_name}_converted.wav")

    # Se o arquivo convertido já existir, removemos para evitar conflitos
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError as e:
            logger.warning(f"Não foi possível remover arquivo anterior: {e}")

    # Comando do FFmpeg:
    # -i: arquivo de entrada
    # -vn: desativa a gravação de vídeo (se houver)
    # -acodec pcm_s16le: codec de áudio PCM de 16 bits
    # -ar 16000: taxa de amostragem de 16kHz (padrão para Whisper)
    # -ac 1: mono (1 canal)
    # -y: sobrescrever arquivo de saída
    # -nostdin é obrigatório em apps GUI (sem stdin o FFmpeg pode bloquear esperando entrada)
    command = [
        ffmpeg,
        "-nostdin",
        "-y",
        "-i",
        input_path,
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        output_path,
    ]

    logger.info("Convertendo mídia com FFmpeg: %s", os.path.basename(input_path))

    # Executar processo em segundo plano capturando erros
    process = subprocess.run(  # noqa: S603 - executável resolvido por shutil.which
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )

    if process.returncode != 0:
        details = (process.stderr or "erro não informado").strip()[-2000:]
        logger.error("Erro no FFmpeg: %s", details)
        raise RuntimeError(f"FFmpeg falhou ao processar o arquivo: {details}")

    logger.info("Áudio convertido com sucesso: %s", output_path)
    return output_path
