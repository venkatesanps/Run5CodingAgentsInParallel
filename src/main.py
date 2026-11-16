"""Command line for the bake-off.

    python -m src.main race            five Groq lanes, judge, merge the winner
    python -m src.main race --fake     same race with scripted offline lanes (no key needed)
    python -m src.main race --keep     judge but don't merge; keep every worktree to inspect
    python -m src.main judge [--merge] re-score kept lanes, optionally merge the winner
    python -m src.main clean           delete workdir/

The race is one Python process: asyncio runs the five lane loops side by side,
and only the git history in workdir/repo outlives it.
"""
import argparse
import asyncio
import os
import sys
import time

from . import config, judge, repo
from .lane import LaneResult, run_lane


def _logger(start: float):
    def log(message: str) -> None:
        print(f"[{time.monotonic() - start:6.1f}s] {message}", flush=True)
    return log


def _clients(lanes, fake: bool):
    """One client per lane. Real lanes share one AsyncGroq; fake lanes get their own script."""
    if fake:
        from .fake import FakeClient
        return {lane.name: FakeClient(lane.name) for lane in lanes}
    if not os.environ.get("GROQ_API_KEY"):
        sys.exit("GROQ_API_KEY is not set. Put it in .env (see .env.example), or run with --fake.")
    from groq import AsyncGroq
    shared = AsyncGroq(max_retries=0)   # lane.py retries 429s itself, so it can count them
    return {lane.name: shared for lane in lanes}


def print_scoreboard(scores: list[judge.Score], results: dict[str, LaneResult]) -> None:
    hidden_total = scores[0].hidden.total if scores else 0
    print()
    print(f"{'rank':<5}{'lane':<8}{'visible':>8}{'hidden':>8}{'diff':>6}"
          f"{'rounds':>7}{'tokens':>8}  hidden failures")
    for rank, s in enumerate(scores, 1):
        r = results.get(s.lane)
        rounds, tokens = (r.rounds, f"{r.tokens}") if r else ("-", "-")
        fails = ", ".join(s.hidden.failed) or "-"
        if r and r.error:
            fails = f"ERROR {r.error[:60]}"
        print(f"{rank:<5}{s.lane:<8}{s.visible.passed:>5}/{s.visible.total:<2}"
              f"{s.hidden.passed:>5}/{hidden_total:<2}{s.diff_lines:>6}{rounds:>7}{tokens:>8}  {fails}")
    print()


def finish(scores: list[judge.Score], keep: bool) -> None:
    """Merge the winner into main and delete every lane. With keep, only report."""
    winner = judge.pick_winner(scores)
    if winner is None:
        print("No lane passed its visible tests. Nothing merged; main is unchanged.")
    else:
        ties = [s.lane for s in scores
                if s.hidden.passed == winner.hidden.passed and s.lane != winner.lane and s.eligible]
        why = f" (tie with {', '.join(ties)} broken by smallest diff, then lane name)" if ties else ""
        print(f"Winner: {winner.lane}, hidden {winner.hidden.passed}/{winner.hidden.total}, "
              f"{winner.diff_lines}-line change{why}.")
    if keep:
        print(f"--keep: nothing merged or deleted. Inspect {config.LANES_DIR}, "
              "then run `python -m src.main judge --merge`.")
        return
    if winner is not None:
        commit = repo.merge(winner.lane)
        print(f"Merged into main as {commit} in {config.REPO}")
    for lane in repo.lane_names():
        repo.discard(lane)


async def race(lanes, fake: bool, keep: bool) -> None:
    clients = _clients(lanes, fake)
    start = time.monotonic()
    log = _logger(start)

    repo.setup()
    paths = {lane.name: repo.add_worktree(lane.name) for lane in lanes}
    log(f"created {len(paths)} worktrees under {config.LANES_DIR}")
    judge.expected_total(config.HIDDEN_TEST_FILE)            # warm the cache before the clock matters

    log("starting all lanes")
    results = await asyncio.gather(*(
        run_lane(lane, paths[lane.name], clients[lane.name], start, log) for lane in lanes
    ))
    by_name = {r.lane: r for r in results}

    for r in results:
        changed = repo.commit_all(paths[r.lane], f"{r.lane}: attempt after {r.rounds} round(s)")
        if not changed:
            log(f"{r.lane} produced no change")

    log("judging")
    scores = judge.judge([lane.name for lane in lanes])
    print_scoreboard(scores, by_name)
    print(f"Race took {time.monotonic() - start:.0f}s, used {sum(r.tokens for r in results):,} tokens, "
          f"hit {sum(r.rate_limited for r in results)} rate-limit refusals.")
    finish(scores, keep)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.main", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_race = sub.add_parser("race", help="run all lanes, judge, merge the winner")
    p_race.add_argument("--fake", action="store_true", help="scripted offline lanes, no API key")
    p_race.add_argument("--keep", action="store_true", help="judge only: no merge, keep every worktree")
    p_race.add_argument("--lanes", type=int, default=len(config.LANES),
                        help=f"how many lanes to run (1-{len(config.LANES)})")
    p_judge = sub.add_parser("judge", help="re-judge lanes kept by `race --keep`")
    p_judge.add_argument("--merge", action="store_true", help="also merge the winner and clean up")
    sub.add_parser("clean", help="delete workdir/")
    args = parser.parse_args(argv)

    if args.command == "race":
        lanes = config.LANES[:max(1, min(args.lanes, len(config.LANES)))]
        asyncio.run(race(lanes, args.fake, args.keep))
    elif args.command == "judge":
        names = repo.lane_names()
        if not names:
            sys.exit("No lanes to judge. Run `race --keep` first.")
        scores = judge.judge(names)
        print_scoreboard(scores, {})
        if args.merge:
            finish(scores, keep=False)
    elif args.command == "clean":
        repo._force_remove(config.WORKDIR)
        print(f"Deleted {config.WORKDIR}")


if __name__ == "__main__":
    main()
