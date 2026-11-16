"""An offline stand-in for Groq, so you can watch a whole race without an API key.

`race --fake` gives each lane a scripted "model" that replies with a canned
money.py. The scripts are chosen to make the judge's job visible: one lane is
correct and short, one correct but long, one forgets odd comma grouping, one
uses floats, and one fails a visible test first and fixes it in round 2.
One lane also gets a simulated 429 so the retry path runs.
"""
import asyncio
import random
from types import SimpleNamespace

import httpx
from groq import RateLimitError

CORRECT = '''"""Parse Indian rupee amounts (rules in SPEC.md)."""
import re
from decimal import Decimal

_AMOUNT = re.compile(
    r"(?:(?:₹|rs\\.?|inr)\\s*)?([0-9](?:,?[0-9])*)(?:\\.([0-9]+))?\\s*([a-z]+)?",
    re.IGNORECASE,
)
_SCALE = {"k": 10**3, "l": 10**5, "lakh": 10**5, "lakhs": 10**5,
          "cr": 10**7, "crore": 10**7, "crores": 10**7}


def parse_inr(text: str) -> int:
    s = text.strip()
    sign = 1
    if s.startswith("(") and s.endswith(")"):
        s, sign = s[1:-1].strip(), -1
    elif s.startswith("-"):
        s, sign = s[1:].strip(), -1
    m = _AMOUNT.fullmatch(s)
    if not m:
        raise ValueError(f"not a rupee amount: {text!r}")
    whole, frac, suffix = m.groups()
    scale = 1
    if suffix:
        if suffix.lower() not in _SCALE:
            raise ValueError(f"unknown suffix: {suffix!r}")
        scale = _SCALE[suffix.lower()]
    elif frac and len(frac) > 2:
        raise ValueError("more than two decimal places")
    paise = Decimal(whole.replace(",", "") + "." + (frac or "0")) * scale * 100
    if paise != paise.to_integral_value():
        raise ValueError("not a whole number of paise")
    return sign * int(paise)
'''

# Same logic, padded with the kind of ceremony that loses a tie-break.
VERBOSE = CORRECT.replace(
    "def parse_inr(text: str) -> int:\n",
    "def _clean(text: str) -> str:\n"
    "    \"\"\"Trim surrounding whitespace.\"\"\"\n"
    "    if not isinstance(text, str):\n"
    "        raise ValueError(\"text must be a string\")\n"
    "    return text.strip()\n\n\n"
    "def _is_wrapped(s: str) -> bool:\n"
    "    \"\"\"True when the whole amount sits inside parentheses.\"\"\"\n"
    "    return s.startswith(\"(\") and s.endswith(\")\")\n\n\n"
    "def parse_inr(text: str) -> int:\n"
    "    text = _clean(text)\n",
)

# Validates comma grouping instead of ignoring commas: rejects "1,2,3".
STRICT_COMMAS = CORRECT.replace(
    '    whole, frac, suffix = m.groups()\n',
    '    whole, frac, suffix = m.groups()\n'
    '    if "," in whole and not re.fullmatch(r"[0-9]{1,3}(,[0-9]{2})*,[0-9]{3}|[0-9]{1,3}(,[0-9]{3})+", whole):\n'
    '        raise ValueError("bad digit grouping")\n',
)

# The classic money bug: float arithmetic, then int() truncates 28.999... to 28.
FLOATS = CORRECT.replace(
    '    paise = Decimal(whole.replace(",", "") + "." + (frac or "0")) * scale * 100\n'
    '    if paise != paise.to_integral_value():\n'
    '        raise ValueError("not a whole number of paise")\n'
    '    return sign * int(paise)\n',
    '    paise = float(whole.replace(",", "") + "." + (frac or "0")) * scale * 100\n'
    '    return sign * int(paise)\n',
)

# Round 1 forgets the "Rs." marker (fails a visible test); round 2 is correct.
NO_RS_DOT = CORRECT.replace("rs\\.?", "rs")
assert NO_RS_DOT != CORRECT and STRICT_COMMAS != CORRECT and FLOATS != CORRECT and VERBOSE != CORRECT


def _reply(code: str) -> str:
    return f"Here is the file.\n\n```python\n{code}```"


SCRIPTS = {
    "lane-1": [VERBOSE],
    "lane-2": [STRICT_COMMAS],
    "lane-3": [NO_RS_DOT, CORRECT],
    "lane-4": [CORRECT],
    "lane-5": [FLOATS],
}


class _Completions:
    def __init__(self, lane: str, rate_limit_once: bool):
        self.replies = list(SCRIPTS.get(lane, [CORRECT]))
        self.rate_limit_once = rate_limit_once

    async def create(self, **_kwargs):
        await asyncio.sleep(random.uniform(0.2, 1.0))     # pretend to think
        if self.rate_limit_once:
            self.rate_limit_once = False
            response = httpx.Response(429, headers={"retry-after": "0.5"},
                                      request=httpx.Request("POST", "https://fake.local"))
            raise RateLimitError("fake 429: tokens per minute", response=response, body=None)
        code = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=_reply(code)),
                                     finish_reason="stop")],
            usage=SimpleNamespace(total_tokens=len(code) // 3 + 900),
        )


class FakeClient:
    """Quacks like AsyncGroq for the one method a lane calls."""
    def __init__(self, lane: str):
        self.chat = SimpleNamespace(completions=_Completions(lane, rate_limit_once=lane == "lane-2"))
