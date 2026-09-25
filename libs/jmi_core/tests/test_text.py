"""repair_mojibake: undo UTF-8 read as Latin-1, and nothing else."""

from __future__ import annotations

import pytest

from jmi_core.text import repair_mojibake


@pytest.mark.parametrize(
    "original",
    ["Mecánico Automotriz", "مسقط, عمان", "Freelance Transcriptionist — Sinhalese", "TEMPORÁRIO"],
)
def test_double_encoded_text_is_restored(original):
    assert repair_mojibake(original.encode().decode("latin-1")) == original


@pytest.mark.parametrize("clean", ["Café", "Zürich", "Data Engineer", "東京", "", None])
def test_clean_text_is_left_alone(clean):
    assert repair_mojibake(clean) == clean
