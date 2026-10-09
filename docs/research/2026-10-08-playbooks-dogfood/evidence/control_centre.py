"""The real window over the toy library, offscreen: show the Control Centre and press a card.

    toy python control_centre.py shot NAME                  # the Control Centre and the graph
    toy python control_centre.py press NAME QID 'LABEL'     # a choice, or 'Retry Now'
    toy python control_centre.py type NAME QID 'WORDS'      # a person's own words
    toy python control_centre.py tab NAME KIND              # another of the project's tabs

Every press grabs the window before and after, so the report shows what a person saw.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dplanner.app import configure_application, new_session, set_early_attributes  # noqa: E402
from dplanner.modules.agent_questions.panel import QuestionCard  # noqa: E402

SHOTS = Path(__file__).resolve().parent / "shots"
SIZE = (1280, 860)


def settle(app: QApplication, seconds: float = 1.5) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.05)


def main() -> None:
    import faulthandler

    faulthandler.dump_traceback_later(40, exit=True)
    mode, name, *rest = sys.argv[1:]
    SHOTS.mkdir(exist_ok=True)
    set_early_attributes()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp(prefix="cc-qs-")
    )
    app = QApplication([])
    configure_application(app)
    session = new_session()
    assert session.open_initial(Path(os.environ["DPLANNER_LIBRARY"]))
    services, window = session.services, session.window
    assert services is not None and window is not None
    window.resize(*SIZE)
    window.show()
    project = services.document.projects[0]

    def grab(suffix: str) -> None:
        services.tabs.open("project", project.id)
        settle(app)
        window.grab().save(str(SHOTS / f"{name}-{suffix}-graph.png"))
        services.tabs.open("control_centre")
        settle(app)
        window.grab().save(str(SHOTS / f"{name}-{suffix}-cc.png"))
        for card in window.findChildren(QuestionCard):
            q = card.facts.question
            words = [b.text() for b in card.options] + (["Retry Now"] if card.retry else [])
            print(f"[{suffix}] card {q.id} {q.kind} {q.state} | {card.kind.text()} | "
                  f"{card.agent.text()} | {card.text.text()[:300]!r} | {words} | "
                  f"status={card.status.text() if hasattr(card.status, 'text') else ''}")
        print(f"[{suffix}] status bar: {window.statusBar().currentMessage()!r}")

    if mode == "tab":  # Any other tab of the project: tab NAME KIND (expenditure, progression…)
        services.tabs.open(rest[0], project.id)
        settle(app, 3)
        window.grab().save(str(SHOTS / f"{name}-{rest[0]}.png"))
        sys.stdout.flush()
        os._exit(0)
    grab("before" if mode != "shot" else "now")
    if mode in ("press", "type"):
        qid, given = rest
        card = next(c for c in window.findChildren(QuestionCard) if c.facts.question.id.endswith(qid.removeprefix("Q-")) or qid.removeprefix("Q-") in c.facts.question.id)
        if mode == "type":
            assert card.field is not None and card.send is not None
            card.field.setText(given)
            card.send.click()
        elif given == "Retry Now":
            assert card.retry is not None
            card.retry.click()
        else:
            next(b for b in card.options if b.text() == given).click()
        settle(app, 3)
        grab("after")
    sys.stdout.flush()
    os._exit(0)  # Closing asks to save: the plan is the CLI's, and the window must not commit it.


if __name__ == "__main__":
    main()
