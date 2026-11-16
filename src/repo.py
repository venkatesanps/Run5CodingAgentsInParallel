"""Git plumbing: the target repo, one worktree per lane, commit, diff, merge, discard.

Reads:   sample/ (the starting code) and lane names.
Creates: workdir/repo (a git repo on branch main) and workdir/lanes/<lane>
         (one worktree + one branch per lane, all sharing repo/.git).
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

from . import config


def git(*args: str, cwd: Path | None = None) -> str:
    """Run one git command (in the target repo unless cwd says otherwise) and return stdout."""
    done = subprocess.run(
        ["git", *args], cwd=cwd or config.REPO, capture_output=True, text=True, encoding="utf-8"
    )
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{done.stderr.strip()}")
    return done.stdout.strip()


def _force_remove(path: Path) -> None:
    """shutil.rmtree that also deletes git's read-only object files on Windows."""
    def make_writable_and_retry(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if path.exists():
        shutil.rmtree(path, onexc=make_writable_and_retry)


def setup() -> None:
    """Start clean: copy sample/ into workdir/repo and make the first commit on main."""
    _force_remove(config.WORKDIR)
    shutil.copytree(config.SAMPLE_DIR, config.REPO)
    git("init", "-q", "-b", "main")
    git("config", "user.name", "bake-off")             # this repo only, not your global config
    git("config", "user.email", "bake-off@localhost")
    git("add", "-A")
    git("commit", "-q", "-m", "start: parse_inr stub + visible tests")


# --- a lane's lifecycle: worktree -> commit -> diff -> merge or discard ---------

def add_worktree(lane: str) -> Path:
    """A new folder and a new branch for one lane, both starting from main."""
    path = config.LANES_DIR / lane
    git("worktree", "add", "-q", "-b", lane, str(path), "main")
    return path


def commit_all(path: Path, message: str) -> bool:
    """Commit everything a lane changed, on that lane's own branch. False if nothing changed."""
    git("add", "-A", cwd=path)
    if not git("status", "--porcelain", cwd=path):
        return False
    git("commit", "-q", "-m", message, cwd=path)
    return True


def diff_size(lane: str) -> int:
    """Lines added + removed on the lane's branch since it left main (the tie-breaker)."""
    total = 0
    for row in git("diff", "--numstat", f"main...{lane}").splitlines():
        added, removed, _name = row.split("\t", 2)
        if added != "-":                       # "-" marks a binary file; skip it
            total += int(added) + int(removed)
    return total


def merge(lane: str) -> str:
    """Merge the winning lane into main with a merge commit. Returns main's new hash."""
    git("merge", "-q", "--no-ff", lane, "-m", f"bake-off winner: {lane}")
    return git("rev-parse", "--short", "HEAD")


def discard(lane: str) -> None:
    """Delete a lane's folder and its branch. Safe to call twice."""
    path = config.LANES_DIR / lane
    if path.exists():
        git("worktree", "remove", "--force", str(path))
    git("worktree", "prune")
    if git("branch", "--list", lane):
        git("branch", "-D", lane)


def lane_names() -> list[str]:
    """Lanes that currently have a worktree, in name order."""
    if not config.LANES_DIR.exists():
        return []
    return sorted(p.name for p in config.LANES_DIR.iterdir() if p.is_dir())


def worktree_list() -> str:
    """Every folder checked out from this repo, with its branch (for debugging)."""
    return git("worktree", "list")
