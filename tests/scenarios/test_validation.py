import pytest

from scenarios.validation import validate_field_value

_LAYOUT = {
    "fields": [
        {"id": "wet_fr", "range": [0.0, 1.0]},
        {"id": "wet_nsa", "range": [0.0, None]},
    ]
}


def test_validate_field_value_accepts_in_range_value() -> None:
    validate_field_value("wet_fr", 0.5, _LAYOUT)  # no exception


def test_validate_field_value_rejects_below_minimum() -> None:
    with pytest.raises(ValueError, match="wet_fr"):
        validate_field_value("wet_fr", -0.1, _LAYOUT)


def test_validate_field_value_rejects_above_maximum() -> None:
    with pytest.raises(ValueError, match="wet_fr"):
        validate_field_value("wet_fr", 1.5, _LAYOUT)


def test_validate_field_value_allows_unbounded_maximum() -> None:
    validate_field_value("wet_nsa", 1_000_000.0, _LAYOUT)  # no exception


def test_validate_field_value_rejects_unknown_field() -> None:
    with pytest.raises(KeyError):
        validate_field_value("not_a_field", 1.0, _LAYOUT)
