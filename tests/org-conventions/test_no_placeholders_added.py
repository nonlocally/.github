"""Org gate: a PR must not ADD placeholder / mock / stub lines to non-test source.

The org's no-placeholder rule made mechanical. Scoped to ADDED lines in
the PR range; test files, docs, and fixtures are exempt (mocks belong there). Escape hatch:
append `# gate: allow-placeholder` to the line — it is grep-able and shows in review.

Measured blast radius (2026-09-06): ran `offending(added_lines(...))` with HEAD at each of
the last 20 merged PRs' merge commits in each of three consumer repos (A, B, C),
base = the merge commit's first parent. Every failing PR was read line-by-line, not just
counted — exactly one hit (repo B, a doc comment on a real placeholder default value
shipped in production code) is a correct catch; the rest are false positives. Keep the true
catch and the false-positive count SEPARATE — conflating them ("N/60 false positives" when
one of the N is actually correct) is the mistake round 1 of review caught here.

| repo                     | PRs checked | fail — BEFORE fix | fail — AFTER fix |
|--------------------------|-------------|--------------------|--------------------|
| A                        | 20          | 0                  | 0                  |
| B                        | 20          | 1 (true catch)     | 1 (true catch)     |
| C                        | 20          | 4                  | 3                  |
| **total**                | **60**      | **5 (8.3%)**       | **4 (6.7%)**       |
| — of which false positive |            | **4 (6.7%)**       | **3 (5.0%)**       |
| — of which mock*/stub*    |            | **2 (3.3%)**       | **1 (1.7%)**       |

mock/stub-specific failures stayed under the design's 10% threshold both before (3.3%) and
after (1.7%) the fixes below, so `mock|stub` is KEPT in PLACEHOLDER_RE (the drop-mock/stub
branch of the design's rule never fires). The false positives came from THREE causes, not the
one the design anticipated:
  1. Negated/descriptive comments ("never a placeholder string", "not a placeholder card") —
     the code explicitly does NOT do the flagged thing. STILL PRESENT after the fixes below
     (repo C, two PRs) — out of scope for a line-level regex gate
     without full-sentence negation parsing; left as-is.
  2. Domain vocabulary overlapping the trigger words in non-deceptive senses: a form field's
     `placeholder` attribute, an SVG wire "stub" drawing routine, "e2e mocks" referenced in
     prose. Two sub-cases were fixed (review round 1):
       (a) `placeholder="..."` / `placeholder: "..."` / `data-placeholder="..."` (JSX props,
           object keys, HTML data-attributes) no longer fire — `PLACEHOLDER_RE`'s placeholder
           alternative now excludes a `data-` prefix and an immediately following `:`/`=`
           (`test_placeholder_regex_ignores_attribute_and_key_uses`), while the true catch
           above (prose "is a placeholder", not an assignment) still fires
           (`test_placeholder_regex_still_catches_the_measured_true_positive`).
       (b) STILL PRESENT: a CSS BEM class name ending in `--placeholder` and a
           bare-word "stub"/"mocks" inside prose (an SVG-terminology comment,
           an "e2e mocks" reference) are not covered by the attribute/key lookahead
           fix and were not in round 1's scope — left as-is, same false-positive class as #1.
  3. `exempt()` gap, FIXED (additive, round 1): it recognized Python's `test_*.py` /
     `conftest.py` convention and a `tests/`/`test/` directory, but not JS/TS's colocated
     `*.test.ts` / `*.spec.ts` convention, Jest's `__tests__/`, or Playwright's `e2e/` — so
     four colocated `*.test.ts` / `*.spec.ts` files were scored as non-test source (all fixed;
     `test_exempt_recognizes_colocated_and_jest_playwright_test_conventions`). This dropped
     one repo C PR out of the failing set entirely.

ADVISORY ROLLOUT (review round 2, 2026-09-06): the residual 5% false-positive rate above is
too high to fail real PRs the moment this gate lands, so it is ADVISORY by default — offending
lines are printed as `::warning` GitHub annotations and the test PASSES — until
`ORG_GATE_PLACEHOLDER_ENFORCE=1`/`true` is set in the job's environment (planned: after a
measured week of warnings on real traffic shows the false-positive rate is acceptable).

Flip path (final-review Finding 3, fixed 2026-09-06): `ORG_GATE_PLACEHOLDER_ENFORCE` is set
from the `placeholder-enforce` input, threaded consumer -> `org-checks.yml` (workflow_call
input, default `"false"`) -> `actions/org-gates` (composite input, same default) -> this
process's env. The flip is a ONE-LINE, PER-REPO opt-in on the consumer's own caller —
`uses: .../org-checks.yml` with `with: { placeholder-enforce: "true" }` — not an
`org-checks.yml` edit, so it does not flip every consumer simultaneously.

Run by reusable workflow .github/workflows/org-checks.yml (suite: conventions) on every PR.
To run locally:  REPO_ROOT=<repo> pytest tests/org-conventions/test_no_placeholders_added.py -v --timeout=30
"""
from __future__ import annotations

