# Run 5 Coding Agents in Parallel and Keep the Best One

Give one coding task to five AI agents at once. Each works in its own git
worktree, so none can overwrite another. When they finish, a judge runs a
**hidden** test suite the agents never saw against every attempt, merges the
winner into `main`, and deletes the other four.

```
                 ┌─ lane-1 worktree ─┐
SPEC.md + stub ──┼─ lane-2 worktree ─┼──> judge: visible + hidden tests ──> main: winner merged
+ visible tests  ├─ lane-3 worktree ─┤                                     (others deleted)
                 ├─ lane-4 worktree ─┤
                 └─ lane-5 worktree ─┘
```

Inspired by the datasciencebrain post
[*Run 5 Coding Agents in Parallel and Keep the Best One*](https://www.instagram.com/datasciencebrain/).
This repo is an independent, complete implementation of that idea.

## What's in the box

| Path | What it is |
|---|---|
| `src/` | The race: config, git plumbing, judge, one agent loop, CLI (~550 lines) |
| `sample/` | The task every race starts from: `SPEC.md`, a `parse_inr` stub, 4 visible tests |
| `hidden_tests/` | The judge's 20-case suite, kept outside the agents' repo |
| `src/fake.py` | Scripted offline "models" so you can run a full race with no API key |
| `tests/` | Tests for the harness itself (offline, run in CI on Linux/macOS/Windows) |
| `.claude/skills/parallel-agent-bakeoff/` | A Claude Code skill: the same best-of-N on **any** repo, with Claude subagents as lanes |
| `.claude/agents/bakeoff-lane.md` | The subagent each lane runs as |
| `docs/GUIDE.md` | How it works, step by step, plus errors, caveats and next steps |

## Quick start

Needs Python 3.12+, [uv](https://docs.astral.sh/uv/), and git 2.28+.

```bash
git clone https://github.com/venkatesanps/Run5CodingAgentsInParallel
cd Run5CodingAgentsInParallel
uv sync

# 1. Offline: watch a whole race with scripted lanes (no key needed)
PYTHONPATH=. uv run python -m src.main race --fake

# 2. For real: free Groq key from console.groq.com/keys
cp .env.example .env        # then put your key in .env
PYTHONPATH=. uv run python -m src.main race
```

On Windows PowerShell, run `$env:PYTHONPATH = "."` once per terminal and drop
the `PYTHONPATH=.` prefix.

Sample offline result:

```
rank lane     visible  hidden  diff rounds  tokens  hidden failures
1    lane-3      4/4    20/20    33      2    2569  -
2    lane-4      4/4    20/20    33      1    1285  -
3    lane-1      4/4    20/20    46      1    1401  -
4    lane-2      4/4    19/20    35      1    1337  odd-commas
5    lane-5      4/4    17/20    31      1    1251  float-trap, float-trap-2, fraction-of-paisa
```

Every lane passed the tests it could see. Two were still wrong. That's why the
judge exists.

## Commands

```bash
PYTHONPATH=. uv run python -m src.main race [--fake] [--lanes N] [--keep]
PYTHONPATH=. uv run python -m src.main judge [--merge]   # after race --keep
PYTHONPATH=. uv run python -m src.main clean
PYTHONPATH=. uv run pytest                               # harness self-tests
```

## The five lanes

Lanes differ on purpose; identical lanes fail on the same inputs.

| Lane | Model | Temperature | Reasoning effort |
|---|---|---|---|
| lane-1 | gpt-oss-120b | 0.2 | medium |
| lane-2 | gpt-oss-120b | 0.8 | medium |
| lane-3 | gpt-oss-120b | 1.0 | low |
| lane-4 | gpt-oss-20b | 0.3 | low |
| lane-5 | gpt-oss-20b | 1.0 | low |

Free-tier limits shape the defaults in `src/config.py` (4 rounds, 4,000-token
replies, 6 rate-limit retries). On a paid key, raise them and put every lane on
your strongest model.

## Use it on your own code: the Claude Code skill

`.claude/skills/parallel-agent-bakeoff` runs the same pattern on any git repo,
with Claude Code subagents as the lanes:

1. Commit a spec, a stub and a few visible tests. Put hidden tests **outside** the repo.
2. Ask Claude Code: *"Run a 5-lane bake-off on this task."*
3. The skill creates the worktrees (`scripts/bakeoff.py lanes`), starts five
   `bakeoff-lane` subagents in parallel with different approaches, judges them
   (`bakeoff.py judge --hidden ...`), shows the scoreboard, and merges the winner
   when you say so.

To use it in another project, copy `.claude/skills/parallel-agent-bakeoff/` and
`.claude/agents/bakeoff-lane.md` into that project's `.claude/` (or into
`~/.claude/` for every project).

## Read before using at work

Lanes are told nothing about the hidden tests, but the code they write runs on
your machine. Use containers for untrusted code, keep secrets out of the lane
repo, and remember every lane sends your spec and code to the model provider.
See `docs/GUIDE.md` section 15.
