---
name: parallel-agent-bakeoff
description: Run the same coding task with several agents in parallel git worktrees, judge every attempt with hidden tests the agents never saw, and merge only the best one. Use for "best of N", "run 5 agents and keep the best", "bake-off", or when one agent's answer to a well-specified, testable change is too risky to trust.
---

# Parallel agent bake-off (best-of-N with a hidden-test judge)

One agent is a sample from a distribution: it usually passes the tests it can see
and sometimes misses an edge case nobody showed it. Running N agents on the same
task, each in its own git worktree, and letting **tests they never saw** pick the
winner turns that guess into a choice.

```
task (spec + visible tests, committed) -> N worktrees -> N agents in parallel
  -> judge: visible + HIDDEN tests per lane -> rank -> merge winner -> delete the rest
```

## When it fits

- The change has a clear spec and can be checked by tests (a function, a parser,
  a bug fix with a reproducible case, a small module).
- Correctness matters more than tokens: N lanes cost about N times one attempt.
- Not for open-ended design work, big refactors with no tests, or anything where
  "correct" is a matter of taste. Say so and suggest a single agent instead.

## Before you start: the three artifacts

1. **Spec**: the rules, written down in the repo (e.g. `SPEC.md` or the issue text
   in a file). The spec is the contract; every hidden test must follow from it.
2. **Visible tests**: a few easy examples, committed in the repo. Lanes run them.
3. **Hidden tests**: the judge's suite, stored **outside** the repo (for example
   `~/.bakeoff/<task>/hidden/`). If the user has none, write them yourself from
   the spec **before** any lane starts, show them to the user, and keep them out
   of every lane prompt. Cover each rule and its edge cases; no tricks the spec
   doesn't state.

Commit the spec, stub and visible tests on the base branch. The repo must be clean.

## Steps

The helper script is `scripts/bakeoff.py` in this skill's folder (stdlib only;
needs git >= 2.28 and pytest). Below, `$BAKEOFF` is its path.

### 1. Create the lanes

```bash
python $BAKEOFF lanes --repo . --n 5
```

This makes `<repo>.bakeoff/lane-1..5` next to the repo, each a worktree on its own
branch `bakeoff/lane-N` from the current commit, and prints the paths.

### 2. Run the lanes in parallel

Start all N `bakeoff-lane` subagents **in one message** so they run at the same
time (if the `bakeoff-lane` agent isn't installed, use a general-purpose agent
with the same brief). Each prompt contains only:

- its worktree path and branch, and that it must work only inside that folder
- where the spec is and the exact visible-test command, e.g.
  `cd <lane path> && python -m pytest tests -q`
- its **diversity directive** (below)
- "commit your work on your branch when done; report what you changed and the
  visible test result"

Never mention the hidden tests, their path, or the other lanes.

**Diversity is the point.** N identical lanes fail on the same inputs. Give each
lane a different angle, and a different model where the platform allows it:

| Lane | Directive |
|---|---|
| 1 | Minimal: the smallest correct change that satisfies the spec. |
| 2 | Spec-first: list every rule and edge case from the spec as a checklist before coding; add your own tests for each. |
| 3 | Adversarial: after it works, try to break it with inputs the spec forbids or allows at the edges, then fix. |
| 4 | Different approach: solve it a way you would not normally choose first (e.g. a parser instead of a regex). |
| 5 | Fast model / low effort: a cheap baseline that sets the bar. |

### 3. Judge

```bash
python $BAKEOFF judge --repo . --hidden /abs/path/to/hidden --visible tests
```

It commits anything a lane left uncommitted, runs the visible and hidden suites
against each lane folder (each lane's folder is put on `PYTHONPATH`; use
`--import-dir src` if the code lives under `src/`), and ranks by:

1. passes its visible tests (otherwise it can't win),
2. most hidden tests passed,
3. smallest diff against the base commit (easier to review),
4. lane name.

The scoreboard is printed and saved to `<repo>.bakeoff/bakeoff.json`.

### 4. Report, then merge

Show the user the scoreboard and which hidden cases each loser missed (that
list is often the most useful output: it shows which rules are easy to get
wrong). Then, unless the user already said to merge automatically, ask before
merging into their branch:

```bash
python $BAKEOFF merge --repo .          # merges the judged winner with --no-ff
python $BAKEOFF cleanup --repo .        # removes every lane worktree and branch
```

If no lane is eligible, merge nothing, report the most common hidden failures,
and suggest tightening the spec or running again.

## Rules

- Hidden tests never enter a lane prompt, a lane folder, or the repo. The script
  refuses to judge with hidden tests inside the repo or lane folders.
- Only the judge decides. Don't merge a lane because its explanation sounds
  better; an LLM opinion is only a tie-breaker for things tests can't measure.
- Lanes run code on this machine. "Never sees the hidden tests" holds for what
  an agent is told, not for code it executes: a determined agent could search
  the disk. For untrusted code or real secrets, run each lane in a container or
  sandbox with only its own folder mounted.
- Keep the user's base branch clean: lanes branch from a commit, and only the
  merge touches the base branch.

## Self-contained demo

The repo this skill ships in also has a stand-alone Python race (`src/`) with
five Groq lanes, and an offline mode that needs no key:
`PYTHONPATH=. uv run python -m src.main race --fake`.
