import pytest

from openbim_qa.normalize import normalize_id, normalize_rating


@pytest.mark.parametrize("raw,unit,minutes", [
    (60, "minutes", 60), (60.0, "minutes", 60), ("60", "minutes", 60),
    ("60 min", "hours", 60), ("60 MINUTES", "minutes", 60), ("1 hr", "minutes", 60),
    ("1.5 h", "minutes", 90), (".5 hours", "minutes", 30), ("1", "hours", 60),
    (" 90mins ", "minutes", 90), ("0", "minutes", 0), ("0.1 h", "minutes", 6),
])
def test_explicit_duration(raw, unit, minutes):
    rating = normalize_rating(raw, unit)
    assert (rating.state, rating.minutes) == ("ok", minutes)


@pytest.mark.parametrize("raw", [None, "", " \t\r\n"])
def test_missing_stays_missing(raw):
    assert normalize_rating(raw).state == "missing"
    assert normalize_rating(raw).minutes is None


@pytest.mark.parametrize("raw", [
    "FD60", "EI60", "N/A", "unrated", "60/90", "1 hr 30 min", "1 hr = 60 min", "1/2 h",
    "-60", "+60", "1e2", "1,5 h", "60 seconds", "1.5 min", "0.333 h", "NaN", "Infinity",
    True, False, [], {"value": 60}, float("nan"), float("inf"), "1" * 129,
    # Decimal context rounding must never erase the fraction and create PASS.
    "1.0000000000000000000000000000000001 h",
])
def test_unsupported_never_has_minutes(raw):
    result = normalize_rating(raw)
    assert result.state == "unsupported"
    assert result.minutes is None


def test_numeric_unit_is_not_guessed():
    with pytest.raises(ValueError):
        normalize_rating("60", "seconds")


@pytest.mark.parametrize("raw,expected", [(" 001 ", "001"), ("D-a", "D-a"), ("", None), (None, None), (1, None), (" \t", None)])
def test_conservative_ids(raw, expected):
    assert normalize_id(raw) == expected
