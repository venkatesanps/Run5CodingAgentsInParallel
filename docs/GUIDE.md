# How the bake-off works

This picks up where the free preview of the original post stops (partway through
"Worktrees: One Repo, Five Folders") and covers the rest: the lane lifecycle in
git, the judge, one coding agent, the command line, a full run, common errors,
what to watch out for at work, and what to build next.

All code referred to here is in `src/`. Run every command from the repo root.

---

## 9 (continued). A lane's lifecycle in git

Every lane goes through the same four steps, all in `src/repo.py`:

| Step | Function | Git underneath |
|---|---|---|
| Get a folder | `add_worktree(lane)` | `git worktree add -b lane-N workdir/lanes/lane-N main` |
| Save its work | `commit_all(path, msg)` | `git add -A` + `git commit` inside the worktree |
| Measure its change | `diff_size(lane)` | `git diff --numstat main...lane-N` |
| Keep or throw away | `merge(lane)` / `discard(lane)` | `git merge --no-ff` / `git worktree remove --force` + `git branch -D` |

`git diff --numstat` prints one line per changed file: lines added, lines
removed, file name. Binary files show `-` instead of numbers and are skipped.
The three dots in `main...lane-3` mean "what changed on `lane-3` since it
branched off `main`", so the size stays correct even after `main` moves on.

`merge` uses `--no-ff` so `main` always gets a merge commit named
`bake-off winner: lane-N`. `git log --graph` then shows exactly which lane won
each race.

