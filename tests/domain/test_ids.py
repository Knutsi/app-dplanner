from dplanner.domain.ids import next_id


def test_the_first_id_is_one():
    assert next_id([], "f") == "f1"


def test_the_next_id_is_one_past_the_highest_taken():
    assert next_id(["f1", "f3"], "f") == "f4"
    # A gap is never refilled: a removed record's id stays retired.
    assert next_id(["f2"], "f") == "f3"


def test_other_prefixes_and_odd_ids_are_ignored():
    assert next_id(["a1", "a2", "f1", "fx", "f"], "f") == "f2"