import os
import re
import subprocess

import pytest

from _orggate import repo_root, range_base, added_lines

PLACEHOLDER_RE = re.compile(
    r"\b(TODO|FIXME|XXX|HACK)\b|(?<!data-)\bplaceholder\b(?!\s*[:=])|\bmock(ed|s)?\b|\bstub(bed|s)?\b|"
    r"NotImplementedError\(\)|^\s*pass\s*#|return\s+(\{\}|\[\]|None)\s*#.*(later|todo|stub)",
    re.I,
)
ALLOW = "gate: allow-placeholder"
EXEMPT_DIRS = ("tests/", "test/", "docs/", "fixtures/", "examples/", ".github/", "scripts/mutants/")
EXEMPT_SUFFIXES = (".md", ".rst", ".txt", ".json", ".yaml", ".yml", ".lock", ".svg", ".csv")
SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".svelte", ".go", ".rs", ".sh", ".lean")


def exempt(path: str) -> bool:
    from pathlib import Path
    p = Path(path)
    # Additive fix (review round 1): the original exempt() only knew Python's test_*.py /
    # conftest.py convention and a tests/|test/ directory. JS/TS colocates tests next to
    # source (*.test.ts, *.spec.ts) and Jest's __tests__/ and Playwright's e2e/ directories
    # carry no "test_" prefix at all — that gap false-positived on real merged PRs (measured
    # 2026-09-06, see docstring). Additive only: does not weaken the true catch below.
    return path.startswith(EXEMPT_DIRS) or "/tests/" in path or path.endswith(EXEMPT_SUFFIXES) \
        or not path.endswith(SOURCE_SUFFIXES) or p.name.startswith(("test_", "conftest")) \
        or p.stem.endswith((".test", ".spec")) or "/e2e/" in path or "/__tests__/" in path


def _offending_tuples(lines: list[tuple[str, int, str]]) -> list[tuple[str, int, str]]:
    return [(p, n, t) for p, n, t in lines if not exempt(p) and PLACEHOLDER_RE.search(t) and ALLOW not in t]


def offending(lines: list[tuple[str, int, str]]) -> list[str]:
    """Pure: no printing, no env reads. Used both by the gate test and by _offending_tuples'
    callers that need the formatted string (controls, the enforce path)."""
    return [f"{p}:{n}: {t.strip()[:120]}" for p, n, t in _offending_tuples(lines)]


def test_pr_adds_no_placeholder_lines(capsys):
    root = repo_root()
    lines = added_lines(root, range_base(root))
    hits = _offending_tuples(lines)
    for p, n, t in hits:
        print(
            f"::warning file={p},line={n}::placeholder/mock/stub line added: "
            f"{t.strip()[:120]} (append '# gate: allow-placeholder' if intentional)"
        )
    enforce = os.environ.get("ORG_GATE_PLACEHOLDER_ENFORCE", "").strip().lower() in ("1", "true")
    if enforce:
        bad = offending(lines)
        assert not bad, "placeholder/mock/stub lines added to non-test source (append '# gate: allow-placeholder' if intentional):\n" + "\n".join(bad)


