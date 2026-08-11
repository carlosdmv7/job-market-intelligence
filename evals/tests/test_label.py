"""The labelling CLI's pure parts: what it surfaces first, and what it refuses."""

from __future__ import annotations

from jmi_core.schema import VisaSponsorshipStatus
from jmi_evals.dataset import GoldenRecord, text_hash
from jmi_evals.label import CHOICES, signal_hits, triage_order


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
        ]
    )
    assert [r.content_hash for r in queue] == ["b", "c", "a"]


def test_triage_skips_rows_that_already_have_a_label():
    queue = triage_order(
        [
            _rec("visa sponsorship", labelled=True, content_hash="done"),
            _rec("nothing relevant", content_hash="todo"),
        ]
    )
    assert [r.content_hash for r in queue] == ["todo"]


def test_choices_cover_the_whole_enum_exactly_once():
    # The keys 1-5 must reach every class; a missing one would be unlabelable.
    assert set(CHOICES) == set(VisaSponsorshipStatus)
    assert len(CHOICES) == len(VisaSponsorshipStatus)
