import math

import pytest

from app.analytics import DEFAULT_WEIGHTS, MarketInput, cagr, hhi, score_markets, unit_value


def test_cagr_basic_and_edge_cases():
    assert cagr({2020: 100.0, 2022: 121.0}) == pytest.approx(0.10)
    assert cagr({2023: 50.0}) is None  # single year
    assert cagr({2020: 0.0, 2023: 10.0}) is None  # zero base
    # uses first and last available years, ignoring gaps
    assert cagr({2019: 100.0, 2021: 50.0, 2023: 146.41}) == pytest.approx(0.10)


def test_hhi_and_unit_value():
    assert hhi([50, 50]) == pytest.approx(0.5)
    assert hhi([100]) == pytest.approx(1.0)
    assert hhi([]) is None
    assert hhi([0, 0]) is None
    assert unit_value(1000.0, 250.0) == pytest.approx(4.0)
    assert unit_value(1000.0, None) is None
    assert unit_value(1000.0, 0.0) is None


def _m(m49, values, kg=None, partners=None):
    return MarketInput(
        m49=m49, iso3=f"C{m49:02d}", name=f"Country {m49}", series=values, latest_kg=kg, partner_values=partners
    )


def test_score_is_deterministic_bounded_and_explained():
    markets = [
        _m(1, {2020: 1e9, 2024: 1.5e9}, kg=3e8, partners={10: 6e8, 11: 5e8, 12: 4e8}),
        _m(2, {2020: 1e8, 2024: 0.9e8}, kg=1e7, partners={10: 0.9e8}),
        _m(3, {2024: 5e8}),  # one year, no weight, no partners
    ]
    a = score_markets(markets)
    b = score_markets(markets)
    assert [r.score for r in a] == [r.score for r in b]
    assert all(0 <= r.score <= 100 for r in a)
    assert a[0].m49 == 1  # biggest, growing, diversified

    top = a[0].components
    assert set(top) == set(DEFAULT_WEIGHTS)
    assert top["openness"]["value"] == pytest.approx(1 - hhi([6e8, 5e8, 4e8]))
    assert top["market_size"]["period"] == "2024"

    third = next(r for r in a if r.m49 == 3)
    assert third.components["growth"]["status"] == "unavailable"
    assert third.components["openness"]["status"] == "unavailable"
    assert third.components["price_level"]["status"] == "unavailable"
    # available weights renormalised, so the score is still on 0-100
    used = sum(c["weight"] for c in third.components.values() if c["status"] == "ok")
    expected = 100 * sum(c["weight"] * c["normalized"] for c in third.components.values() if c["status"] == "ok") / used
    assert third.score == pytest.approx(expected, abs=0.01)


def test_custom_weights_change_ranking():
    markets = [_m(1, {2020: 1e9, 2024: 1e9}), _m(2, {2020: 1e7, 2024: 4e7})]
    by_size = score_markets(
        markets, {"market_size": 1, "growth": 0, "openness": 0, "price_level": 0, "data_quality": 0}
    )
    by_growth = score_markets(
        markets, {"market_size": 0, "growth": 1, "openness": 0, "price_level": 0, "data_quality": 0}
    )
    assert by_size[0].m49 == 1 and by_growth[0].m49 == 2


def test_no_nan_leaks():
    rows = score_markets([_m(1, {2024: 1.0}), _m(2, {2024: 1.0})])
    for r in rows:
        assert not math.isnan(r.score)
