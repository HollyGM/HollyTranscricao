import multiprocessing
import os
import queue
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hollytranscricao.backend import orchestrator, process_runner
from hollytranscricao.gui import worker as worker_module
from hollytranscricao.gui.worker import TranscriptionWorker


def _worker(tmp_path):
    return TranscriptionWorker(
        input_file_path=str(tmp_path / "audio.wav"),
        output_md_dir=str(tmp_path),
        hf_token="",
        whisper_model="large-v3-turbo",
        initial_prompt="",
        apply_noise_reduction=False,
    )


class _EventQueue(queue.Queue):
    closed = False
    joined = False

    def close(self):
        self.closed = True

    def join_thread(self):
        self.joined = True


class _Process:
    def __init__(self, context, options):
        self.context = context
        self.workspace = Path(options["work_dir"])
        self.pid = None
        self.exitcode = None
        self.alive = False
        self.closed = False
        self.start_calls = 0

    def start(self):
        self.start_calls += 1
        (self.workspace / "temporary.wav").write_bytes(b"temporary audio")
        if self.context.start_error:
            raise RuntimeError("engine could not start")
        self.pid = 123456
        if self.context.cancel_on_start:
            self.context.worker.cancel()
            self.alive = True
        else:
            self.exitcode = self.context.exitcode
            if self.context.event is not None:
                self.context.event_queue.put(self.context.event)

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        pass

    def close(self):
        self.closed = True


class _Context:
    def __init__(self, worker, event=None, exitcode=0, cancel_on_start=False, start_error=False):
        self.worker = worker
        self.event = event
        self.exitcode = exitcode
        self.cancel_on_start = cancel_on_start
        self.start_error = start_error
        self.event_queue = _EventQueue()
        self.process = None
        self.stop_calls = 0

    def Queue(self):
        return self.event_queue

    def Process(self, *, target, args, name):
        self.process = _Process(self, args[0])
        return self.process

    def stop(self, process):
        self.stop_calls += 1
        process.alive = False
        process.exitcode = -signal.SIGTERM


def _install_context(monkeypatch, context):
    monkeypatch.setattr(worker_module.multiprocessing, "get_context", lambda method: context)
    monkeypatch.setattr(TranscriptionWorker, "_stop_process", staticmethod(context.stop))


def test_cancel_before_run_does_not_create_engine(monkeypatch, tmp_path):
    worker = _worker(tmp_path)
    cancellations = []
    errors = []
    worker.cancelled_signal.connect(lambda: cancellations.append(True))
    worker.error_signal.connect(errors.append)

    def unexpected_context(method):
        pytest.fail("A cancelled operation must not create a process context")

    monkeypatch.setattr(worker_module.multiprocessing, "get_context", unexpected_context)
    worker.cancel()
    worker.run()

    assert cancellations == [True]
    assert errors == []
    assert worker._process is None


def test_cancel_during_start_stops_engine_and_cleans_before_signal(monkeypatch, tmp_path):
    worker = _worker(tmp_path)
    context = _Context(worker, cancel_on_start=True)
    _install_context(monkeypatch, context)
    observations = []
    errors = []
    finished = []
    worker.cancelled_signal.connect(
        lambda: observations.append(
            (context.process.alive, context.process.workspace.exists(), context.process.closed)
        )
    )
    worker.error_signal.connect(errors.append)
    worker.finished_signal.connect(finished.append)

    worker.run()

    assert context.process.start_calls == 1
    assert context.stop_calls >= 1
    assert observations == [(False, False, True)]
    assert context.event_queue.closed and context.event_queue.joined
    assert worker._process is None
    assert errors == [] and finished == []


