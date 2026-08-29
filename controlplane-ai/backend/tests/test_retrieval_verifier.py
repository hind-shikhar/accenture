"""
Regression coverage for RetrievalVerifier._extract_claims's sentence
splitting. The old implementation split on every '.', which fractured
decimal figures like "14.2%" or "$2.8B" into separate claim fragments
that could never match a document's keywords/numbers. The fix must
preserve decimal points while still splitting on real sentence
boundaries that merely happen to follow a number (e.g. "...FY2025. Note:").
"""
from backend.app.evaluation.retrieval_verifier import retrieval_verifier


def test_decimal_figures_stay_within_one_claim():
    claims = retrieval_verifier._extract_claims(
        "Q3 FY2026 revenue grew 14.2% year-over-year, reaching $2.8B."
    )
    assert len(claims) == 1
    assert "14.2%" in claims[0]
    assert "$2.8B" in claims[0]


def test_sentence_boundary_after_a_number_still_splits():
    claims = retrieval_verifier._extract_claims(
        "Operating margin improved to 22.1% in Q3 FY2025. "
        "Note: figures are subject to final audit confirmation."
    )
    # The two sentences must NOT be merged just because "FY2025" ends in a digit.
    assert any("22.1%" in c and "Note" not in c for c in claims)


def test_multi_sentence_response_extracts_each_claim_intact():
    response = (
        "Q3 FY2026 revenue in the European market grew 14.2% year-over-year, reaching $2.8B. "
        "Key drivers included strong performance in the DACH region (+18.4%) and expansion of "
        "the enterprise middleware segment. Operating margin improved to 22.1%, up from 19.3% "
        "in Q3 FY2025. Note: figures are subject to final audit confirmation."
    )
    claims = retrieval_verifier._extract_claims(response)
    assert any(c.startswith("Q3 FY2026 revenue") and c.endswith("$2.8B") for c in claims)
    assert not any("Note" in c for c in claims), "trailing non-claim sentence should not merge into a claim"
