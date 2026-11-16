#!/usr/bin/env python3
"""Best-of-N for any git repo: N worktrees, a hidden-test judge, merge the winner.

Standard library only. Needs git >= 2.28 and pytest in the Python that runs it.

    bakeoff.py lanes   --repo . --n 5                     # create lane worktrees + branches
    bakeoff.py judge   --repo . --hidden /abs/hidden_tests --visible tests
    bakeoff.py merge   --repo . --lane lane-3              # merge one lane into the base branch
    bakeoff.py cleanup --repo .                            # delete every lane worktree + branch

Lanes live OUTSIDE the repo, in <repo-parent>/<repo-name>.bakeoff/lane-N, on
branches bakeoff/lane-N. State is kept in that folder's bakeoff.json.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


# ---------------------------------------------------------------- git helpers

def git(*args: str, cwd: Path) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{done.stderr.strip()}")
    return done.stdout.strip()


def workroot(repo: Path) -> Path:
    return repo.parent / f"{repo.name}.bakeoff"


def load_state(repo: Path) -> dict:
    f = workroot(repo) / "bakeoff.json"
    if not f.exists():
        raise SystemExit(f"No bake-off found for {repo}. Run `lanes` first.")
    return json.loads(f.read_text(encoding="utf-8"))


def save_state(repo: Path, state: dict) -> None:
    (workroot(repo) / "bakeoff.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- lanes

def cmd_lanes(repo: Path, n: int) -> None:
    if git("status", "--porcelain", cwd=repo):
        raise SystemExit("The repo has uncommitted changes. Commit the task (spec, stub, visible tests) first.")
    root = workroot(repo)
    if root.exists():
        raise SystemExit(f"{root} already exists. Run `cleanup` first.")
    base = git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    base_commit = git("rev-parse", "HEAD", cwd=repo)
    root.mkdir()
    lanes = {}
    for i in range(1, n + 1):
        name = f"lane-{i}"
        path = root / name
        git("worktree", "add", "-q", "-b", f"bakeoff/{name}", str(path), base_commit, cwd=repo)
        lanes[name] = str(path)
    save_state(repo, {"base": base, "base_commit": base_commit, "lanes": lanes})
    print(json.dumps({"base": base, "lanes": lanes}, indent=2))


# ---------------------------------------------------------------- judge

def run_pytest(code_dir: Path, target: Path, import_dir: Path, timeout: int) -> dict:
    """Run pytest on target with import_dir importable. Returns passed/total/failed."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(import_dir), os.environ.get("PYTHONPATH", "")]),
           "PYTHONDONTWRITEBYTECODE": "1"}
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "r.xml"
        cmd = [sys.executable, "-m", "pytest", str(target), "-q", "-p", "no:cacheprovider",
               f"--rootdir={code_dir}", f"--junitxml={report}"]
        try:
            subprocess.run(cmd, cwd=code_dir, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"passed": 0, "total": 0, "failed": ["timeout"]}
        if not report.exists():
            return {"passed": 0, "total": 0, "failed": ["no-report"]}
        passed, failed, total = 0, [], 0
        for case in ET.parse(report).getroot().iter("testcase"):
            total += 1
            name = case.get("name", "?")
            if len(case):
                failed.append(name[name.find("[") + 1:-1] if "[" in name else name)
            else:
                passed += 1
        return {"passed": passed, "total": total, "failed": failed}


def diff_size(repo: Path, base_commit: str, branch: str) -> int:
    total = 0
    for row in git("diff", "--numstat", f"{base_commit}...{branch}", cwd=repo).splitlines():
        added, removed, _ = row.split("\t", 2)
        if added != "-":
            total += int(added) + int(removed)
    return total