@pytest.mark.parametrize("failure", ["pipeline_error", "native_crash", "start_error"])
def test_failures_clean_workspace_before_error_signal(monkeypatch, tmp_path, failure):
    worker = _worker(tmp_path)
    context = _Context(
        worker,
        event=("error", "decoding failed") if failure == "pipeline_error" else None,
        exitcode=-signal.SIGTERM if failure == "native_crash" else 0,
        start_error=failure == "start_error",
    )
    _install_context(monkeypatch, context)
    observations = []
    worker.error_signal.connect(
        lambda message: observations.append(
            (message, context.process.workspace.exists(), worker._process)
        )
    )

    worker.run()

    assert len(observations) == 1
    message, workspace_exists, current_process = observations[0]
    assert message
    assert workspace_exists is False
    assert current_process is None
    assert context.event_queue.closed and context.event_queue.joined
    if failure == "pipeline_error":
        assert message == "decoding failed"
    elif failure == "native_crash":
        assert "SIGTERM" in message
    else:
        assert message == "engine could not start"


def test_finished_signal_is_delivered_after_resources_are_released(monkeypatch, tmp_path):
    worker = _worker(tmp_path)
    outputs = {"txt": str(tmp_path / "transcript.txt")}
    context = _Context(worker, event=("finished", outputs))
    _install_context(monkeypatch, context)
    observations = []
    worker.finished_signal.connect(
        lambda paths: observations.append(
            (paths, context.process.workspace.exists(), context.event_queue.closed)
        )
    )

    worker.run()

    assert observations == [(outputs, False, True)]


@pytest.mark.parametrize("parent_owned", [False, True])
def test_pipeline_respects_workspace_owner_on_failure(monkeypatch, tmp_path, parent_owned):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(orchestrator.tempfile, "mkdtemp", lambda **kwargs: str(workspace))

    def fail_extraction(input_path, temporary_dir):
        (Path(temporary_dir) / "partial.wav").write_bytes(b"partial audio")
        raise RuntimeError("invalid audio")

    monkeypatch.setattr(orchestrator, "extract_and_convert_audio", fail_extraction)
    with pytest.raises(RuntimeError, match="invalid audio"):
        orchestrator.run_transcription_pipeline(
            input_file_path="audio.wav",
            output_md_dir=str(tmp_path),
            work_dir=str(workspace) if parent_owned else None,
        )

    assert workspace.exists() is parent_owned


def _engine_with_descendant(event_queue):
    """Run the actual process boundary with a media child that resists SIGTERM."""
    script = (
        "import signal,socket,time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "listener=socket.socket()\n"
        "listener.bind(('127.0.0.1',0))\n"
        "listener.listen()\n"
        "print(listener.getsockname()[1],flush=True)\n"
        "while True: time.sleep(60)\n"
    )

    def waiting_pipeline(**kwargs):
        descendant = subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", script], stdout=subprocess.PIPE, text=True
        )
        port = int(descendant.stdout.readline().strip())
        event_queue.put(
            ("ready", (os.getpid(), os.getpgrp(), descendant.pid, port))
        )
        while True:
            time.sleep(60)

    process_runner.run_transcription_pipeline = waiting_pipeline
    process_runner.run_pipeline_process({}, event_queue)


@pytest.mark.skipif(os.name != "posix", reason="Process groups require POSIX")
def test_stop_process_kills_descendant_without_signalling_parent_group():
    context = multiprocessing.get_context("spawn")
    event_queue = context.Queue()
    process = context.Process(target=_engine_with_descendant, args=(event_queue,))
    process.start()
    stopped = False
    try:
        kind, (engine_pid, engine_group, descendant_pid, port) = event_queue.get(timeout=20)
        assert kind == "ready"
        assert engine_pid == process.pid
        assert engine_group == process.pid
        assert engine_group != os.getpgrp()
        assert descendant_pid != engine_pid
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass

        TranscriptionWorker._stop_process(process)
        stopped = True

        assert not process.is_alive()
        deadline = time.monotonic() + 5
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    pass
            except OSError:
                break
            if time.monotonic() >= deadline:
                pytest.fail("A descendant survived cancellation of its process group")
            time.sleep(0.05)
    finally:
        if not stopped:
            TranscriptionWorker._stop_process(process)
        process.close()
        event_queue.close()
        event_queue.join_thread()
