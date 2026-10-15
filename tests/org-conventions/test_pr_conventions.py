"""
Org-wide PR convention tests.

Enforces conventions from:
- the org-wide agent instructions
- the org's RED-spec TDD standard (rules 1-5 below)

Run by reusable workflow .github/workflows/org-checks.yml on every PR.
To run locally:  pytest tests/org-conventions/ -v --timeout=30
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

# The base-resolution rule lives in _orggate so every gate scopes to the same window
# (a second copy once re-introduced the frozen-base-sha bug described there).
from _orggate import resolve_pr_base_sha as _resolve_pr_base_sha


def _find_repo_root() -> Path:
    """Find repo root: REPO_ROOT env var > walk up from cwd > walk up from __file__."""
    env_root = os.environ.get("REPO_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        if (p / ".git").exists():
            return p

    for start in (Path.cwd(), Path(__file__).resolve()):
        p = start
        while p != p.parent:
            if (p / ".git").exists():
                return p
            p = p.parent

    return Path.cwd()  # last resort


REPO_ROOT = _find_repo_root()

_EXCLUDE_DIRS = {".git", ".venv", "venv", "node_modules", ".lake", ".tox", "__pycache__", ".mypy_cache"}


def _skip_path(rel: str) -> bool:
    """Skip vendored/generated directories."""
    return any(f"/{d}/" in rel or rel.startswith(f"{d}/") for d in _EXCLUDE_DIRS)


# ═══════════════════════════════════════════════════════════════════════════
# TDD rule 1: Tests must RUN, not SKIP
# "Ship 501 stubs alongside specs so tests go RED not SKIP"
# ═══════════════════════════════════════════════════════════════════════════


class TestRedSpecStandards:
    """RED specs must actually fail — skipped tests are placeholders, not specs."""

    def test_no_all_skipped_test_files(self):
        """A file where every test is @skip is a placeholder, not a spec."""
        for test_file in REPO_ROOT.rglob("test_*.py"):
            if _skip_path(str(test_file.relative_to(REPO_ROOT))):
                continue
            content = test_file.read_text(errors="ignore")
            test_count = len(re.findall(r"def test_", content))
            skip_count = len(re.findall(r"@pytest\.mark\.skip\b", content))
            if test_count > 0 and test_count == skip_count:
                pytest.fail(
                    f"{test_file.relative_to(REPO_ROOT)}: all {test_count} tests "
                    f"are @skip — ship a 501 stub so tests go RED, not SKIP "
                    f"(TDD rule 1)"
                )

    def test_xfail_must_have_reason(self):
        """Every xfail needs reason= to document why failure is expected."""
        for test_file in REPO_ROOT.rglob("test_*.py"):
            if _skip_path(str(test_file.relative_to(REPO_ROOT))):
                continue
            content = test_file.read_text(errors="ignore")
            bare = re.findall(r"@pytest\.mark\.xfail\s*\n", content)
            if bare:
                pytest.fail(
                    f"{test_file.relative_to(REPO_ROOT)}: {len(bare)} bare "
                    f"@xfail without reason= (TDD rule 1)"
                )

    def test_no_empty_test_files(self):
        """Test files must contain at least one test function."""
        for test_file in REPO_ROOT.rglob("test_*.py"):
            if _skip_path(str(test_file.relative_to(REPO_ROOT))):
                continue
            content = test_file.read_text(errors="ignore")
            if len(re.findall(r"def test_", content)) == 0:
                pytest.fail(
                    f"{test_file.relative_to(REPO_ROOT)}: no test functions"
                )


# ═══════════════════════════════════════════════════════════════════════════
# TDD rule 2: Pydantic models define the contract
# TDD rule 4: Named mock methods — interface is the spec
# ═══════════════════════════════════════════════════════════════════════════


class TestSpecQuality:
    """Spec/contract tests must use typed assertions, not generic mocks."""

    def test_no_generic_magicmock_in_specs(self):
        """Contract tests should not accept anything via generic MagicMock.

        TDD rule 4: 'Name storage methods in mocks — interface is the spec.'
        Generic MagicMock() accepts any attribute/call, making tests meaningless.
        Use spec= or spec_set= to constrain mock behavior.
        """
        violations = []
        for test_file in REPO_ROOT.rglob("test_*.py"):
            if _skip_path(str(test_file.relative_to(REPO_ROOT))):
                continue
            rel = str(test_file.relative_to(REPO_ROOT))
            # Only check files in tests/contracts/ (work-order specs)
            if "/contracts/" not in rel:
                continue
            content = test_file.read_text(errors="ignore")
            # Find MagicMock() without spec= or spec_set=
            bare_mocks = re.findall(r"MagicMock\(\s*\)", content)
            if bare_mocks:
                violations.append(f"{rel}: {len(bare_mocks)} bare MagicMock()")
        if violations:
            pytest.fail(
                f"Generic MagicMock() in spec tests (TDD rule 4): "
                + "; ".join(violations)
            )


# ═══════════════════════════════════════════════════════════════════════════
# TDD rule 5: Error paths in tests
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorPathCoverage:
    """Spec tests should include error/edge cases, not just happy path."""

    def test_contract_tests_have_error_cases(self):
        """Contract test files should test at least one error scenario.

        TDD rule 5: '5+ error paths per endpoint — business rules in tests.'
        We check for presence of error testing patterns (pytest.raises, 4xx/5xx
        status codes, 'error' in test names).
        """
        for test_file in REPO_ROOT.rglob("test_*.py"):
            if _skip_path(str(test_file.relative_to(REPO_ROOT))):
                continue
            rel = str(test_file.relative_to(REPO_ROOT))
            if "/contracts/" not in rel:
                continue
            content = test_file.read_text(errors="ignore")
            test_count = len(re.findall(r"def test_", content))
            if test_count < 5:
                continue  # small contract files exempt
            has_error_tests = (
                "pytest.raises" in content
                or "status_code" in content
                or re.search(r"def test_\w*(error|invalid|reject|fail|bad|404|401|403|500)", content)
            )
            if not has_error_tests:
                pytest.fail(
                    f"{rel}: {test_count} tests but no error/edge cases "
                    f"(TDD rule 5)"
                )


# ═══════════════════════════════════════════════════════════════════════════
# Agent instructions: No mocks in production code
# ═══════════════════════════════════════════════════════════════════════════


class TestNoMocks:
    """No mock implementations in production code — zero tolerance."""

    def test_no_mock_in_non_test_python(self):
        violations = []
        for py_file in REPO_ROOT.rglob("*.py"):
            rel = str(py_file.relative_to(REPO_ROOT))
            if _skip_path(rel) or "/tests/" in rel or "/test_" in rel or rel.startswith("test") or "conftest" in rel:
                continue
            content = py_file.read_text(errors="ignore")
            if "from unittest.mock import" in content or "from unittest import mock" in content:
                violations.append(rel)
        assert not violations, f"Production code imports unittest.mock: {violations}"


# ═══════════════════════════════════════════════════════════════════════════
# Agent instructions: No hardcoded secrets
# ═══════════════════════════════════════════════════════════════════════════


class TestNoSecrets:
    """Never hardcode API keys, passwords, or tokens."""

    PATTERNS = [
        (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API key"),
        (r"sk-ant-[a-zA-Z0-9-]{20,}", "Anthropic API key"),
        (r"ghp_[a-zA-Z0-9]{36}", "GitHub PAT"),
        (r"ghs_[a-zA-Z0-9]{36}", "GitHub server token"),
        (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    ]

    def test_no_api_keys_in_source(self):
        violations = []
        for src_file in REPO_ROOT.rglob("*.py"):
            rel = str(src_file.relative_to(REPO_ROOT))
            if _skip_path(rel):
                continue
            content = src_file.read_text(errors="ignore")
            for pattern, label in self.PATTERNS:
                if re.search(pattern, content):
                    violations.append(f"{rel}: {label}")
        assert not violations, f"Hardcoded secrets: {violations}"

    def test_no_api_keys_in_config(self):
        violations = []
        for ext in ("*.json", "*.yaml", "*.yml", "*.toml"):
            for cfg in REPO_ROOT.rglob(ext):
                rel = str(cfg.relative_to(REPO_ROOT))
                if _skip_path(rel) or "package-lock" in rel:
                    continue
                content = cfg.read_text(errors="ignore")
                for pattern, label in self.PATTERNS:
                    if re.search(pattern, content):
                        violations.append(f"{rel}: {label}")
        assert not violations, f"Secrets in config: {violations}"


# ═══════════════════════════════════════════════════════════════════════════
# Agent instructions: Conventional commits
# ═══════════════════════════════════════════════════════════════════════════


CONVENTIONAL_PREFIXES = frozenset({
    "feat", "fix", "docs", "test", "refactor", "chore", "ci", "perf",
    "style", "revert",
    # Project-specific prefixes:
    "wc",       # spec/contract seed or update
    "critic",   # automated review commits
    "merge",    # Resolve-collision merges (conflict-resolving intent commits)
})


def _git(args, cwd):
    """Run a git command, returning the CompletedProcess (never raises on non-zero)."""
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, timeout=10, cwd=cwd,
    )


def _pr_commit_messages(cwd):
    """Return the subjects of PR-only commits (base..HEAD), or None if git is
    unavailable. An empty list means "git works but there are no PR commits".

    When the base cannot be resolved we return an empty list (nothing to check)
    rather than scanning unrelated base-branch history — only the PR's own
    commits should ever be gated.
    """
    if _git(["rev-parse", "HEAD"], cwd).returncode != 0:
        return None  # not a git repo / git unavailable

    base_sha = _resolve_pr_base_sha(cwd)
    if base_sha is None:
        return []  # no PR context — do not scan base-branch history

    result = _git(["log", f"{base_sha}..HEAD", "--format=%s"], cwd)
    if result.returncode != 0:
        return None
    return result.stdout.strip().splitlines()


# Boilerplate first-commit subjects emitted verbatim by coding-agent
# platforms before any real work is attached (e.g. GitHub Copilot's coding
# agent always opens a PR branch with a commit literally titled "Initial
# plan"). These aren't author-chosen messages, so gating on them only
# punishes every PR a given agent platform opens — allowlist by exact
# subject rather than prefix.
BOT_BOILERPLATE_SUBJECTS = frozenset({"Initial plan"})


def _is_conventional(msg: str, prefixes=CONVENTIONAL_PREFIXES) -> bool:
    """A commit subject is conventional if it carries an allowed prefix
    (``type:`` or ``type(scope):``), is a merge/revert subject, or is
    known coding-agent boilerplate (see ``BOT_BOILERPLATE_SUBJECTS``)."""
    if msg.startswith("Merge ") or msg.startswith("Revert "):
        return True
    if msg in BOT_BOILERPLATE_SUBJECTS:
        return True
    return any(
        msg.startswith(f"{p}:") or msg.startswith(f"{p}(")
        for p in prefixes
    )


class TestIsConventional:
    """Unit coverage for `_is_conventional` pinning the boilerplate allowlist
    (regression guard: Copilot's
    "Initial plan" commit failing org-conventions on every Copilot PR)."""

    def test_copilot_initial_plan_is_allowed(self):
        assert _is_conventional("Initial plan")

    def test_unrelated_freeform_subject_is_rejected(self):
        assert not _is_conventional("Initial plan for the new feature")
        assert not _is_conventional("oops fix typo")


class TestConventionalCommits:
    # Kept as a class attribute for backwards compatibility with any importer.
    PREFIXES = set(CONVENTIONAL_PREFIXES)

    def test_recent_commits_are_conventional(self):
        # Only the PR's own commits (base..HEAD) are gated, so pre-convention
        # commits already on the base branch never block a new PR.
        msgs = _pr_commit_messages(REPO_ROOT)
        if msgs is None:
            pytest.skip("git not available")
        for msg in msgs:
            assert _is_conventional(msg, self.PREFIXES), (
                f"Non-conventional commit: {msg!r}. "
                f"Use: {', '.join(sorted(self.PREFIXES))}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Agent instructions + TDD standard: Test safety
# ═══════════════════════════════════════════════════════════════════════════


class TestTestSafety:
    def test_pyproject_has_timeout(self):
        pyproject = REPO_ROOT / "pyproject.toml"
        if not pyproject.exists():
            pytest.skip("No pyproject.toml")
        assert "timeout" in pyproject.read_text(), "Must configure pytest timeout"

    def test_timeout_value_reasonable(self):
        pyproject = REPO_ROOT / "pyproject.toml"
        if not pyproject.exists():
            pytest.skip("No pyproject.toml")
        match = re.search(r"timeout\s*=\s*(\d+)", pyproject.read_text())
        if match:
            assert int(match.group(1)) <= 60, f"Timeout {match.group(1)}s too high"


# ═══════════════════════════════════════════════════════════════════════════
# The scanned window must be the PR's OWN commits, never base-branch history
# ═══════════════════════════════════════════════════════════════════════════


def _build_pr_repo(tmp_path):
    r"""A repo shaped like a real PR whose base branch moved after it opened.

    main:  A --- B ------------------- X          B = base.sha, frozen at open
                  \                               X = non-conventional, landed later
       pr:         P                              P = the PR's own commit

    Returns (repo, base_sha_at_open, pr_head, merge_commit).
    """
    r = tmp_path / "repo"
    r.mkdir()
    def g(*a):
        out = _git(list(a), r)
        assert out.returncode == 0, f"git {' '.join(a)} -> {out.stderr}"
        return out.stdout.strip()
    n = [0]
    def commit(subject):
        # One file per commit: a shared file would make the merge below conflict,
        # which fails the fixture rather than the assertion it is setting up.
        n[0] += 1
        name = f"f{n[0]}.txt"
        (r / name).write_text(subject)
        g("add", name)
        g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", subject)
        return g("rev-parse", "HEAD")

    g("init", "-q", "-b", "main")
    commit("feat: initial")
    base = commit("feat: base branch tip when the PR was opened")

    g("checkout", "-q", "-b", "pr")
    pr_head = commit("fix: the PR's own work")

    g("checkout", "-q", "main")
    commit("Update the verifier and its tests")

    # refs/pull/N/merge -- what a `pull_request` checkout actually resolves to
    g("checkout", "-q", "-b", "merged", "main")
    g("-c", "user.email=t@t", "-c", "user.name=t",
      "merge", "--no-ff", "-m", "Merge pull request #1", "pr")
    merge = g("rev-parse", "HEAD")
    return r, base, pr_head, merge


@pytest.mark.parametrize("checkout", ["merge-commit", "pr-head"])
def test_window_excludes_base_branch_commits(tmp_path, monkeypatch, checkout):
    """A commit that is on the base branch must never be gated against a PR.

    `github.event.pull_request.base.sha` is the base tip FROZEN at PR-open; it
    does not advance as main moves. So `base.sha..HEAD` spans everything main
    landed in the meantime, and the gate blames the PR author for other
    people's commits.

    The two parametrisations are not symmetric, and it is worth being exact
    about which one carries the bug:

    * ``merge-commit`` -- reproduces it. This is the shape a `pull_request`
      checkout actually takes (`refs/pull/N/merge` contains current base), so
      the frozen base.sha spans the base history the merge commit dragged in.
      Verified RED against the previous resolver.
    * ``pr-head`` -- passes both before and after, because a base commit is not
      reachable from the PR head at all. It is a REGRESSION GUARD, not a
      demonstration: it pins that the fix keeps working if the workflow is ever
      changed to check out `head.sha`.
    """
    repo, base_at_open, pr_head, merge = _build_pr_repo(tmp_path)
    _git(["checkout", "-q", merge if checkout == "merge-commit" else pr_head], repo)

    monkeypatch.setenv("PR_BASE_SHA", base_at_open)   # frozen, as CI exports it
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    monkeypatch.delenv("BASE_SHA", raising=False)
    monkeypatch.delenv("BASE_REF", raising=False)

    msgs = _pr_commit_messages(repo)
    assert msgs is not None, "git unavailable"

    # Positive control: a fix that always returned [] would pass the assertion
    # below while gating nothing at all.
    assert any(m.startswith("fix: the PR's own work") for m in msgs), (
        f"the PR's own commit vanished from the window: {msgs}"
    )
    assert not any("Update the verifier" in m for m in msgs), (
        f"base-branch commit leaked into the gated window: {msgs}"
    )
