"""TaskRunner: task lifecycle around a worker body, busy refusal, failure reporting,
progress marshalling, and cooperative cancellation."""

import threading
import time
import weakref

from PySide6.QtWidgets import QWidget

from dplanner.framework.task_runner import TaskRunner, TaskTimeoutError
from dplanner.framework.tasks import TaskService


def wait_idle(qtbot, runner: TaskRunner) -> None:
    """Wait for the queued busy_changed(False) that ends the current run."""
    with qtbot.waitSignal(runner.busy_changed, timeout=5000, check_params_cb=lambda busy: not busy):
        pass


def test_run_registers_a_task_and_finishes_it(app, qtbot) -> None:
    tasks = TaskService()
    runner = TaskRunner(tasks)

    with qtbot.waitSignal(runner.busy_changed, timeout=5000, check_params_cb=lambda busy: not busy):
        assert runner.run("Working", lambda: None)
        assert runner.is_busy()
        assert [t.label for t in tasks.active()] == ["Working"]

    assert not runner.is_busy()
    assert tasks.active() == []


def test_a_second_run_while_busy_is_refused(app, qtbot) -> None:
    tasks = TaskService()
    runner = TaskRunner(tasks)
    gate = threading.Event()

    def wait_for_gate() -> None:
        gate.wait(timeout=5)

    try:
        assert runner.run("First", wait_for_gate)
        assert not runner.run("Second", lambda: None)
        assert [t.label for t in tasks.active()] == ["First"]
    finally:
        gate.set()
    wait_idle(qtbot, runner)


def test_a_failing_body_emits_failed_and_frees_the_runner(app, qtbot) -> None:
    tasks = TaskService()
    runner = TaskRunner(tasks)

    def boom() -> None:
        raise RuntimeError("kaboom")

    with qtbot.waitSignal(runner.failed, timeout=5000) as blocker:
        assert runner.run("Working", boom)

    assert "kaboom" in blocker.args[0]
    assert tasks.active() == []
    assert runner.run("Again", lambda: None)  # The runner is reusable after a failure.
    wait_idle(qtbot, runner)


def test_report_progress_reaches_the_task(app, qtbot) -> None:
    tasks = TaskService()
    runner = TaskRunner(tasks)

    with qtbot.waitSignal(runner.busy_changed, timeout=5000, check_params_cb=lambda busy: not busy):
        assert runner.run("Working", lambda: runner.report_progress(0.25))
        task = tasks.active()[0]

    # The queued progress marshal lands before the queued completion.
    assert task.progress == 0.25


def test_body_observes_cooperative_cancel(app, qtbot) -> None:
    tasks = TaskService()
    runner = TaskRunner(tasks)
    started = threading.Event()

    def body() -> None:
        started.set()
        while not runner.cancel_requested():
            time.sleep(0.01)

    with qtbot.waitSignal(runner.busy_changed, timeout=5000, check_params_cb=lambda busy: not busy):
        assert runner.run("Reading", body, cancellable=True)
        assert started.wait(timeout=5)
        tasks.cancel(tasks.active()[0])  # Worker exits its loop; run finishes cleanly.

    assert tasks.active() == []


def test_task_options_land_on_the_task(app, qtbot) -> None:
    tasks = TaskService()
    runner = TaskRunner(tasks)

    def factory() -> QWidget:
        return QWidget()

    with qtbot.waitSignal(runner.busy_changed, timeout=5000, check_params_cb=lambda busy: not busy):
        assert runner.run(
            "Reading through",
            lambda: None,
            key="readthrough",
            cancellable=True,
            keep_finished=True,
            detail_factory=factory,
        )
        task = tasks.active()[0]

    assert task.key == "readthrough"
    assert task.cancellable
    assert task.keep_finished
    assert task.detail_factory is factory
    assert tasks.finished() == [task]  # keep_finished: it lingers after the run.


def test_body_raising_task_timeout_error_marks_the_task_timed_out(app, qtbot) -> None:
    tasks = TaskService()
    runner = TaskRunner(tasks)

    def body() -> None:
        raise TaskTimeoutError("request timed out after 120s")

    with qtbot.waitSignal(runner.busy_changed, timeout=5000, check_params_cb=lambda busy: not busy):
        assert runner.run("Reading through", body, keep_finished=True)
        task = tasks.active()[0]

    assert task.timed_out
    assert task.error is None  # Timed out, not failed.
    assert not runner.is_busy()  # A new run may start right away.


# -- lifetime: nothing the worker thread holds may die on the worker thread ----------------
#
# PySide deletes a Python-owned QObject wherever its last reference goes. A worker that
# dropped the last reference to the runner (or to the service its body closed over) right
# after queueing the completion would delete the object while the GUI thread delivers
# that very event — the segfault in QCoreApplication::notify that haunted the suite.


def released_on(obj: object) -> list[threading.Thread]:
    """The thread that freed ``obj``, recorded when it happens."""
    threads: list[threading.Thread] = []
    weakref.finalize(obj, lambda: threads.append(threading.current_thread()))
    return threads


def test_the_runner_is_released_on_the_gui_thread_after_its_completion(app, qtbot) -> None:
    tasks = TaskService()
    runner = TaskRunner(tasks)
    freed = released_on(runner)
    gate = threading.Event()
    idle = runner.busy_changed  # A signal instance holds no reference to its QObject.

    def wait_for_gate() -> None:
        gate.wait(timeout=5)

    assert runner.run("Working", wait_for_gate)
    del runner  # Only the worker's handoff still holds it.

    with qtbot.waitSignal(idle, timeout=5000, check_params_cb=lambda busy: not busy):
        gate.set()

    qtbot.waitUntil(lambda: bool(freed), timeout=5000)  # Released on the next loop turn.
    assert freed == [threading.main_thread()]


def test_the_body_and_its_captures_are_released_on_the_gui_thread(app, qtbot) -> None:
    class Service:  # Stands in for the QObject a body closes over.
        def work(self) -> None:
            pass

    service = Service()
    freed = released_on(service)
    tasks = TaskService()
    runner = TaskRunner(tasks)
    body = service.work
    del service

    with qtbot.waitSignal(runner.busy_changed, timeout=5000, check_params_cb=lambda busy: not busy):
        assert runner.run("Working", body)
        del body  # The worker's handoff holds the only reference now.

    qtbot.waitUntil(lambda: bool(freed), timeout=5000)
    assert freed == [threading.main_thread()]
