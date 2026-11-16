"""Every setting for the bake-off, in one place.

Reads:   .env (GROQ_API_KEY).
Exposes: folder paths, the five lane specs, and the limits the other modules use.
"""
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # full path, so it works from any working directory

SAMPLE_DIR = ROOT / "sample"            # the starting code every race copies
HIDDEN_TESTS = ROOT / "hidden_tests"    # the judge's suite; never copied into the repo
WORKDIR = ROOT / "workdir"              # rebuilt on every race
REPO = WORKDIR / "repo"                 # the target repo, branch main
LANES_DIR = WORKDIR / "lanes"           # one git worktree per lane

TARGET_FILE = "money.py"                # the only file a lane is asked to write
SPEC_FILE = "SPEC.md"
VISIBLE_TESTS = Path("tests") / "test_visible.py"   # relative to a lane folder
HIDDEN_TEST_FILE = HIDDEN_TESTS / "test_hidden.py"


@dataclass(frozen=True)
class Lane:
    """One competitor: a model plus the settings that make it think differently."""
    name: str
    model: str
    temperature: float
    effort: str  # gpt-oss reasoning effort: "low" is quick, "medium" thinks longer


# Lanes must differ, or they fail on the same inputs and the judge has nothing
# to choose between. Mix model size, randomness and thinking budget.
# FREE TIER: each Groq model has its own small tokens-per-minute bucket, so the
# lanes are spread over two models. On a paid key, use your strongest model(s).
LANES = [
    Lane("lane-1", "openai/gpt-oss-120b", 0.2, "medium"),
    Lane("lane-2", "openai/gpt-oss-120b", 0.8, "medium"),
    Lane("lane-3", "openai/gpt-oss-120b", 1.0, "low"),
    Lane("lane-4", "openai/gpt-oss-20b", 0.3, "low"),
    Lane("lane-5", "openai/gpt-oss-20b", 1.0, "low"),
]

# FREE TIER: few rounds and a modest reply budget keep five lanes under the
# per-minute token limit. On a paid key, raise both.
MAX_ROUNDS = 4                 # model calls per lane
MAX_COMPLETION_TOKENS = 4000   # per reply, reasoning included
RATE_LIMIT_RETRIES = 6         # 429s are routine on the free tier
TEST_TIMEOUT_S = 30            # an infinite loop in a lane can't hang the race
