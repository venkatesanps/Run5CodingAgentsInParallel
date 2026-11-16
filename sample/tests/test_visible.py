"""Four easy examples. The spec in SPEC.md is the real contract."""
import pytest

from money import parse_inr


def test_rupee_symbol():
    assert parse_inr("₹750") == 75000


def test_rs_with_comma():
    assert parse_inr("Rs. 2,500") == 250000


def test_inr_with_paise():
    assert parse_inr("INR 49.99") == 4999


def test_garbage_is_rejected():
    with pytest.raises(ValueError):
        parse_inr("hello")
