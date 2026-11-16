"""The judge's suite. It lives outside the target repo; no lane is shown it.

Every case comes straight from a rule in sample/SPEC.md. The visible tests
cover four easy ones; these cover the rest.
"""
import pytest

from money import parse_inr

VALID = {
    "indian-commas":   ("₹1,25,000.50", 12500050),
    "float-trap":      ("0.29", 29),              # 0.29 * 100 == 28.999... as a float
    "float-trap-2":    ("Rs 1.15", 115),          # 1.15 * 100 == 114.999...
    "lakh":            ("1.2 lakh", 12000000),
    "crores-plural":   ("3 Crores", 3000000000),
    "cr-no-space":     ("2.5cr", 2500000000),
    "suffix-decimals": ("1.2345 lakh", 12345000),
    "k-suffix":        ("Rs 5 K", 500000),
    "odd-commas":      ("1,2,3", 12300),          # rule 3: any grouping
    "paren-negative":  ("(₹200)", -20000),
    "minus-negative":  ("-Rs 15", -1500),
    "whitespace-case": ("  inr7  ", 700),
}

INVALID = {
    "3-decimals":       "₹12.345",
    "empty":            "",
    "two-points":       "1.2.3",
    "suffix-only":      "₹ lakh",
    "exponent":         "₹1e5",                  # float() accepts it; the spec doesn't
    "unbalanced-paren": "(200",
    "marker-after":     "500 INR",               # markers only go before the number
    "fraction-of-paisa": "1.234567 k",           # 1234.567 rupees is 123456.7 paise
}


@pytest.mark.parametrize("text, paise", VALID.values(), ids=VALID.keys())
def test_valid(text, paise):
    assert parse_inr(text) == paise


@pytest.mark.parametrize("text", INVALID.values(), ids=INVALID.keys())
def test_invalid(text):
    with pytest.raises(ValueError):
        parse_inr(text)
