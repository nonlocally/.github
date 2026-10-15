"""The org-gates action's exact pytest invocation must deliver the advisory `::warning`s.

Measured origin (upstream review, 2026-09-06): both advisory gates emit their `::warning`
annotations via `print()` inside a PASSING test. `actions/org-gates/action.yml` ran pytest
with default output capture, so pytest swallowed every one of them — measured 0 warning lines
with the action's flags against 7 (help gate) and 2 (placeholder gate) with capture off. The
"warn until a repo opts in" rollout therefore produced nothing a consumer could observe.

The existing capsys tests prove the warning STRING is built; these prove it reaches the job
log. Each test builds a throwaway repo whose PR range trips one gate, then runs that gate the
way the action does — the `run:` line is read from action.yml itself, so a flag change there
is what this test measures, not a copy of it.

Run locally: pytest tests/org-conventions/test_action_invocation.py -v --timeout=30
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ACTION = HERE.parents[1] / "actions" / "org-gates" / "action.yml"


def action_pytest_argv(gate_file: Path) -> list[str]:
    """The action's `run: pytest ...` line, with its two env placeholders substituted."""
    run_lines = [l.strip() for l in ACTION.read_text().splitlines() if l.strip().startswith("run: pytest ")]
    assert len(run_lines) == 1, f"expected exactly one `run: pytest` step in action.yml, found {run_lines}"
    argv = shlex.split(run_lines[0][len("run: "):])
    out = []
    for a in argv:
        if a == "$GATE_FILES":
            out.append(str(gate_file))
        else:
            out.append(a.replace("$GATE_ROOTDIR", str(HERE)))
    return out


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _pr_repo(tmp_path: Path, pr_files: dict[str, str]) -> Path:
    """main with one base commit; `feature` adds/changes `pr_files`; origin/main = base tip."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("base\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    _git(root, "update-ref", "refs/remotes/origin/main", base)
    _git(root, "checkout", "-q", "-b", "feature")
    for rel, text in pr_files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "pr change")
    return root


def _run_gate_like_the_action(gate_file: Path, root: Path) -> subprocess.CompletedProcess:
    env = {
        **{k: v for k, v in os.environ.items() if k not in ("PR_BASE_SHA", "BASE_REF", "PR_BASE_REF",
                                                           "ORG_GATE_PLACEHOLDER_ENFORCE", "ORG_GATE_HELP_ENFORCE")},
        "REPO_ROOT": str(root),
        "GITHUB_BASE_REF": "main",
    }
    return subprocess.run(action_pytest_argv(gate_file), cwd=root, env=env, capture_output=True, text=True, timeout=120)


def test_action_invocation_surfaces_the_placeholder_gate_warning(tmp_path: Path):
    root = _pr_repo(tmp_path, {"app.py": "def f():\n    return {}  # TODO fill in later\n"})
    proc = _run_gate_like_the_action(HERE / "test_no_placeholders_added.py", root)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]  # advisory: passes
    assert "::warning file=app.py,line=2::placeholder/mock/stub line added:" in proc.stdout, (
        "the advisory annotation was built but never reached the job log:\n" + proc.stdout[-3000:]
    )


def test_action_invocation_surfaces_the_help_gate_warning(tmp_path: Path):
    root = _pr_repo(tmp_path, {
        "scripts/deploy.sh": '#!/bin/bash\ncase "${1:-}" in --dry-run) DRY=1;; esac\ndocker build .\n',
    })
    proc = _run_gate_like_the_action(HERE / "test_scripts_help_is_inert.py", root)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]  # advisory: passes
    assert "::warning file=" in proc.stdout and "deploy.sh --help invoked mutating tools" in proc.stdout, (
        "the advisory annotation was built but never reached the job log:\n" + proc.stdout[-3000:]
    )
