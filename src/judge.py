"""The judge: run both test suites against every lane's folder and rank the lanes.

Reads:   each lane's worktree, sample-derived visible tests, hidden_tests/.
Returns: one Score per lane, best first. It never reads the agents' conversations.
"""
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from . import config, repo


@dataclass
class SuiteResult:
    passed: int
    total: int
    failed: list[str] = field(default_factory=list)   # test ids, e.g. "float-trap"
    output: str = ""                                    # pytest's text, for feeding back to a lane

    @property
    def all_passed(self) -> bool:
        return self.total > 0 and self.passed == self.total


@dataclass
class Score:
    lane: str
    visible: SuiteResult
    hidden: SuiteResult
    diff_lines: int

    @property
    def eligible(self) -> bool:
        """Only an attempt that passes its own visible tests may be merged."""
        return self.visible.all_passed

    def sort_key(self):
        # More hidden passes first, then visible passes, then the smaller change.
        return (-self.hidden.passed, -self.visible.passed, self.diff_lines, self.lane)


def _test_id(name: str) -> str:
    """'test_valid[float-trap]' -> 'float-trap'; 'test_rupee_symbol' stays as is."""
    return name[name.index("[") + 1:-1] if "[" in name else name


def _pytest(code_dir: Path, test_file: Path, *extra: str, timeout: float):
    """Run pytest on one test file with code_dir importable. Returns (process, junit xml text)."""
    env = {
        **os.environ,
        "PYTHONPATH": str(code_dir),          # so `from money import parse_inr` finds this lane's file
        "PYTHONDONTWRITEBYTECODE": "1",       # keep caches out of hidden_tests/
    }
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.xml"
        cmd = [
            sys.executable, "-m", "pytest", str(test_file), "-q",
            "-p", "no:cacheprovider", f"--rootdir={code_dir}",
            f"--junitxml={report}", *extra,
        ]
        done = subprocess.run(cmd, cwd=code_dir, env=env, capture_output=True,
                              text=True, encoding="utf-8", timeout=timeout)
        return done, report.read_text(encoding="utf-8") if report.exists() else ""


@cache
def expected_total(test_file: Path) -> int:
    """How many tests a suite holds, counted against the untouched stub.

    A lane whose money.py has a syntax error makes pytest report one collection
    error instead of N tests, so the denominator must come from somewhere stable.
    """
    done, _ = _pytest(config.SAMPLE_DIR, test_file, "--collect-only", timeout=60)
    return sum(1 for line in done.stdout.splitlines() if "::" in line)


def run_suite(code_dir: Path, test_file: Path) -> SuiteResult:
    """Run one test file against the code in code_dir."""
    total = expected_total(test_file)
    try:
        done, xml = _pytest(code_dir, test_file, timeout=config.TEST_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return SuiteResult(0, total, ["timeout"], f"Tests did not finish within {config.TEST_TIMEOUT_S}s.")

    passed, failed = 0, []
    if xml:
        for case in ET.fromstring(xml).iter("testcase"):
            if len(case):                     # a <failure>, <error> or <skipped> child
                failed.append(_test_id(case.get("name", "?")))
            else:
                passed += 1
    if passed == 0 and not failed:
        failed = ["collection-error"]
    return SuiteResult(passed, total, failed, (done.stdout + done.stderr).strip())


def score_lane(lane: str) -> Score:
    path = config.LANES_DIR / lane
    return Score(
        lane=lane,
        visible=run_suite(path, path / config.VISIBLE_TESTS),
        hidden=run_suite(path, config.HIDDEN_TEST_FILE),
        diff_lines=repo.diff_size(lane),
    )


def judge(lanes: list[str]) -> list[Score]:
    """Score every lane (in parallel; each run is its own pytest process) and rank them."""
    with ThreadPoolExecutor(max_workers=len(lanes) or 1) as pool:
        scores = list(pool.map(score_lane, lanes))
    return sorted(scores, key=Score.sort_key)


def pick_winner(scores: list[Score]) -> Score | None:
    """The best eligible lane, or None if no lane passed its own visible tests."""
    return next((s for s in scores if s.eligible), None)
