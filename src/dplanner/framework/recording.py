"""Capturing the microphone through a peer process.

PySide6-Essentials ships no QtMultimedia, and the Addons package that has it is refused for
its weight (``pyproject.toml``), so the microphone is read by whichever recorder this machine
has — a row of :data:`~dplanner.domain.dictation.RECORDERS`, or a command somebody typed —
streaming raw signed 16-bit mono samples to its stdout. A :class:`QProcess` on the GUI thread
reads that pipe as it fills: no worker thread, no lock, and every signal here is delivered
by the event loop.

**Raw output is what makes stopping simple.** A WAV written by the recorder would need its
header patched at the end, which a killed process never does; raw samples have no trailer,
so whatever reached the pipe before the recorder died is the clip, and whoever wants a file
puts the header on (``core/wav.py``). That is also why stopping is one sequence everywhere:
``q`` on stdin (ffmpeg on POSIX takes it, every other recorder ignores it), then
``terminate()``, then ``kill()`` after a grace — on Windows only the last does anything to a
console process, and the bytes already read survive it.

**One process, kept.** A ``QProcess`` made in Python and dropped mid-run is deleted the
moment its last reference goes, killing the child from a destructor; one long-lived process
parented here is restarted per clip and dies with its owner.
"""

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

GRACE_MS = 500  # After terminate(): how long a recorder gets to exit before kill().
MAX_SECONDS = 120  # A forgotten microphone stops itself: 2.9 MB of 24 kHz samples.


class Recording(QObject):
    """One clip at a time from a recorder command; the samples arrive as it runs."""

    chunk = Signal(bytes)  # Each read of the pipe, as it arrives: what a live provider is fed.
    finished = Signal(bytes)  # The whole clip's samples, once the recorder has exited.
    failed = Signal(str)  # Could not start, or ended on its own with an error: the words.

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._process.readyReadStandardOutput.connect(self._read)
        self._process.finished.connect(self._finished)
        self._process.errorOccurred.connect(self._error)
        self._pcm = bytearray()
        self._program = ""
        self._live = False  # Between start() and the one finished/failed it owes.
        self._stopping = False
        self._cap = QTimer(self)
        self._cap.setSingleShot(True)
        self._cap.timeout.connect(self.stop)
        self._grace = QTimer(self)
        self._grace.setSingleShot(True)
        self._grace.timeout.connect(self._process.kill)

    def is_recording(self) -> bool:
        return self._live

    def bytes_read(self) -> int:
        """How much of the clip has arrived so far — what a test waits on before stopping."""
        return len(self._pcm)

    def start(self, command: list[str]) -> str | None:
        """Run ``command`` and collect its stdout; the refusal, or None when it started.

        Starting is asynchronous: a program that cannot start reports through ``failed``.
        """
        if self._live:
            return "already recording"
        if not command:
            return "no recorder command"
        self._pcm.clear()
        self._program = command[0]
        self._live = True
        self._stopping = False
        self._process.start(command[0], command[1:])
        self._cap.start(MAX_SECONDS * 1000)
        return None

    def stop(self) -> None:
        """Ask the recorder to end; ``finished`` follows with the clip."""
        if not self._live or self._stopping:
            return
        self._stopping = True
        self._cap.stop()
        if self._process.state() == QProcess.ProcessState.NotRunning:
            return  # Its own exit is on the way through _finished.
        self._process.write(b"q\n")
        self._process.closeWriteChannel()
        self._process.terminate()
        self._grace.start(GRACE_MS)

    def discard(self) -> None:
        """Forget the clip: kill the recorder and emit nothing."""
        self._live = False
        self._stopping = False
        self._cap.stop()
        self._grace.stop()
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
        self._pcm.clear()

    def _read(self) -> None:
        data = bytes(self._process.readAllStandardOutput().data())
        if data and self._live:
            self._pcm += data
            self.chunk.emit(data)

    def _finished(self, code: int, status: QProcess.ExitStatus) -> None:
        self._grace.stop()
        self._cap.stop()
        self._read()  # What the pipe still held when the recorder exited.
        if not self._live:
            return  # Discarded, or already reported as failed.
        self._live = False
        ended_badly = status == QProcess.ExitStatus.CrashExit or code != 0
        if ended_badly and not self._stopping:
            self.failed.emit(self._why(code))
            self._pcm.clear()
            return
        pcm = bytes(self._pcm)
        self._pcm.clear()
        self.finished.emit(pcm)

    def _error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart and self._live:
            self._live = False
            self._cap.stop()
            self.failed.emit(f"{self._program} could not be started — is it installed?")
        # Crashed after terminate() or kill() is the stop that was asked for; _finished
        # sees the clip through.

    def _why(self, code: int) -> str:
        stderr = bytes(self._process.readAllStandardError().data()).decode(errors="replace")
        return stderr.strip() or f"{self._program} exited with status {code}"
