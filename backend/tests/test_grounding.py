from app.ai.grounding import Evidence, extract_numbers, fmt_usd, validate_statements


def ev(id_, values, text="fact"):
    return Evidence(id=id_, kind="trade_stat", text=text, values=values)


EVIDENCE = [ev("E1", [2_404_909_000.0, 0.315]), ev("E2", [760_749_300.0]), ev("E3", [], "gap")]


def test_fmt_usd():
    assert fmt_usd(2_404_909_000) == "$2.40 billion"
    assert fmt_usd(760_749_300) == "$760.7 million"
    assert fmt_usd(12_500) == "$12,500"


def test_extract_numbers_handles_units_percent_and_years():
    nums = extract_numbers("In 2024 the USA imported $2.4 billion (31.5% share), up from 950 million.")
    assert 2.4e9 in nums and 0.315 in [round(n, 3) for n in nums] and 9.5e8 in nums
    assert 2024 not in nums  # years ignored
    assert extract_numbers("ranked 3rd of 5 markets") == []  # small ordinals ignored
    assert extract_numbers("€1,234,567") == [1234567.0]


def test_verified_statement_with_matching_numbers_passes():
    out = validate_statements(
        [{"text": "The USA imported $2.4 billion, a 31.5% share.", "label": "verified", "evidence_ids": ["E1"]}],
        EVIDENCE,
    )
    assert out[0]["label"] == "verified" and out[0]["issues"] == []


def test_unknown_ids_are_removed_and_verified_without_evidence_downgraded():
    out = validate_statements(
        [{"text": "Demand is resilient.", "label": "verified", "evidence_ids": ["E99"]}], EVIDENCE
    )
    assert out[0]["evidence_ids"] == []
    assert out[0]["label"] == "inference"
    assert "unknown_evidence:E99" in out[0]["issues"]


def test_number_not_in_cited_evidence_is_flagged_unverified():
    out = validate_statements(
        [{"text": "Imports reached $3.9 billion.", "label": "verified", "evidence_ids": ["E1"]}], EVIDENCE
    )
    assert out[0]["label"] == "unverified"
    assert any(i.startswith("unsupported_number") for i in out[0]["issues"])


def test_number_must_come_from_cited_ids_not_any_evidence():
    out = validate_statements(
        [{"text": "UK imports were $760.7 million.", "label": "verified", "evidence_ids": ["E1"]}], EVIDENCE
    )
    assert out[0]["label"] == "unverified"


def test_inference_with_numbers_also_checked_and_unavailable_kept():
    out = validate_statements(
        [
            {"text": "Freight cost data is not available.", "label": "unavailable", "evidence_ids": ["E3"]},
            {"text": "A 12% price premium is likely.", "label": "inference", "evidence_ids": []},
        ],
        EVIDENCE,
    )
    assert out[0]["label"] == "unavailable" and out[0]["issues"] == []
    assert out[1]["label"] == "unverified"


def test_live_run_false_positives_are_fixed():
    """Statements from the first live Claude run (26 Oct 2026) that were wrongly marked unverified."""
    ev = [
        Evidence("E28", "score", "UK scored 85.0/100", [85.0, 0.86, 0.37]),
        Evidence("E44", "trade_stat", "SYR share 0.0%", [0.0]),
        Evidence("E5", "trade_stat", "UK imports", [833_100_000.0]),
    ]
    out = validate_statements(
        [
            {"text": "United Kingdom scored 85.0/100 for HS 190531.", "label": "verified", "evidence_ids": ["E28"]},
            {"text": "The USA price level score of 0.37 is the lowest.", "label": "verified", "evidence_ids": ["E28"]},
            {"text": "Syria holds 0.0% of imports.", "label": "verified", "evidence_ids": ["E44"]},
            {
                "text": "The UK imported $833.1 million of HS code 190531 in 2025.",
                "label": "verified",
                "evidence_ids": ["E5"],
            },
        ],
        ev,
    )
    assert [s["label"] for s in out] == ["verified"] * 4, [s["issues"] for s in out]
    # still strict: a wrong score or share is caught
    bad = validate_statements(
        [{"text": "UK scored 91.0/100 with a 4% share.", "label": "verified", "evidence_ids": ["E28"]}], ev
    )
    assert bad[0]["label"] == "unverified"


def test_live_brief_false_positives_are_fixed():
    """Withheld statements from the first live market brief (26 Oct 2026)."""
    ev = [
        Evidence(
            "E2",
            "catalogue",
            "Our products: Ma'amoul Dates (350 g, Carton box); Ma'amoul Dates (500 g, Tin)",
            [350, 500],
        ),
        Evidence("E44", "trade_stat", "SYR holds 0.0% of USA imports.", [1.867523850441071e-05]),
        Evidence("E60", "news", "Market development (2026-09-25): USDA forecast", []),
    ]
    out = validate_statements(
        [
            {
                "text": "We offer Ma'amoul Dates in a 350 g carton and a 500 g tin.",
                "label": "verified",
                "evidence_ids": ["E2"],
            },
            {"text": "SYR holds 0.0% of USA imports.", "label": "verified", "evidence_ids": ["E44"]},
            {
                "text": "USDA (reported 2026-09-25) expects sweets prices to rise.",
                "label": "verified",
                "evidence_ids": ["E60"],
            },
        ],
        ev,
    )
    assert [s["label"] for s in out] == ["verified"] * 3, [s["issues"] for s in out]
    assert (
        validate_statements([{"text": "SYR holds 2.5% of imports.", "label": "verified", "evidence_ids": ["E44"]}], ev)[
            0
        ]["label"]
        == "unverified"
    )