`git()` takes an optional `cwd` and falls back to `config.REPO` **at call time**.
(A default of `cwd=config.REPO` in the signature would be frozen when the module
is imported, and tests couldn't point the race at a temporary folder.)

---

## 10. The judge

`src/judge.py` answers one question per lane: how many visible tests and how many
hidden tests does this folder pass?

### Running pytest against one lane

`run_suite(code_dir, test_file)` starts a fresh `python -m pytest` process with:

- `cwd` = the lane folder and `PYTHONPATH` = the lane folder, so
  `from money import parse_inr` imports *that lane's* file, even for the hidden
  suite that lives elsewhere;
- `--junitxml=<temp file>`: pytest writes one `<testcase>` per test, with a
  `<failure>` or `<error>` child when it didn't pass. Parsing that XML is far
  more reliable than scraping the terminal output;
- `-p no:cacheprovider` and `PYTHONDONTWRITEBYTECODE=1`, so no `.pytest_cache`
  or `__pycache__` lands in `hidden_tests/` or gets committed in a lane;
- `timeout=TEST_TIMEOUT_S`: an attempt with an infinite loop scores 0 instead of
  hanging the race.

Each lane runs in its own process, so five lanes can be judged at once
(`ThreadPoolExecutor`) without one attempt's imports leaking into another's.

### A stable denominator

If a lane's `money.py` has a syntax error, pytest reports one collection error
instead of 20 failed tests, and the scoreboard would read `0/1`.
`expected_total()` counts the tests once against the untouched stub (which
imports fine and only fails when called) and caches the number.

### Ranking

```python
def sort_key(self):
    return (-self.hidden.passed, -self.visible.passed, self.diff_lines, self.lane)
```

1. Most hidden tests passed: correctness against the contract.
2. Then most visible tests passed.
3. Then the smallest diff: two equally correct attempts, keep the one that's
   easier to review.
4. Then lane name, so the result is deterministic.

`pick_winner()` takes the best lane **that passes all its visible tests**. A lane
that fails the examples it was shown isn't merged, however it ranks. If no lane
qualifies, nothing is merged and `main` keeps the stub.

---

## 11. One coding agent

`src/lane.py` is the agent: an LLM in a loop with one tool, the visible test
suite.

```
round 1: send SPEC.md + stub + visible tests      -> model replies with money.py
         write it into the lane folder, run visible tests
round 2: send the pytest output                   -> model replies with a fix
...      stop when visible tests all pass, or after MAX_ROUNDS
```

Design choices that matter:

- **One file, one code block.** The model replies with the complete `money.py`
  in a fenced block, and `extract_code()` takes the last block. No tool-calling
  schema to get wrong, and a partial patch can't leave the file half-edited.
- **The prompt points at the spec, not the tests.** It says plainly that unseen
  tests check every rule. That is the honest framing, and it's what you'd tell a
  human contractor.
- **Nudges.** If a reply has no code block, the lane asks again. If the reply
  was cut off (`finish_reason == "length"`), it asks for a shorter complete file.
  This is why the spec lives in `SPEC.md` and the prompt says "keep the
  docstring to one line": models that paste the spec into the file run out of
  tokens before the code is finished.
- **Rate limits are expected.** The Groq client is created with
  `max_retries=0`, and `_complete()` retries `RateLimitError` itself, honouring
  the `retry-after` header and counting each refusal for the summary line.
- **A lane never raises.** Any exception is caught, recorded on the
  `LaneResult`, and logged; the other lanes carry on. One broken lane must not
  cancel a race the other four can still win.
- **Concurrency without threads.** All lanes share one `AsyncGroq` client.
  `asyncio.gather` runs the five loops in one process; while one lane waits on
  the network, another runs. The blocking pytest call goes through
  `asyncio.to_thread` so it doesn't freeze the event loop.

---

## 12. The command line

```bash
PYTHONPATH=. uv run python -m src.main race             # 5 Groq lanes, judge, merge
PYTHONPATH=. uv run python -m src.main race --fake      # scripted offline lanes, no key
PYTHONPATH=. uv run python -m src.main race --lanes 3   # fewer lanes, fewer tokens
PYTHONPATH=. uv run python -m src.main race --keep      # judge only; keep every worktree
PYTHONPATH=. uv run python -m src.main judge --merge    # re-judge kept lanes, then merge
PYTHONPATH=. uv run python -m src.main clean            # delete workdir/
```

`race` does, in order: `repo.setup()` → five `add_worktree()` calls → all lanes
via `asyncio.gather` → `commit_all()` per lane → `judge.judge()` → scoreboard →
`finish()`, which merges the winner and discards every lane.

`--keep` stops before the merge so you can open `workdir/lanes/lane-2/money.py`
and see *why* it lost. `judge --merge` finishes the job afterwards.

`--fake` swaps Groq for `src/fake.py`: five scripted "models" chosen to exercise
everything (a short correct answer, a long correct answer, one that validates
comma grouping instead of ignoring it, one that uses floats, and one that fails a
visible test and fixes it in round 2), plus one simulated 429.

---

## 13. Run it end to end

Offline first, to see the machinery:

```bash
PYTHONPATH=. uv run python -m src.main race --fake
```

```
[   0.2s] created 5 worktrees under .../workdir/lanes
[   0.9s] starting all lanes
[   1.2s] lane-2 rate-limited (429), retrying in 0.5s
[   3.9s] lane-4 round 1: wrote money.py, visible 4/4
[   4.1s] lane-1 round 1: wrote money.py, visible 4/4
[   4.6s] lane-3 round 1: wrote money.py, visible 3/4
[   4.7s] lane-5 round 1: wrote money.py, visible 4/4
[   4.7s] lane-2 round 1: wrote money.py, visible 4/4
[   5.6s] lane-3 round 2: wrote money.py, visible 4/4
[   6.1s] judging

rank lane     visible  hidden  diff rounds  tokens  hidden failures
1    lane-3      4/4    20/20    33      2    2569  -
2    lane-4      4/4    20/20    33      1    1285  -
3    lane-1      4/4    20/20    46      1    1401  -
4    lane-2      4/4    19/20    35      1    1337  odd-commas
5    lane-5      4/4    17/20    31      1    1251  float-trap, float-trap-2, fraction-of-paisa

Race took 10s, used 7,843 tokens, hit 1 rate-limit refusals.
Winner: lane-3, hidden 20/20, 33-line change (tie with lane-4, lane-1 broken by smallest diff, then lane name).
Merged into main as 04bf4ae in .../workdir/repo
```

Every lane passed every visible test, and two of them were still wrong. That
gap is the whole argument for the judge.

Then the real thing, with `GROQ_API_KEY` in `.env`:

```bash
PYTHONPATH=. uv run python -m src.main race
```

Expect one to three minutes and 30k–45k tokens on the free tier, with a handful
of 429 retries. Look at the result:

```bash
git -C workdir/repo log --oneline --graph
git -C workdir/repo show HEAD --stat
```

---

## 14. Common errors & fixes

| Symptom | Cause | Fix |
|---|---|---|
| `GROQ_API_KEY is not set` | `.env` missing, saved as `.env.txt`, or UTF-16 | Create `.env` in the repo root in VS Code, one line `GROQ_API_KEY=gsk_...` |
| `No module named 'src'` | `PYTHONPATH=.` missing (or ignored by PowerShell) | PowerShell: `$env:PYTHONPATH = "."` once per terminal |
| `git worktree add ... already exists` | A previous race crashed mid-way | `python -m src.main clean`, then race again |
| `error: unknown switch 'b'` on `git init` | git older than 2.28 | Upgrade git |
| `PermissionError` deleting `workdir` (Windows) | Python < 3.12, or an editor holds a file open | Use Python 3.12+; close files under `workdir/` |
| Many `rate-limited (429)` lines | Normal on the free tier | Ignore. If a lane stops with `RateLimitError`, run `--lanes 3` or wait a minute |
| Lanes stop with a 400 about `reasoning_effort` | Model doesn't accept that parameter | Use gpt-oss models, or drop `reasoning_effort` for other models |
| `model_not_found` / decommissioned | Groq retired the model | Update `LANES` in `src/config.py` from console.groq.com/docs/models |
| Every lane scores 20/20 every race | Task too easy for these settings | Good news for the task; add low-effort lanes or a harder spec to see the judge work |
| `hidden 0/20` with `collection-error` | Syntax error or missing `parse_inr` | `race --keep`, then open that lane's `money.py` |
| `UnicodeEncodeError` printing `₹` | Windows console code page | Set `PYTHONUTF8=1` |

---

## 15. Before you use this at work

- **"Never sees" is about prompts, not code.** Lanes can't read the hidden
  tests, but the code they write runs on your machine during testing and could,
  in principle, open `../../hidden_tests/`. With real models, real repos or
  untrusted output, run each lane's tests in a container that mounts only that
  lane's folder (and copy the hidden tests in only for the judge run).
- **Your code goes to a third party.** Every lane sends the spec, stub and tests
  to the model provider. Check your company's policy before pointing this at
  internal code, and never put secrets in the repo the lanes see.
- **Cost scales with N.** Five lanes cost about five attempts. Spend it on
  changes where a hidden bug is expensive, not on every edit.
- **The judge is only as good as the hidden suite.** If the spec is vague, the
  "winner" is whoever guessed your intent. Write the spec first, derive hidden
  tests from it, and have a second person review both.
- **Flaky tests pick random winners.** Make the suite deterministic (no network,
  no clock, no ordering assumptions) before trusting a ranking.
- **A human still reviews the merge.** The winner passed the tests you wrote;
  the merge commit is a normal change that goes through normal review/CI.

---

## 16. What you should remember

- One agent is a sample. Several agents plus a judge is a choice.
- Worktrees solve collisions: one repo, one history, one folder and one branch
  per lane.
- Tests the agents never saw solve choosing; tests the agents *did* see can't
  tell a correct attempt from a lucky one.
- Diversity (model, temperature, effort, approach) is what makes best-of-N beat
  a typical single run. Identical lanes fail together.
- Rank on facts (tests), break ties on reviewability (diff size), and never
  merge an attempt that fails its own visible tests.

---

## 17. What to build next

- **Containers per lane** so test runs can't see anything but their own folder.
- **Cross-vendor lanes**: Claude, GPT, Gemini and open models side by side. Their
  mistakes overlap less than two settings of one model. The Claude Code skill in
  `.claude/skills/parallel-agent-bakeoff` does this with Claude subagents today.
- **A pull request per winner** instead of a local merge, with the scoreboard in
  the PR description.
- **Early stopping**: end the race when one lane hits a perfect hidden score and
  the others are still on round 1, to save tokens.
- **An LLM tie-breaker** for lanes tied on tests: readability, naming, error
  messages. Opinions only after facts.
- **Mutation-test the hidden suite**: deliberately break the reference solution
  in small ways and check the suite catches each break. A suite that misses
  mutants will miss real bugs too.
- **Ensembles**: let the winner read the losers' diffs and the failing case
  names, then make one more attempt.
