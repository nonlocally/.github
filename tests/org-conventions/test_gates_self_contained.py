"""This repo is public and its gates run in other repos' CI, so they must work from this tree alone.

The gate action resolves its test files relative to its own checkout. Anything the action or
the reusable workflow names must therefore exist here, and every reference to the action must
point at this repo, never at a private one a public caller cannot read.

Run locally: pytest tests/org-conventions/test_gates_self_contained.py -v --timeout=30
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / "actions" / "org-gates" / "action.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "org-checks.yml"
GATES = ROOT / "tests" / "org-conventions"


def _suite_files() -> dict[str, list[str]]:
    """The `case` arms in action.yml: suite name -> the gate files it runs."""
    arms = re.findall(r"^\s*([a-z-]+)\)\s+files=\"([^\"]+)\";;", ACTION.read_text(), re.M)
    assert arms, "no suite arms found in action.yml"
    return {suite: names.split() for suite, names in arms}


def test_every_gate_file_the_action_runs_exists_here():
    missing = [f"{s}: {n}" for s, names in _suite_files().items() for n in names if not (GATES / n).is_file()]
    assert not missing, f"action.yml runs gate files this repo does not ship: {missing}"


def test_the_action_reads_nothing_outside_this_tree():
    # The upstream original required an org instructions file beside the action; this repo has none.
    assert "CLAUDE.md" not in ACTION.read_text()


def test_reusable_workflow_calls_this_repos_action():
    steps = [s for job in yaml.safe_load(WORKFLOW.read_text())["jobs"].values() for s in job["steps"]]
    gate_uses = [s["uses"] for s in steps if "org-gates" in s.get("uses", "")]
    assert gate_uses, "org-checks.yml no longer calls the org-gates action"
    wrong = [u for u in gate_uses if not u.startswith("nonlocally/.github/actions/org-gates@")]
    assert not wrong, f"org-checks.yml calls an org-gates action outside this repo: {wrong}"


def test_repo_tests_job_keeps_the_inputs_callers_rely_on():
    # Callers pass a test dir plus a list of --ignore flags; without them a large unit suite
    # runs twice and hits the job's timeout, which then concludes `cancelled`.
    doc = yaml.safe_load(WORKFLOW.read_text())
    inputs = doc.get("on", doc.get(True))["workflow_call"]["inputs"]   # PyYAML reads bare `on` as True
    for name in ("test-dirs", "pytest-extra-args"):
        assert name in inputs, f"workflow_call input {name!r} is gone"
        assert (inputs[name]["type"], inputs[name]["default"]) == ("string", ""), name
    job = doc["jobs"]["repo-tests"]
    assert job["timeout-minutes"] >= 10
    step = next(s for s in job["steps"] if "PYTEST_EXTRA_ARGS" in s.get("env", {}))
    bound = {k: "".join(v.split()) for k, v in step["env"].items()}
    assert bound["TEST_DIRS"] == "${{inputs.test-dirs}}"
    assert bound["PYTEST_EXTRA_ARGS"] == "${{inputs.pytest-extra-args}}"
    # Unquoted on purpose ($X or ${X}): the shell must split the string into separate pytest arguments.
    assert re.search(r'(?<!")\$(?:\{PYTEST_EXTRA_ARGS\}|PYTEST_EXTRA_ARGS\b)(?!")', step["run"]), step["run"]


def test_repo_tests_job_skips_when_a_caller_passes_no_test_dirs():
    # A caller whose own required job already runs its unit tests passes no test-dirs, and
    # the duplicate run must then not start at all.
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["repo-tests"]
    assert "".join(str(job.get("if", "")).split()) == "inputs.test-dirs!=''"
