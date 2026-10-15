"""Acceptance criteria for the org-gates composite action itself.

The org's contract-health gate asks every repo with tests/ to state its
acceptance criteria as executable contracts. These are this repo's: the two
properties that, if they regressed, would reintroduce the outages this repo's
gates exist to prevent.

C1 — the gates need no PAT. The upstream gates once ran on an org PAT secret;
when that token started returning 401, `org-conventions` and `Contract health`
went red on every non-Lean PR in the org at once. The composite action exists
so a consumer checks the gates out with its OWN GITHUB_TOKEN. A `secrets.`
reference creeping back into action.yml would restore the single point of
failure silently — the gate would still pass on the day it was added.

C2 — every suite the action accepts is documented. `suite:` is the action's
only behavioural input; an undocumented suite is one no consumer can adopt,
and a documented-but-unimplemented one fails at the consumer, not here.
"""
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION = REPO_ROOT / "actions" / "org-gates" / "action.yml"
DOCS = REPO_ROOT / "docs" / "org-gates.md"


def _suites() -> set[str]:
    """Suite names from the action's own case arms: `  name)  files="..."`."""
    source = ACTION.read_text(encoding="utf-8")
    return set(re.findall(r"^\s{8,}([a-z][a-z-]*)\)\s+files=", source, re.MULTILINE))


def test_action_requires_no_secret() -> None:
    source = ACTION.read_text(encoding="utf-8")
    leaked = re.findall(r"\$\{\{\s*secrets\.[A-Za-z_][A-Za-z0-9_]*\s*\}\}", source)
    assert not leaked, (
        f"actions/org-gates/action.yml references {leaked}. The action must run on "
        "the caller's own GITHUB_TOKEN — a PAT here is the org-PAT "
        "outage waiting to happen again."
    )


def test_no_caller_input_is_interpolated_into_a_run_body() -> None:
    """C3 — nothing caller-influenceable may reach a `run:` script as ${{ }} text.

    A `${{ inputs.x }}` inside `run:` is substituted textually before bash parses
    the line, so a consumer threading a workflow input into it can inject shell
    into every repo in the org. Inputs must arrive through `env:` instead. Found
    on this PR's own head (`suite` was interpolated into the case statement and
    the error message), which is why it is pinned here rather than trusted to
    review: a sibling action already followed the rule, so
    the inconsistency survived precisely because nothing checked it.
    """
    banned = re.compile(r"\$\{\{\s*(inputs|github\.event\.[A-Za-z_.]*(title|body|ref|name|label))")
    # Every composite action plus the two workflows this repo ships.
    scoped = [
        *(REPO_ROOT / "actions").rglob("action.yml"),
        REPO_ROOT / ".github" / "workflows" / "self-check.yml",
        REPO_ROOT / ".github" / "workflows" / "org-checks.yml",
    ]
    offenders: list[str] = []
    for path in [p for p in scoped if p.is_file()]:
        in_run = False
        run_indent = 0
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped:
                continue
            indent = len(line) - len(line.lstrip())
            if in_run and indent <= run_indent and not stripped.startswith("#"):
                in_run = False
            if re.match(r"^run:\s*\|?", stripped):
                in_run, run_indent = True, indent
                if banned.search(line):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {stripped[:90]}")
                continue
            if in_run and banned.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {stripped[:90]}")
    assert not offenders, (
        "caller-influenceable ${{ }} expansion inside a run: body — route it through env: instead:\n"
        + "\n".join(sorted(set(offenders)))
    )


def test_every_suite_is_documented() -> None:
    suites = _suites()
    assert suites, "parsed no suites out of action.yml — the case-arm shape changed"
    documented = DOCS.read_text(encoding="utf-8")
    missing = sorted(s for s in suites if s not in documented)
    assert not missing, f"suites accepted by the action but absent from docs/org-gates.md: {missing}"
