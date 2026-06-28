from __future__ import annotations

import pytest

from jmi_enrichment.dedup import canonical_key, cosine_similarity, normalize_title


def test_normalize_title_strips_noise_and_genders():
    assert normalize_title("Senior Data Engineer (m/w/d) - Remote") == "senior data engineer"
    assert normalize_title("Analytics Engineer (Hybrid)") == "analytics engineer"


def test_canonical_key_is_source_agnostic():
    # Same role + company + country from two sources => same cluster key.
    a = canonical_key(company_name="Acme B.V.", title="Data Engineer (m/f)", country_code="NL")
    b = canonical_key(company_name="acme b v", title="data engineer", country_code="nl")
    assert a == b


def test_canonical_key_differs_on_company():
    a = canonical_key(company_name="Acme", title="Data Engineer", country_code="NL")
    b = canonical_key(company_name="Globex", title="Data Engineer", country_code="NL")
    assert a != b


def test_cosine_similarity():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([], [1]) == 0.0
