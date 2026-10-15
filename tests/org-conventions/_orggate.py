"""Shared helpers for the org gates. Every gate scopes to the PR's own range.

The range is `range_base(root)...HEAD`, where the base is the MERGE-BASE of HEAD and the base
branch's current tip — never `github.event.pull_request.base.sha`, which is frozen at PR-open.
Measured (upstream review, 2026-09-06): with that frozen sha preferred and a `refs/pull/N/merge`
checkout, main commits landing after the PR opened were blamed on the PR — the --help gate ran
another PR's script, the blob gate failed an innocent PR on a 2 MiB file main added, and the
placeholder gate warned on main's TODO. The same bug had been fixed once before, so the
resolution rule is defined ONCE here and test_pr_conventions imports it.
"""
from __future__ import annotations
import os, re, subprocess
from pathlib import Path

def repo_root() -> Path:
    return Path(os.environ.get("REPO_ROOT", ".")).resolve()

def org_root() -> Path:
    return Path(os.environ.get("ORG_REPO_ROOT", Path(__file__).resolve().parents[2])).resolve()

def _git(args, cwd):
    """Run a git command, returning the CompletedProcess (never raises on non-zero)."""
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, cwd=cwd)


def resolve_pr_base_sha(cwd) -> str | None:
    """Resolve the base commit the PR branches from — PR-only commits are base..HEAD.

    The base is the base branch's **tip**, not the merge base and not
    ``base.sha``. Excluding everything reachable from the base branch is what
    makes the window the PR's own commits, and it is correct for both shapes a
    CI checkout can take:

    * ``refs/pull/N/merge`` (the default for ``pull_request``) — a merge commit
      that already contains the base tip, so ``tip..HEAD`` is the PR's commits.
    * the PR head — ``tip..HEAD`` still excludes base history, even when the
      branch is hundreds of commits stale.

    The merge base yields the same window as the tip in both shapes above, so
    this is not a correctness fix over it — the tip is simply the direct
    expression of "everything already on the base branch is not ours", and it
    stays right if the checkout shape changes again.

    ``github.event.pull_request.base.sha`` must NOT be preferred: it is the base
    tip frozen at PR-open and never advances, so on any PR older than a base
    commit it reintroduces exactly the bug this function exists to prevent
    (an earlier variant of the same bug scanned the base branch's "last N commits"). It is kept only as a last resort for a checkout so shallow that no
    base ref is reachable at all.

    Returns the base SHA, or None when no base information is available
    (e.g. a direct push to a long-lived branch with no PR context).
    """
    # 1. Base branch tip, from the ref CI tells us the PR targets.
    env_refs = []
    for env_name in ("PR_BASE_REF", "BASE_REF", "GITHUB_BASE_REF"):
        ref = os.environ.get(env_name, "").strip()
        if ref:
            env_refs.extend([f"origin/{ref}", ref])

    # 2. Conventional defaults, for a checkout that exports no base ref.
    candidate_refs = [*env_refs, "origin/main", "main", "origin/master", "master"]

    seen = set()
    for ref in candidate_refs:
        if not ref or ref in seen:
            continue
        seen.add(ref)
        tip = _git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd)
        if tip.returncode == 0 and tip.stdout.strip():
            return tip.stdout.strip()

    # 3. Last resort only — see the docstring. A frozen base.sha over-reports,
    # but a shallow checkout with no base ref leaves nothing better.
    for env_name in ("PR_BASE_SHA", "BASE_SHA"):
        sha = os.environ.get(env_name, "").strip()
        if sha and _git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd).returncode == 0:
            return sha

    return None


def range_base(root: Path) -> str | None:
    """The commit the gates diff from: merge-base(HEAD, base-branch tip), else the frozen sha.

    `resolve_pr_base_sha` already orders the candidates correctly (base ref tip first,
    `PR_BASE_SHA` last). Reducing the tip to its merge-base with HEAD makes the returned sha
    the same commit whether the checkout is `refs/pull/N/merge` or the bare PR head, and
    makes `base..HEAD` and `base...HEAD` agree. When the last-resort frozen sha is all there
    is (shallow checkout, no base ref) there is nothing to reduce against and it is returned
    as-is — over-reporting, but never a crash.
    """
    base = resolve_pr_base_sha(root)
    if base is None:
        return None
    mb = _git(["merge-base", "HEAD", base], root)
    return mb.stdout.strip() or base

def changed_files(root: Path, base: str | None, diff_filter: str | None = None) -> list[Path]:
    if base is None:
        return []
    cmd = ["git", "diff", "--name-only"] + ([f"--diff-filter={diff_filter}"] if diff_filter else []) + [f"{base}...HEAD"]
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=True)
    return [root / l.strip() for l in r.stdout.splitlines() if l.strip()]

def added_files(root: Path, base: str | None) -> list[Path]:
    return changed_files(root, base, "A")

def added_lines(root: Path, base: str | None) -> list[tuple[str, int, str]]:
    if base is None:
        return []
    r = subprocess.run(["git", "diff", "--unified=0", "--no-color", f"{base}...HEAD"], cwd=root, capture_output=True, text=True, check=True)
    out, path, lineno = [], None, 0
    for line in r.stdout.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line); lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++") and path:
            out.append((path, lineno, line[1:])); lineno += 1
        elif not line.startswith(("-", "\\")):
            # `\ No newline at end of file` is diff metadata, not a context line — counting it
            # put every annotation on a file whose old version lacked a trailing newline one
            # line low.
            lineno += 1
    return out
