"""Tests for the bake-off machinery itself. No API key or network needed.

    PYTHONPATH=. uv run pytest
"""
import asyncio
import shutil

import pytest

from src import config, fake, judge, lane, main, repo


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """Point the race at a throwaway workdir so tests never touch ./workdir."""
    monkeypatch.setattr(config, "WORKDIR", tmp_path / "workdir")
    monkeypatch.setattr(config, "REPO", tmp_path / "workdir" / "repo")
    monkeypatch.setattr(config, "LANES_DIR", tmp_path / "workdir" / "lanes")
    return tmp_path


def _scored(tmp_path, code: str) -> tuple[judge.SuiteResult, judge.SuiteResult]:
    folder = tmp_path / "attempt"
    shutil.copytree(config.SAMPLE_DIR, folder)
    (folder / config.TARGET_FILE).write_text(code, encoding="utf-8")
    return (judge.run_suite(folder, folder / config.VISIBLE_TESTS),
            judge.run_suite(folder, config.HIDDEN_TEST_FILE))


def test_suite_sizes():
    assert judge.expected_total(config.SAMPLE_DIR / config.VISIBLE_TESTS) == 4
    assert judge.expected_total(config.HIDDEN_TEST_FILE) == 20


def test_reference_solution_passes_everything(tmp_path):
    visible, hidden = _scored(tmp_path, fake.CORRECT)
    assert visible.all_passed and hidden.all_passed, hidden.failed


@pytest.mark.parametrize("code, expected_failures", [
    (fake.STRICT_COMMAS, {"odd-commas"}),
    (fake.FLOATS, {"float-trap", "float-trap-2", "fraction-of-paisa"}),
])
def test_hidden_suite_catches_known_bugs(tmp_path, code, expected_failures):
    visible, hidden = _scored(tmp_path, code)
    assert visible.all_passed                      # the bugs are invisible to the examples...
    assert set(hidden.failed) == expected_failures  # ...and caught by the judge


def test_stub_and_broken_code_score_zero(tmp_path):
    _, hidden = _scored(tmp_path, "def parse_inr(:\n")      # syntax error
    assert hidden.passed == 0 and hidden.total == 20


def test_extract_code_takes_last_block():
    reply = "draft:\n```python\nx = 1\n```\nfinal:\n```python\nx = 2\n```"
    assert lane.extract_code(reply) == "x = 2\n"
    assert lane.extract_code("no code here") is None


def test_ranking_prefers_hidden_then_smaller_diff():
    def s(name, hidden, diff, visible=4):
        return judge.Score(name, judge.SuiteResult(visible, 4), judge.SuiteResult(hidden, 20), diff)
    scores = sorted([s("a", 19, 10), s("b", 20, 50), s("c", 20, 30), s("d", 20, 5, visible=3)],
                    key=judge.Score.sort_key)
    assert [x.lane for x in scores] == ["c", "b", "d", "a"]
    assert judge.pick_winner(scores).lane == "c"


def test_fake_race_merges_a_perfect_lane_and_cleans_up(workdir, capsys):
    asyncio.run(main.race(config.LANES, fake=True, keep=False))
    out = capsys.readouterr().out
    assert "Winner: lane-3" in out and "odd-commas" in out
    assert repo.lane_names() == []                                 # every worktree removed
    assert repo.git("branch", "--format=%(refname:short)") == "main"
    merged = (config.REPO / config.TARGET_FILE).read_text(encoding="utf-8")
    assert merged == fake.CORRECT                                  # the winner's code is on main
    assert repo.git("log", "-1", "--format=%s").startswith("bake-off winner: lane-3")


def test_keep_then_rejudge(workdir, capsys):
    asyncio.run(main.race(config.LANES[:2], fake=True, keep=True))
    assert repo.lane_names() == ["lane-1", "lane-2"]
    scores = judge.judge(repo.lane_names())
    assert [x.lane for x in scores] == ["lane-1", "lane-2"]        # 20/20 beats 19/20


def test_lane_with_real_groq_sdk_over_mock_http(workdir):
    """The real AsyncGroq client, a mocked network: one 429, then a valid completion."""
    import json
    import time

    import httpx
    from groq import AsyncGroq

    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return httpx.Response(429, headers={"retry-after": "0.1"},
                                  json={"error": {"message": "rate limit", "type": "tokens"}})
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "openai/gpt-oss-20b",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": f"```python\n{fake.CORRECT}```"}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 400, "total_tokens": 1300},
        })

    client = AsyncGroq(api_key="test", max_retries=0,
                       http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    repo.setup()
    path = repo.add_worktree("lane-4")
    result = asyncio.run(lane.run_lane(config.LANES[3], path, client, time.monotonic(), print))

    assert result.error is None and result.rate_limited == 1
    assert (result.rounds, result.tokens, result.visible_passed) == (1, 1300, 4)
    body = sent[-1]
    assert body["model"] == "openai/gpt-oss-20b" and body["reasoning_effort"] == "low"
    assert body["max_completion_tokens"] == config.MAX_COMPLETION_TOKENS
    assert "SPEC.md" in body["messages"][1]["content"]
