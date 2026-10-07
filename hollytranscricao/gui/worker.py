import logging
import multiprocessing
import os
import queue
import signal
import tempfile
from contextlib import suppress

from PySide6.QtCore import QThread, Signal

from hollytranscricao.backend.process_runner import run_pipeline_process

logger = logging.getLogger(__name__)


class TranscriptionWorker(QThread):
    """Thread de background para o pipeline de transcrição."""

    progress_signal = Signal(str)
    finished_signal = Signal(dict)  # mapa {"md": path, "srt": path, "txt": path}
    error_signal = Signal(str)
    cancelled_signal = Signal()
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
        self._process = None
        self._cancel_requested = False

    def run(self):
        event_queue = None
        workspace = None
        terminal_event: tuple[str, object] | None = None
        error_message = None
        try:
            if self._cancel_requested:
                self.cancelled_signal.emit()
                return
            logger.info("Iniciando worker de transcrição (backend=%s)...", self.backend)
            workspace = tempfile.TemporaryDirectory(prefix="hollytranscricao_")
            options = {
                "input_file_path": self.input_file_path,
                "output_md_dir": self.output_md_dir,
                "hf_token": self.hf_token,
                "whisper_model": self.whisper_model,
                "initial_prompt": self.initial_prompt,
                "apply_noise_reduction": self.apply_noise_reduction,
                "backend": self.backend,
                "min_speakers": self.min_speakers,
                "max_speakers": self.max_speakers,
                "recording_type": self.recording_type,
                "write_md": self.write_md,
                "write_srt": self.write_srt,
                "write_txt": self.write_txt,
                "work_dir": workspace.name,
            }

            context = multiprocessing.get_context("spawn")
            event_queue = context.Queue()
            self._process = context.Process(
                target=run_pipeline_process,
                args=(options, event_queue),
                name="HollyTranscricaoEngine",
            )
            if not self._cancel_requested:
                self._process.start()

            while self._process.is_alive():
                if self._cancel_requested:
                    self._stop_process(self._process)
                    break
                event = self._next_event(event_queue, timeout=0.2)
                if event is not None:
                    terminal_event = self._forward_event(event) or terminal_event

            if self._process.pid is not None:
                self._process.join()
            while not self._cancel_requested:
                event = self._next_event(event_queue, timeout=0.0)
                if event is None:
                    break
                terminal_event = self._forward_event(event) or terminal_event

            if terminal_event is None and not self._cancel_requested:
                exit_code = self._process.exitcode
                error_message = self._native_failure_message(exit_code)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Worker falhou.")
            error_message = str(exc)
        finally:
            process = self._process
            if process is not None and process.pid is not None:
                self._stop_process(process)
                process.close()
            if event_queue is not None:
                event_queue.close()
                event_queue.join_thread()
            self._process = None
            if workspace is not None:
                try:
                    workspace.cleanup()
                except OSError as exc:
                    logger.warning("Não removeu temporários %s: %s", workspace.name, exc)

        # A interface só pode iniciar outra operação após a liberação do motor
        # e dos temporários desta transcrição.
        if self._cancel_requested:
            self.cancelled_signal.emit()
        elif error_message is not None:
            self.error_signal.emit(error_message)
        elif terminal_event is not None and terminal_event[0] == "finished":
            self.finished_signal.emit(terminal_event[1])
        elif terminal_event is not None:
            self.error_signal.emit(str(terminal_event[1]))

    @staticmethod
    def _stop_process(process):
        """Encerra o motor e, no macOS/Linux, seus subprocessos de mídia."""
        group_signalled = False
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
                group_signalled = True
            except ProcessLookupError:
                pass  # O filho ainda não executou setsid, ou o grupo já saiu.
        if process.is_alive() and not group_signalled:
            process.terminate()
        process.join(timeout=3)
        if os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        if process.is_alive():
            process.kill()
            process.join(timeout=3)

    @staticmethod
    def _next_event(event_queue, timeout: float):
        try:
            if timeout > 0:
                return event_queue.get(timeout=timeout)
            return event_queue.get_nowait()
        except queue.Empty:
            return None

    def _forward_event(self, event):
        kind, payload = event
        if kind == "progress":
            self.progress_signal.emit(str(payload))
        elif kind == "eta":
            seconds, label = payload
            self.eta_signal.emit(float(seconds), str(label))
        elif kind in {"finished", "error"}:
            return kind, payload
        return None

    @staticmethod
    def _native_failure_message(exit_code: int | None) -> str:
        if exit_code is not None and exit_code < 0:
            signal_number = -exit_code
            try:
                signal_name = signal.Signals(signal_number).name
            except ValueError:
                signal_name = f"sinal {signal_number}"
            return (
                "O motor de transcrição foi encerrado por uma falha nativa "
                f"({signal_name}). O aplicativo permaneceu aberto porque o motor roda "
                "em um processo protegido. Tente o Large V3 Turbo ou feche outros "
                "aplicativos para liberar memória."
            )
        return (
            "O motor de transcrição terminou inesperadamente "
            f"(código {exit_code}). Tente novamente com o Large V3 Turbo."
        )

    def cancel(self):
        """Interrompe inclusive downloads ou chamadas nativas bloqueantes."""
        self._cancel_requested = True
        self.requestInterruption()
        # A thread monitora a flag também durante o startup e encerra o grupo
        # de processos. Evita a corrida entre cancel() e Process.start().

    def report_progress(self, message: str):
        self.progress_signal.emit(message)

    def report_eta(self, estimated_seconds: float, backend_label: str):
        self.eta_signal.emit(float(estimated_seconds), str(backend_label))
