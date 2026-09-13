"""The labelling CLI's pure parts: what it surfaces first, and what it refuses."""

from __future__ import annotations

from jmi_core.schema import VisaSponsorshipStatus
from jmi_evals.dataset import GoldenRecord, text_hash
from jmi_evals.label import _CHOICES, signal_hits, triage_order
from jmi_evals.targets import ENGLISH, VISA, EnglishSufficiency


def _rec(text: str, *, labelled: bool = False, content_hash: str = "abc") -> GoldenRecord:
    return GoldenRecord(
        content_hash=content_hash,
        text_sha256=text_hash(text),
        prompt_input=text,
        visa_status_true=VisaSponsorshipStatus.UNCLEAR if labelled else None,
    )


def test_signal_hits_finds_right_to_work_vocabulary():
    hits = signal_hits("We offer visa sponsorship and help with relocation.")
    assert "visa" in hits
    assert "sponsorship" in hits
    assert "relocation" in hits


def test_signal_hits_is_empty_for_a_posting_that_never_mentions_it():
    assert signal_hits("We need a Python developer with dbt experience.") == []


def test_signal_hits_does_not_match_inside_other_words():
    # "supervisation" contains "visa"; a substring match would make the
    # triage order meaningless on ordinary prose.
    assert signal_hits("Supervisation of the team") == []


def test_triage_puts_the_richest_signal_first():
    queue = triage_order(
        [
            _rec("plain backend role", content_hash="a"),
            _rec("visa sponsorship and relocation offered", content_hash="b"),
            _rec("we mention a visa once", content_hash="c"),
        ],
        target=VISA,
    )
    assert [r.content_hash for r in queue] == ["b", "c", "a"]


def test_triage_puts_scoreable_postings_before_richer_unscoreable_ones():
    # The first real labelling session produced nine labels and nothing
    # scoreable: ordering by signal alone walked straight into postings the
    # pipeline had never enriched. A label on an unenriched posting buys no
    # score until the quota reaches it, so "can be scored today" outranks
    # "discusses visas the most".
    queue = triage_order(
        [
            _rec("visa sponsorship relocation work permit", content_hash="rich_no_response"),
            _rec("we mention a visa once", content_hash="poor_with_response"),
        ],
        target=VISA,
        scoreable={"poor_with_response"},
    )
    assert [r.content_hash for r in queue] == ["poor_with_response", "rich_no_response"]


def test_triage_still_ranks_by_signal_within_the_scoreable_group():
    queue = triage_order(
        [
            _rec("nothing relevant here", content_hash="a"),
            _rec("visa sponsorship and relocation", content_hash="b"),
        ],
        target=VISA,
        scoreable={"a", "b"},
    )
    assert [r.content_hash for r in queue] == ["b", "a"]


def test_triage_skips_rows_that_already_have_a_label():
    queue = triage_order(
        [
            _rec("visa sponsorship", labelled=True, content_hash="done"),
            _rec("nothing relevant", content_hash="todo"),
        ],
        target=VISA,
    )
    assert [r.content_hash for r in queue] == ["todo"]


def test_choices_cover_every_class_of_every_target_exactly_once():
    # The number keys must reach every class; a missing one would be unlabelable.
    assert set(_CHOICES["visa"]) == {s.value for s in VisaSponsorshipStatus}
    assert len(_CHOICES["visa"]) == len(VisaSponsorshipStatus)
    assert set(_CHOICES["english"]) == {e.value for e in EnglishSufficiency}
    assert len(_CHOICES["english"]) == len(EnglishSufficiency)


def test_english_signal_finds_language_vocabulary():
    hits = signal_hits("Fluent Dutch is required; English is a plus.", "english")
    assert "dutch" in hits
    assert "english" in hits
    assert "fluent" in hits


def test_english_signal_ignores_visa_vocabulary():
    # Each target highlights only what decides *its* question, so a posting
    # full of sponsorship talk must not be pushed to the front of an English pass.
    assert signal_hits("We sponsor visas and help you relocate.", "english") == []


def test_the_two_targets_are_labelled_independently():
    rec = _rec("fluent Dutch required", content_hash="a")
    assert triage_order([rec], target=ENGLISH) == [rec]
    rec.english_sufficient_true = EnglishSufficiency.NO
    # Labelled for english, still unlabelled for visa — not "done".
    assert triage_order([rec], target=ENGLISH) == []
    assert triage_order([rec], target=VISA) == [rec]
