"""Unit tests for the shared org-gates helper module (_orggate.py).

_orggate centralizes the env contract every gate file relies on
(REPO_ROOT / ORG_REPO_ROOT / PR_BASE_SHA / BASE_REF) plus the git-diff
helpers used to scope a gate to the PR's own changes. Covered here with
a real throwaway git repo (no mocks) per repo convention.

Run locally: pytest tests/org-conventions/test_orggate.py -v --timeout=30
"""
import os
import subprocess
from pathlib import Path

import pytest

from _orggate import repo_root, org_root, range_base, added_files, added_lines


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def tiny_repo(tmp_path, monkeypatch):
    """A throwaway repo: base commit on 'main', one PR commit adding a file."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "existing.txt").write_text("one\n")
    _git(root, "add", "existing.txt")
    _git(root, "commit", "-q", "-m", "base")
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()

    _git(root, "checkout", "-q", "-b", "feature")
    (root / "new_file.py").write_text("def test_x():\n    assert True\n")
    (root / "existing.txt").write_text("one\ntwo\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "pr change")

    monkeypatch.delenv("REPO_ROOT", raising=False)
    monkeypatch.delenv("ORG_REPO_ROOT", raising=False)
    monkeypatch.delenv("PR_BASE_SHA", raising=False)
    monkeypatch.delenv("BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    return root, base_sha


class TestRepoRoot:
    def test_uses_repo_root_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPO_ROOT", str(tmp_path))
        assert repo_root() == tmp_path.resolve()

    def test_defaults_to_cwd(self, monkeypatch):
        monkeypatch.delenv("REPO_ROOT", raising=False)
        assert repo_root() == Path(".").resolve()


class TestOrgRoot:
    def test_uses_org_repo_root_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORG_REPO_ROOT", str(tmp_path))
        assert org_root() == tmp_path.resolve()

    def test_defaults_to_this_repos_checkout(self, monkeypatch):
        monkeypatch.delenv("ORG_REPO_ROOT", raising=False)
        # _orggate.py lives at <org_root>/tests/org-conventions/_orggate.py
        assert (org_root() / "actions" / "org-gates" / "action.yml").exists()


def _sha(root, ref="HEAD"):
    return subprocess.run(["git", "rev-parse", ref], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture(params=["merge-commit", "pr-head"])
def stale_pr_repo(tmp_path, monkeypatch, request):
    """The frozen-base-sha shape: main advanced AFTER the PR opened, and PR_BASE_SHA is frozen at open.

    M0 (base at PR-open) -> feature adds pr_file.py
    main advances to M1 adding main_file.py (with a line the placeholder gate would flag)
    origin/main -> M1; PR_BASE_SHA -> M0 (what github.event.pull_request.base.sha carries)
    HEAD is either refs/pull/N/merge (M1 merged with feature) or the bare PR head.
    Either way, the PR's own change is exactly pr_file.py.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("base\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "M0")
    m0 = _sha(root)

    _git(root, "checkout", "-q", "-b", "feature")
    (root / "pr_file.py").write_text("def pr():\n    return 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "pr change")

    _git(root, "checkout", "-q", "main")
    (root / "main_file.py").write_text("def later():\n    return {}  # TODO fill in later\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "M1 lands on main after the PR opened")
    m1 = _sha(root)
    _git(root, "update-ref", "refs/remotes/origin/main", m1)

    if request.param == "merge-commit":
        _git(root, "merge", "-q", "--no-ff", "-m", "Merge pull request #1", "feature")
    else:
        _git(root, "checkout", "-q", "feature")

    monkeypatch.delenv("REPO_ROOT", raising=False)
    monkeypatch.delenv("BASE_REF", raising=False)
    monkeypatch.delenv("PR_BASE_REF", raising=False)
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    monkeypatch.setenv("PR_BASE_SHA", m0)
    return root, m0, m1


class TestRangeBase:
    def test_prefers_the_merge_base_against_the_base_ref_over_a_frozen_pr_base_sha(self, stale_pr_repo):
        # Inverts the pinned-wrong behaviour: PR_BASE_SHA (base.sha, frozen at PR-open) must
        # NOT win over a reachable base ref (it blamed main's later commits on the PR).
        root, m0, m1 = stale_pr_repo
        expected = subprocess.run(
            ["git", "merge-base", "HEAD", "origin/main"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert range_base(root) == expected
        # In the merge-commit shape that is M1, not the frozen M0; in the pr-head shape the
        # merge-base happens to BE M0, so the two only coincide there.
        assert expected == (m1 if _sha(root, "HEAD") != _sha(root, "feature") else m0)

    def test_pr_base_sha_is_the_last_resort_when_no_base_ref_resolves(self, tiny_repo, monkeypatch):
        root, base_sha = tiny_repo
        _git(root, "branch", "-q", "-m", "main", "not-a-base-ref")  # no main/master/origin ref left
        monkeypatch.setenv("PR_BASE_SHA", base_sha)
        assert range_base(root) == base_sha

    def test_pr_base_sha_that_is_not_a_reachable_commit_is_ignored(self, tiny_repo, monkeypatch):
        root, _ = tiny_repo
        _git(root, "branch", "-q", "-m", "main", "not-a-base-ref")
        monkeypatch.setenv("PR_BASE_SHA", "deadbeef")
        assert range_base(root) is None

    def test_falls_back_to_merge_base_against_base_ref(self, tiny_repo, monkeypatch):
        root, base_sha = tiny_repo
        _git(root, "branch", "-q", "-m", "main", "origin-main-shadow")  # keep base reachable
        _git(root, "branch", "-q", "main-tracking", base_sha)
        # Simulate an 'origin/main' ref pointing at the base commit.
        (root / ".git" / "refs" / "remotes" / "origin").mkdir(parents=True)
        (root / ".git" / "refs" / "remotes" / "origin" / "main").write_text(base_sha + "\n")
        monkeypatch.setenv("BASE_REF", "main")
        assert range_base(root) == base_sha


class TestFrozenBaseRegression:
    """The frozen-base-sha bug across all three gates: with main advanced after PR-open and PR_BASE_SHA frozen at
    M0, every gate must collect ONLY the PR's own change — never main_file.py."""

    def test_added_files_collects_only_the_prs_file(self, stale_pr_repo):
        root, _m0, _m1 = stale_pr_repo
        assert added_files(root, range_base(root)) == [root / "pr_file.py"]

    def test_added_lines_blames_only_the_prs_lines(self, stale_pr_repo):
        root, _m0, _m1 = stale_pr_repo
        paths = {p for p, _n, _t in added_lines(root, range_base(root))}
        assert paths == {"pr_file.py"}

    def test_the_frozen_sha_alone_would_have_over_reported(self, stale_pr_repo):
        # Positive control for the regression: the old behaviour (diff from the frozen M0)
        # blames main's file on the PR in the merge-commit shape. If this stops holding,
        # the fixture no longer models that bug and the tests above prove nothing.
        root, m0, _m1 = stale_pr_repo
        head_is_merge = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD^2"], cwd=root,
                                       capture_output=True, text=True).returncode == 0
        if head_is_merge:
            assert root / "main_file.py" in added_files(root, m0)
        else:
            pytest.skip("pr-head shape: the frozen sha happens to equal the merge base")


class TestAddedFiles:
    def test_lists_only_new_files_in_the_pr_range(self, tiny_repo):
        root, base_sha = tiny_repo
        files = added_files(root, base_sha)
        assert files == [root / "new_file.py"]

    def test_empty_when_no_base(self, tiny_repo):
        root, _base_sha = tiny_repo
        assert added_files(root, None) == []


class TestAddedLines:
    def test_reports_new_lines_with_path_and_lineno(self, tiny_repo):
        root, base_sha = tiny_repo
        lines = added_lines(root, base_sha)
        by_path = {}
        for path, lineno, text in lines:
            by_path.setdefault(path, []).append((lineno, text))
        assert ("new_file.py") in by_path
        assert (1, "def test_x():") in by_path["new_file.py"]
        # existing.txt got one new line ("two") appended after the pre-existing "one"
        assert ("existing.txt") in by_path
        assert (2, "two") in by_path["existing.txt"]

    def test_empty_when_no_base(self, tiny_repo):
        root, _base_sha = tiny_repo
        assert added_lines(root, None) == []


class TestAddedLinesNoTrailingNewline:
    def test_no_newline_marker_does_not_shift_the_line_numbers(self, tmp_path, monkeypatch):
        """`\\ No newline at end of file` is diff metadata, not a context line. Counting it
        advanced lineno by one, so every annotation on a file whose OLD version lacked a
        trailing newline landed one line low (upstream review, minor)."""
        root = tmp_path / "repo"
        root.mkdir()
        _git(root, "init", "-q", "-b", "main")
        _git(root, "config", "user.email", "test@example.com")
        _git(root, "config", "user.name", "Test")
        (root / "notes.py").write_text("one")            # no trailing newline
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "base")
        base = _sha(root)
        _git(root, "checkout", "-q", "-b", "feature")
        (root / "notes.py").write_text("one\ntwo  # TODO\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "append")
        got = [(n, t) for p, n, t in added_lines(root, base) if p == "notes.py"]
        assert got == [(1, "one"), (2, "two  # TODO")]
