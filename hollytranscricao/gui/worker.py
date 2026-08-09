import logging

from PySide6.QtCore import QThread, Signal

from hollytranscricao.backend.orchestrator import run_transcription_pipeline

logger = logging.getLogger(__name__)


class TranscriptionWorker(QThread):
    """Thread de background para o pipeline de transcrição."""

    progress_signal = Signal(str)
    finished_signal = Signal(dict)  # mapa {"md": path, "srt": path, "txt": path}
    error_signal = Signal(str)
    eta_signal = Signal(float, str)  # (segundos estimados, rótulo do backend)

    def __init__(
        self,
        input_file_path: str,
        output_md_dir: str,
        hf_token: str,
        whisper_model: str,
        initial_prompt: str,
        apply_noise_reduction: bool,
        backend: str = "mlx",
        min_speakers: int | None = None,
        max_speakers: int | None = None,
        recording_type: str = "",
        write_md: bool = True,
        write_srt: bool = False,
        write_txt: bool = False,
    ):
        super().__init__()
        self.input_file_path = input_file_path
        self.output_md_dir = output_md_dir
        self.hf_token = hf_token
        self.whisper_model = whisper_model
        self.initial_prompt = initial_prompt
        self.apply_noise_reduction = apply_noise_reduction
        self.backend = backend
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers
        self.recording_type = recording_type
        self.write_md = write_md
        self.write_srt = write_srt
        self.write_txt = write_txt

    def run(self):
        try:
            logger.info("Iniciando worker de transcrição (backend=%s)...", self.backend)
            paths = run_transcription_pipeline(
                input_file_path=self.input_file_path,
                output_md_dir=self.output_md_dir,
                hf_token=self.hf_token,
                whisper_model=self.whisper_model,
                initial_prompt=self.initial_prompt,
                apply_noise_reduction=self.apply_noise_reduction,
                backend=self.backend,
                min_speakers=self.min_speakers,
                max_speakers=self.max_speakers,
                recording_type=self.recording_type,
                write_md=self.write_md,
                write_srt=self.write_srt,
                write_txt=self.write_txt,
                progress_callback=self.report_progress,
                eta_callback=self.report_eta,
            )
            self.finished_signal.emit(paths)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Worker falhou.")
            self.error_signal.emit(str(exc))

    def report_progress(self, message: str):
        self.progress_signal.emit(message)

    def report_eta(self, estimated_seconds: float, backend_label: str):
        self.eta_signal.emit(float(estimated_seconds), str(backend_label))
