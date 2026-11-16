"""One coding agent: an LLM in a loop with one tool, the visible test suite.

Each round: ask the model for money.py, write it into the lane's worktree, run the
visible tests, and show the model the results. Stop when they all pass or the
round budget runs out. The lane never sees the hidden tests or another lane.
"""
import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import config, judge
from .config import Lane

SYSTEM_PROMPT = """You are a careful Python engineer. Several engineers are solving \
this same task independently; only the most correct solution is kept.

Write money.py so that parse_inr follows SPEC.md exactly. The visible tests are \
just examples. Other tests you will never see check every rule in the spec, \
including the edge cases, so code against the spec, not the examples.

Reply with the COMPLETE contents of money.py in ONE ```python code block.
Standard library only. Keep the module docstring to one line; do not paste the \
spec into the file. Nothing outside the code block."""

CODE_BLOCK = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.S)


@dataclass
class LaneResult:
    lane: str
    rounds: int = 0
    tokens: int = 0
    first_write_s: float | None = None
    visible_passed: int = 0
    visible_total: int = 0
    rate_limited: int = 0
    error: str | None = None


def extract_code(reply: str) -> str | None:
    """The last fenced code block in a reply, or None."""
    blocks = CODE_BLOCK.findall(reply or "")
    return blocks[-1].strip() + "\n" if blocks else None


def first_prompt(path: Path) -> str:
    spec = (path / config.SPEC_FILE).read_text(encoding="utf-8")
    stub = (path / config.TARGET_FILE).read_text(encoding="utf-8")
    tests = (path / config.VISIBLE_TESTS).read_text(encoding="utf-8")
    return (
        f"SPEC.md:\n{spec}\n\n"
        f"Current {config.TARGET_FILE}:\n```python\n{stub}```\n\n"
        f"Visible tests ({config.VISIBLE_TESTS.as_posix()}):\n```python\n{tests}```"
    )


def _retry_after(error, attempt: int) -> float:
    """How long to wait after a 429: Groq's retry-after header, else exponential backoff."""
    try:
        return min(float(error.response.headers.get("retry-after")), 30.0)
    except (AttributeError, TypeError, ValueError):
        return min(2.0 ** attempt, 30.0)


async def _complete(client, lane: Lane, messages: list[dict], result: LaneResult, log):
    """One model call, retrying rate-limit refusals ourselves so we can count them."""
    from groq import RateLimitError
    for attempt in range(config.RATE_LIMIT_RETRIES + 1):
        try:
            return await client.chat.completions.create(
                model=lane.model,
                messages=messages,
                temperature=lane.temperature,
                reasoning_effort=lane.effort,
                max_completion_tokens=config.MAX_COMPLETION_TOKENS,
            )
        except RateLimitError as e:
            if attempt == config.RATE_LIMIT_RETRIES:
                raise
            wait = _retry_after(e, attempt)
            result.rate_limited += 1
            log(f"{lane.name} rate-limited (429), retrying in {wait:.1f}s")  # FREE TIER: drop on paid
            await asyncio.sleep(wait)


async def run_lane(lane: Lane, path: Path, client, start: float, log) -> LaneResult:
    """Run one agent to completion inside its own worktree. Never raises."""
    result = LaneResult(lane.name)
    target = path / config.TARGET_FILE
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": first_prompt(path)},
    ]
    try:
        while result.rounds < config.MAX_ROUNDS:
            result.rounds += 1
            response = await _complete(client, lane, messages, result, log)
            choice = response.choices[0]
            reply = choice.message.content or ""
            result.tokens += getattr(response.usage, "total_tokens", 0) or 0
            messages.append({"role": "assistant", "content": reply})

            code = extract_code(reply)
            if code is None:
                cut_off = choice.finish_reason == "length"
                messages.append({"role": "user", "content": (
                    "Your reply was cut off. Send a shorter but complete money.py"
                    if cut_off else "No code block found. Reply with the complete money.py"
                ) + " in one ```python block."})
                log(f"{lane.name} round {result.rounds}: no code, nudged")
                continue

            target.write_text(code, encoding="utf-8")
            if result.first_write_s is None:
                result.first_write_s = time.monotonic() - start
            suite = await asyncio.to_thread(judge.run_suite, path, path / config.VISIBLE_TESTS)
            result.visible_passed, result.visible_total = suite.passed, suite.total
            log(f"{lane.name} round {result.rounds}: wrote {config.TARGET_FILE}, "
                f"visible {suite.passed}/{suite.total}")
            if suite.all_passed:
                break
            messages.append({"role": "user", "content": (
                f"Visible tests: {suite.passed}/{suite.total} passed.\n\n"
                f"{suite.output[-2000:]}\n\nFix money.py and reply with the complete file."
            )})
    except Exception as e:  # one broken lane must not stop the other four
        result.error = f"{type(e).__name__}: {e}"[:300]
        log(f"{lane.name} stopped: {result.error}")
    return result