def cmd_judge(repo: Path, hidden: Path, visible: str | None, import_dir: str, timeout: int) -> None:
    state = load_state(repo)
    hidden = hidden.resolve()
    if hidden.is_relative_to(repo.resolve()) or hidden.is_relative_to(workroot(repo).resolve()):
        raise SystemExit("Hidden tests must live outside the repo and the lane folders.")

    def score(item):
        name, path = item
        path = Path(path)
        git("add", "-A", cwd=path)                       # commit whatever the lane left behind
        if git("status", "--porcelain", cwd=path):
            git("-c", "user.name=bakeoff", "-c", "user.email=bakeoff@localhost",
                "commit", "-q", "-m", f"{name}: final state", cwd=path)
        imp = path / import_dir
        vis = run_pytest(path, path / visible, imp, timeout) if visible else None
        hid = run_pytest(path, hidden, imp, timeout)
        return {"lane": name, "branch": f"bakeoff/{name}", "path": str(path),
                "visible": vis, "hidden": hid,
                "diff_lines": diff_size(repo, state["base_commit"], f"bakeoff/{name}")}

    with ThreadPoolExecutor(max_workers=len(state["lanes"])) as pool:
        scores = list(pool.map(score, state["lanes"].items()))

    def eligible(s):
        v = s["visible"]
        return v is None or (v["total"] > 0 and v["passed"] == v["total"])

    scores.sort(key=lambda s: (not eligible(s), -s["hidden"]["passed"],
                               -(s["visible"] or {"passed": 0})["passed"], s["diff_lines"], s["lane"]))
    winner = next((s["lane"] for s in scores if eligible(s) and s["hidden"]["passed"] > 0), None)
    state["scores"], state["winner"] = scores, winner
    save_state(repo, state)

    print(f"{'rank':<5}{'lane':<9}{'visible':>9}{'hidden':>9}{'diff':>6}  hidden failures")
    for i, s in enumerate(scores, 1):
        v = f"{s['visible']['passed']}/{s['visible']['total']}" if s["visible"] else "-"
        h = f"{s['hidden']['passed']}/{s['hidden']['total']}"
        print(f"{i:<5}{s['lane']:<9}{v:>9}{h:>9}{s['diff_lines']:>6}  {', '.join(s['hidden']['failed']) or '-'}")
    print(f"\nWinner: {winner}" if winner else "\nNo eligible winner (no lane passed its visible tests).")
    print(f"Scoreboard saved to {workroot(repo) / 'bakeoff.json'}")


# ---------------------------------------------------------------- merge / cleanup

def cmd_merge(repo: Path, lane: str | None) -> None:
    state = load_state(repo)
    lane = lane or state.get("winner")
    if not lane or lane not in state["lanes"]:
        raise SystemExit("Name a lane with --lane, or run `judge` first.")
    current = git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    if current != state["base"]:
        raise SystemExit(f"Check out {state['base']} in {repo} first (currently on {current}).")
    if git("status", "--porcelain", cwd=repo):
        raise SystemExit("The repo has uncommitted changes; commit or stash them before merging.")
    git("merge", "-q", "--no-ff", f"bakeoff/{lane}", "-m", f"bake-off winner: {lane}", cwd=repo)
    print(f"Merged bakeoff/{lane} into {state['base']} as {git('rev-parse', '--short', 'HEAD', cwd=repo)}")


def cmd_cleanup(repo: Path) -> None:
    state = load_state(repo)
    for name, path in state["lanes"].items():
        if Path(path).exists():
            git("worktree", "remove", "--force", path, cwd=repo)
        if git("branch", "--list", f"bakeoff/{name}", cwd=repo):
            git("branch", "-D", f"bakeoff/{name}", cwd=repo)
    git("worktree", "prune", cwd=repo)
    shutil.rmtree(workroot(repo), ignore_errors=True)
    print(f"Removed {len(state['lanes'])} lanes and {workroot(repo)}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("lanes", "judge", "merge", "cleanup"):
        sp = sub.add_parser(name)
        sp.add_argument("--repo", type=Path, default=Path("."))
        if name == "lanes":
            sp.add_argument("--n", type=int, default=5)
        if name == "judge":
            sp.add_argument("--hidden", type=Path, required=True, help="hidden test file or folder, outside the repo")
            sp.add_argument("--visible", help="visible tests, relative to a lane (e.g. tests)")
            sp.add_argument("--import-dir", default=".", help="folder put on PYTHONPATH, relative to a lane")
            sp.add_argument("--timeout", type=int, default=120)
        if name == "merge":
            sp.add_argument("--lane", help="defaults to the judged winner")
    a = p.parse_args()
    repo = Path(git("rev-parse", "--show-toplevel", cwd=a.repo.resolve()))
    if a.cmd == "lanes":
        cmd_lanes(repo, a.n)
    elif a.cmd == "judge":
        cmd_judge(repo, a.hidden, a.visible, a.import_dir, a.timeout)
    elif a.cmd == "merge":
        cmd_merge(repo, a.lane)
    else:
        cmd_cleanup(repo)


if __name__ == "__main__":
    main()
