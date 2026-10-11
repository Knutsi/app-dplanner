"""The question record: its file, its states and who may move it between them."""

import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from dplanner.domain import questions
from dplanner.domain.questions import Question

AT = "2026-10-07T10:33:41+00:00"
PERSON = {"kind": "person", "name": "Knut"}
COORDINATOR = {"kind": "coordinator", "name": "kettle-actual"}


def _asked(**fields: object) -> Question:
    question = questions.asked(
        "p1",
        "s1",
        AT,
        [
            questions.one(
                "Keep both records?", "At-work", [("Keep both", "Two clocks"), ("Absorb", "")]
            )
        ],
        run="20261007T101500Z-9c1e44ab",
        by={"callsign": "kettle-three", "harness": "claude"},
    )
    return replace(question, **fields)  # type: ignore[arg-type]


def test_a_question_round_trips_through_its_file_in_its_month(tmp_path):
    question = _asked(body="the plan")
    questions.write(tmp_path, question)
    path = tmp_path / "questions" / "2026-10" / f"{question.id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["questions"][0]["options"][0] == {"label": "Keep both", "description": "Two clocks"}
    assert "answer" not in raw and "pass" not in raw  # Absence encodes the default.
    assert stored(tmp_path, question.id) == question
    assert questions.records(tmp_path) == [question]
    assert question.short == "Q-" + question.id.rpartition("-")[2][:4]


def test_a_file_this_build_cannot_read_is_skipped(tmp_path):
    question = _asked()
    questions.write(tmp_path, question)
    newer = tmp_path / "questions" / "2026-10" / "20261007T000000Z-ffffffff.json"
    newer.write_text(json.dumps({**question.to_json(), "format": 99, "id": "x"}), "utf-8")
    (newer.parent / "20261007T000001Z-eeeeeeee.json").write_text("{half", "utf-8")
    assert questions.records(tmp_path) == [question]


def test_an_answer_names_a_choice_by_its_own_label_or_keeps_the_words():
    question = _asked()
    assert questions.answers_for(question, "keep BOTH") == {"Keep both records?": "Keep both"}
    assert questions.answers_for(question, "Neither") == {"Keep both records?": "Neither"}


def test_the_states_move_one_way_and_refuse_the_rest():
    question = questions.answered(_asked(), {"Keep both records?": "Absorb"}, PERSON, AT)
    assert question.state == "answered" and question.answer["by"] == PERSON
    with pytest.raises(ValueError, match="already answered"):
        questions.answered(question, {}, PERSON, AT)
    with pytest.raises(ValueError, match="only an open question escalates"):
        questions.escalated(question, COORDINATOR, "a product call", AT)
    consumed = questions.consumed(question, AT, question.run, 2)
    assert consumed.consumed == {"at": AT, "run": question.run, "turn": 2}
    for move in (
        lambda q: questions.withdrawn(q, "late", AT),
        lambda q: questions.answered(q, {}, PERSON, AT),
    ):
        with pytest.raises(ValueError, match="consumed"):
            move(consumed)
    with pytest.raises(ValueError, match="not answered"):
        questions.consumed(_asked(), AT, "r", 2)


def test_an_escalated_question_can_still_be_answered_by_a_person():
    question = questions.escalated(_asked(), COORDINATOR, "a product call", AT)
    assert question.escalated == {"at": AT, "by": COORDINATOR, "why": "a product call"}
    assert questions.answered(question, {}, PERSON, AT).state == "answered"


def test_the_coordinator_may_not_answer_a_person_gate():
    gate = _asked(purpose="gate", stage="person-2", run="")
    assert "escalates it" in questions.may_answer(gate, "coordinator")
    assert questions.may_answer(gate, "person") == ""
    assert questions.may_answer(replace(gate, stage="coordinator"), "coordinator") == ""
    assert questions.may_answer(_asked(), "coordinator") == ""


def test_the_answer_text_quotes_each_question_and_its_answer():
    question = questions.answered(_asked(), {"Keep both records?": "Absorb"}, PERSON, AT)
    text = questions.answer_text(question)
    assert question.short in text and "> Keep both records?\nAbsorb" in text


def test_a_question_resolves_by_its_short_id_or_its_full_one(tmp_path):
    question = _asked()
    questions.write(tmp_path, question)
    assert questions.resolve(tmp_path, question.short) == question
    assert questions.resolve(tmp_path, question.short.lower()) == question
    assert questions.resolve(tmp_path, question.id) == question
    with pytest.raises(LookupError, match="no question"):
        questions.resolve(tmp_path, "Q-zzzz")


def test_withdrawing_a_runs_questions_leaves_the_kept_and_the_settled(tmp_path):
    kept, other = _asked(), _asked()
    done = replace(_asked(), state="consumed")
    for question in (kept, other, done):
        questions.write(tmp_path, question)
    questions.withdraw_unsettled(
        tmp_path, kept.run, "the run ended", keep=kept.id, config=tmp_path / "config"
    )
    states = {q.id: q.state for q in questions.records(tmp_path)}
    assert states == {kept.id: "open", other.id: "withdrawn", done.id: "consumed"}


def test_two_answers_at_once_land_one_and_refuse_the_other(tmp_path):
    question = _asked()
    questions.write(tmp_path, question)
    refused: list[str] = []

    def answer(name: str) -> None:
        try:
            questions.update(
                tmp_path,
                question.id,
                lambda q: questions.answered(q, {}, {"kind": "person", "name": name}, AT),
                tmp_path / "config",
            )
        except ValueError as error:
            refused.append(str(error))

    threads = [threading.Thread(target=answer, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(refused) == 1 and "already answered" in refused[0]
    assert stored(tmp_path, question.id).state == "answered"


def stored(project_dir: Path, question_id: str) -> Question:
    found = questions.find(project_dir, question_id)
    assert found is not None
    return found
