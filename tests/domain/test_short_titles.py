from dplanner.domain.model import Project
from dplanner.domain.short_titles import short_titles


def shortened(*titles: str) -> list[str]:
    projects = [Project(title=title) for title in titles]
    labels = short_titles(projects)
    return [labels[project.id] for project in projects]


def test_a_title_of_several_words_is_its_initials_with_numbers_whole():
    assert shortened("DPlanner changes 2", "Dermatology module", "Plan 2026 rollout") == [
        "DC2",
        "DM",
        "P2026R",
    ]


def test_a_one_word_title_stays_whole():
    assert shortened("Discovery", "DPlanner") == ["Discovery", "DPlanner"]


def test_an_untitled_project_is_called_so():
    assert shortened("") == ["Untitled project"]


def test_punctuation_and_hyphens_part_words():
    assert shortened("time-estimation-2", "Research & development") == ["TE2", "RD"]


def test_clashing_initials_grow_their_first_word_until_they_part():
    assert shortened("Dermatology module", "Delivery milestone", "Design map") == [
        "DerM",
        "DelM",
        "DesM",
    ]


def test_initials_that_clash_only_in_case_still_part():
    assert shortened("Data model", "DM") == ["DaM", "DM"]


def test_titles_growing_cannot_part_keep_their_whole_titles():
    assert shortened("Dermatology module", "Dermatology mapping", "Other thing") == [
        "Dermatology module",
        "Dermatology mapping",
        "OT",
    ]


def test_a_leading_number_that_clashes_keeps_the_whole_title():
    assert shortened("2026 roadmap", "2026 review") == ["2026 roadmap", "2026 review"]


def test_every_label_in_a_mixed_library_is_unique():
    titles = (
        "DPlanner changes 2",
        "Dermatology module",
        "Delivery milestone",
        "Discovery",
        "Data model",
        "DM",
        "Dermatology mapping",
        "Deployment manual",
    )
    labels = shortened(*titles)
    assert len({label.casefold() for label in labels}) == len(titles)
