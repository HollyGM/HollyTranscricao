"""Executa o pipeline em um processo isolado.

Bibliotecas de GPU como MLX/Metal podem encerrar o processo com um sinal nativo
(por exemplo, SIGBUS) antes que o Python consiga gerar uma exceção. Manter o
motor fora do processo da interface impede que esse tipo de falha feche o app.
"""

from __future__ import annotations

from typing import Any

from hollytranscricao.backend.orchestrator import run_transcription_pipeline


def run_pipeline_process(options: dict[str, Any], event_queue: Any) -> None:
    """Executa o pipeline e envia eventos serializáveis ao processo da interface."""

    def report_progress(message: str) -> None:
        event_queue.put(("progress", str(message)))

    def report_eta(estimated_seconds: float, backend_label: str) -> None:
        event_queue.put(("eta", (float(estimated_seconds), str(backend_label))))

    try:
        paths = run_transcription_pipeline(
            **options,
            progress_callback=report_progress,
            eta_callback=report_eta,
        )
        event_queue.put(("finished", paths))
    except Exception as exc:  # noqa: BLE001
        event_queue.put(("error", str(exc)))
    finally:
        # Garante que o feeder thread entregue o último evento antes de o
        # processo terminar. Falhas nativas não passam por este bloco e são
        # detectadas pelo código de saída no processo pai.
        event_queue.close()
        event_queue.join_thread()