# ---- positive controls -----------------------------------------------------------------
def test_gate_bites_on_a_todo_in_source():
    assert offending([("src/app.py", 3, "    return {}  # TODO fill in later")]) == ["src/app.py:3: return {}  # TODO fill in later"]


def test_gate_ignores_tests_docs_and_allowlisted_lines():
    assert offending([
        ("tests/test_x.py", 1, "mock = Mock()"),
        ("docs/plan.md", 1, "TODO"),
        ("src/app.py", 9, "MockFlag = True  # gate: allow-placeholder"),
    ]) == []


def test_gate_allowlist_is_load_bearing_on_a_line_that_would_otherwise_fire():
    # Without the marker this line trips the FIXME alternative; the allowlist must be what
    # suppresses it, not a coincidental exemption on path or suffix.
    line = "x = 1  # FIXME: replace with real client"
    assert offending([("src/app.py", 4, line)]) == ["src/app.py:4: " + line]
    assert offending([("src/app.py", 4, line + "  # gate: allow-placeholder")]) == []


# ---- exempt() — colocated JS/TS test-file conventions (review round 1) -----------------
def test_exempt_recognizes_colocated_and_jest_playwright_test_conventions():
    for path in (
        "frontend/src/x.test.ts",
        "frontend/e2e/foo.spec.ts",
        "src/__tests__/x.ts",
        "backend/tests/test_x.py",
        "conftest.py",
    ):
        assert exempt(path), f"expected exempt: {path}"
    for path in ("src/app.py", "frontend/src/dock.tsx"):
        assert not exempt(path), f"expected NOT exempt: {path}"


# ---- placeholder lookahead — JSX/object-key attributes vs. the real placeholder trigger ---
def test_placeholder_regex_ignores_attribute_and_key_uses():
    for line in (
        'placeholder="Search…"',
        'placeholder: "x"',
        'data-placeholder="y"',
    ):
        assert offending([("src/app.tsx", 1, line)]) == [], f"should not fire: {line}"


def test_placeholder_regex_still_catches_the_measured_true_positive():
    # The lines from repo B's production code that
    # fired in the 2026-09-06 blast-radius measurement — a real placeholder value shipped
    # in production code, not a false positive. Must still fire after the lookahead fix.
    assert offending([
        ("src/pkg/service.py", 6,
         "#: Placeholder written into every extracted record's ``score``."),
    ]) == ["src/pkg/service.py:6: #: Placeholder written into every extracted record's ``score``."]
    assert offending([
        ("src/pkg/service.py", 24,
         "#: Value of :data:`SCORE_BASIS` while the number is a placeholder."),
    ]) == ["src/pkg/service.py:24: #: Value of :data:`SCORE_BASIS` while the number is a placeholder."]


# ---- advisory rollout (review round 2) -------------------------------------------------
def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo_with_offending_line(tmp_path, monkeypatch):
    """A throwaway repo (real git, no mocks — pattern from test_orggate.py's tiny_repo)
    whose PR range adds one offending TODO line to non-test source."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "app.py").write_text("def f():\n    return 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()

    _git(root, "checkout", "-q", "-b", "feature")
    (root / "app.py").write_text("def f():\n    return {}  # TODO fill in later\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "pr change")

    monkeypatch.setenv("REPO_ROOT", str(root))
    monkeypatch.setenv("PR_BASE_SHA", base_sha)
    monkeypatch.delenv("ORG_GATE_PLACEHOLDER_ENFORCE", raising=False)
    return root


def test_advisory_default_warns_and_passes(repo_with_offending_line, capsys):
    # No exception raised — the offending TODO line is only warned about, not failed on.
    test_pr_adds_no_placeholder_lines(capsys)
    out = capsys.readouterr().out
    assert "::warning file=app.py,line=2::placeholder/mock/stub line added:" in out
    assert "TODO fill in later" in out
    assert "gate: allow-placeholder" in out


def test_enforce_env_fails_the_same_range(repo_with_offending_line, monkeypatch, capsys):
    monkeypatch.setenv("ORG_GATE_PLACEHOLDER_ENFORCE", "1")
    with pytest.raises(AssertionError, match="placeholder/mock/stub lines added"):
        test_pr_adds_no_placeholder_lines(capsys)
