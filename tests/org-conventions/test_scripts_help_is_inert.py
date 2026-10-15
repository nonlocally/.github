"""Org gate: `<script> --help` (and any unknown flag) must be INERT.

Measured origin (2026-09-06): a deploy script only parsed
--dry-run, so `--help` fast-forwarded main, ran docker build/rm/run — a live deploy from a
help request. Same class as a prune script that deleted backups on `--help`.

Method: run each script under scripts/ with --help inside a PATH sandbox where every
mutating tool is a stub that RECORDS the call to $HELP_SANDBOX_LOG and exits 1. Any recorded
call = gate failure. Scoped to scripts changed in the PR range so pre-existing debt does not
redden unrelated PRs — with no resolvable range there is nothing to gate, so no scripts run
(matches _orggate.changed_files and the org's PR-scope rule: scope to the PR's own change, never
the whole tree).

MEASURED FALSE-POSITIVE RATE (replay of 28 merged PRs across 12 repos inside ubuntu:24.04,
2026-09-06): 14 of 28 exercised PRs went red, of which only 2 were real (one script
filed a GitHub issue from `--help`; another ran `gcloud services enable` against
a live project). The other 12 — 43% of exercised PRs, 86% of all reds — split into exactly two
causes, both fixed here:

  A. a READ-ONLY invocation of a tool on MUTATING_TOOLS (6): `gh auth token`, `gh auth status`,
     `docker ps --filter`, `launchctl list`, `git rev-parse`/`git status`, `rm -f` of the
     script's own mktemp scratch file. Fixed by `is_read_only()` below: the stub still RECORDS
     every call, and the recorded ARGUMENTS decide whether it was a mutation.
  B. `--help` was inert but exited non-zero (6): usage printed with `exit 1`, or a missing
     credential/binary refused early. An exit code is a convention, not the safety property
     this gate is named for. The `returncode` check is now advisory-only — it warns, never fails.

ADVISORY ROLLOUT: with A and B fixed the sampled false-positive count is 1 of 28 (a script whose
`--help` `git init`s a throwaway repo) and both true positives still bite. That is measured on 28
PRs, not on org traffic, so the mutating-call assertion is ADVISORY by default — offending calls
print as `::warning` annotations and the test PASSES — until `ORG_GATE_HELP_ENFORCE=1`/`true` is
set in the job's environment, threaded the same consumer -> org-checks.yml -> actions/org-gates
path as `ORG_GATE_PLACEHOLDER_ENFORCE`. The flip is a one-line per-repo opt-in, not an
org-checks.yml edit, so it never flips every consumer at once.

KNOWN SANDBOX HOLE (not a false positive, do not read this gate as proving more than it does):
the sandbox stubs PATH binaries only. In-process mutation is invisible to it — `shutil.rmtree`,
`requests.post`, a neo4j driver write, and, measured on one consumer, a `urllib` HTTPS call to
a production service that ran three times (once per flag) and passed. Enabling this
gate means every PR touching `scripts/` executes that PR's own code from CI, with network.

Run by reusable workflow .github/workflows/org-checks.yml (suite: conventions) on every PR.
To run locally:  REPO_ROOT=<repo> pytest tests/org-conventions/test_scripts_help_is_inert.py -v --timeout=30
"""
from __future__ import annotations

import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

import pytest

from _orggate import repo_root, range_base, changed_files

MUTATING_TOOLS = (
    "docker", "kubectl", "gcloud", "ssh", "scp", "rsync", "rclone", "launchctl",
    "systemctl", "rm", "mv", "curl", "wget", "gh", "git", "pip", "npm", "uv",
    "sudo", "doas",
)
HELP_FLAGS = ("--help", "-h", "--definitely-not-a-real-flag")
SCRIPT_GLOBS = ("scripts/**/*.sh", "scripts/**/*.py", "scripts/*.sh", "scripts/*.py")

# Measured 2026-09-06 (final-review Finding 1): the org-conventions job runs
# each changed script under a bare /usr/bin/python3 with no consumer
# dependencies installed and cwd=script.parent on its own sys.path — 8.4% of
# one consumer's scripts/**/*.py import a module unresolvable there (pint,
# z3, logfire, gdsfactory, sax, lean_interact, sibling packages). That is a
# missing-dependency problem in THIS gate's sandbox, not a --help side
# effect, so it must not fail the same way a real mutating call does.
MISSING_DEP_RE = re.compile(r"ModuleNotFoundError|ImportError|No module named")

# A tool being on MUTATING_TOOLS says only that it CAN mutate. These first-argument
# subcommands cannot — each was a measured false positive (bucket A above). Deliberately
# a subcommand allowlist, never a denylist: an unrecognised `gh <verb>` stays a failure.
READ_ONLY_SUBCOMMANDS = {
    "gh": {"auth"},                    # `gh auth status|token` — reads a credential
    "docker": {"ps", "images", "inspect", "info", "version", "logs"},
    "kubectl": {"get", "describe", "logs", "version"},
    "launchctl": {"list", "print"},
    "systemctl": {"status", "is-active", "is-enabled", "show", "list-units"},
    "git": {"rev-parse", "status", "log", "show", "diff", "describe", "ls-files",
            "symbolic-ref"},           # NOT branch/config/remote — those have writing forms
    "pip": {"show", "list", "freeze"},
    "npm": {"ls", "view"},
}
# `rm` of a path the script itself created under the temp dir is self-owned cleanup, not a
# side effect on the world. Anything outside temp — including a bare `rm -rf /x` — still fails.
_TEMP_PREFIXES = ("/tmp/", "/var/folders/", "/private/tmp/", "/private/var/folders/")


def is_read_only(call: str) -> bool:
    """True when a RECORDED sandbox call could not have mutated anything outside the process.

    `call` is one sandbox log line: '<tool> <args…>'. Classification is by ARGUMENTS, because
    the tool name alone put 6 of 12 measured false positives on the board.
    """
    try:
        parts = shlex.split(call)
    except ValueError:
        return False  # unparseable quoting — refuse to call it safe
    if not parts:
        return False
    tool, args = parts[0], parts[1:]
    if tool == "rm":
        paths = [a for a in args if not a.startswith("-")]
        # normpath first: '/tmp/../etc' starts with '/tmp/' as a STRING but names /etc.
        return bool(paths) and all(
            os.path.normpath(p).startswith(_TEMP_PREFIXES) for p in paths
        )
    sub = next((a for a in args if not a.startswith("-")), None)
    return sub is not None and sub in READ_ONLY_SUBCOMMANDS.get(tool, ())


def mutating_calls(calls: list[str]) -> list[str]:
    return [c for c in calls if not is_read_only(c)]


def enforcing() -> bool:
    return os.environ.get("ORG_GATE_HELP_ENFORCE", "").strip().lower() in ("1", "true")


def changed_scripts(root: Path, base: str | None) -> list[Path]:
    """Scripts under scripts/ that the PR range touched.

    With no resolvable base there is no range to gate, so this returns [] — same
    as _orggate.changed_files and the org's PR-scope rule (scope to the PR's own
    change, never the whole tree). It is NOT a full-repo sweep fallback.
    """
    if base is None:
        return []
    candidates = sorted({p for g in SCRIPT_GLOBS for p in root.glob(g) if p.is_file()})
    changed = set(changed_files(root, base))
    return [p for p in candidates if p in changed]


def make_sandbox(tmp_path: Path) -> tuple[Path, Path]:
    """PATH dir of stubs; each stub appends '<tool> <args>' to the log and exits 1."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    for tool in MUTATING_TOOLS:
        stub = bin_dir / tool
        stub.write_text(f'#!/bin/sh\necho "{tool} $*" >> "$HELP_SANDBOX_LOG"\nexit 1\n')
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir, log


def run_help(script: Path, flag: str, bin_dir: Path, log: Path) -> subprocess.CompletedProcess:
    interp = ["bash"] if script.suffix == ".sh" else ["python3"]
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",  # stubs shadow the real tools
        "HELP_SANDBOX_LOG": str(log),
        "HOME": str(bin_dir.parent),
    }
    return subprocess.run(interp + [str(script), flag], cwd=script.parent, env=env,
                          capture_output=True, text=True, timeout=20)


def _scripts_param():
    root = repo_root()
    return [pytest.param(p, id=str(p.relative_to(root))) for p in changed_scripts(root, range_base(root))]


def evaluate_help_result(script: Path, flag: str, proc: subprocess.CompletedProcess, calls: list[str]) -> list[str]:
    """Return the GH `::warning` annotations this run earned.

    Raises only when a genuinely mutating call was recorded AND `ORG_GATE_HELP_ENFORCE` is
    set. A non-zero exit is never a failure on its own (measured bucket B): six of twelve
    false positives were an inert `--help` that printed usage and exited 1, or refused early
    on a missing credential. The exit code is reported, not enforced.
    """
    warnings: list[str] = []
    bad = mutating_calls(calls)
    if bad:
        msg = (
            f"{script.name} {flag} invoked mutating tools: {bad[:5]} — a help/unknown-flag "
            f"request must exit before any side effect (a help request once ran a live deploy)."
        )
        if enforcing():
            assert False, msg
        warnings.append(f"::warning file={script}::{msg}")
    if flag in ("--help", "-h") and proc.returncode != 0:
        dep_line = next(
            (l for l in proc.stderr.splitlines() if MISSING_DEP_RE.search(l)), ""
        )
        why = f"missing dependency ({dep_line})" if dep_line else (proc.stderr.strip()[-200:] or "no stderr")
        warnings.append(
            f"::warning file={script}::--help exited {proc.returncode}: {why} — inert, so not "
            f"a gate failure; a help arm that prints usage should exit 0"
        )
    return warnings


@pytest.mark.parametrize("script", _scripts_param())
@pytest.mark.parametrize("flag", HELP_FLAGS)
def test_help_touches_no_mutating_tool(script: Path, flag: str, tmp_path: Path):
    bin_dir, log = make_sandbox(tmp_path)
    proc = run_help(script, flag, bin_dir, log)
    calls = log.read_text().splitlines() if log.exists() else []
    for warning in evaluate_help_result(script, flag, proc, calls):
        print(warning)


# ---- positive control: the gate itself must bite --------------------------------------
def test_gate_bites_on_a_script_whose_help_runs_docker(tmp_path: Path):
    bad = tmp_path / "bad.sh"
    bad.write_text('#!/bin/bash\ncase "${1:-}" in --dry-run) DRY=1;; esac\ndocker build .\n')
    bin_dir, log = make_sandbox(tmp_path)
    run_help(bad, "--help", bin_dir, log)
    assert log.read_text().startswith("docker build ."), "sandbox did not record the docker call"


def test_gate_bites_on_a_script_whose_help_runs_sudo(tmp_path: Path):
    # ubuntu-latest runners grant the runner user passwordless sudo — a script that
    # shells out via sudo would otherwise escape the PATH sandbox entirely.
    bad = tmp_path / "bad_sudo.sh"
    bad.write_text('#!/bin/bash\ncase "${1:-}" in --dry-run) DRY=1;; esac\nsudo rm -rf /x\n')
    bin_dir, log = make_sandbox(tmp_path)
    run_help(bad, "--help", bin_dir, log)
    assert log.read_text().startswith("sudo rm -rf /x"), "sandbox did not record the sudo call"


# ---- unit test: no resolvable range means no scripts, not all scripts -----------------
def test_changed_scripts_returns_empty_when_base_is_none(tmp_path: Path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "anything.sh").write_text("#!/bin/bash\necho hi\n")
    assert changed_scripts(tmp_path, None) == []


def test_gate_passes_a_script_with_a_real_help_arm(tmp_path: Path):
    good = tmp_path / "good.sh"
    good.write_text('#!/bin/bash\ncase "${1:-}" in -h|--help) echo usage; exit 0;; --dry-run) ;; *) echo "unknown flag" >&2; exit 2;; esac\ndocker build .\n')
    bin_dir, log = make_sandbox(tmp_path)
    p = run_help(good, "--help", bin_dir, log)
    assert p.returncode == 0 and not log.exists()
    p2 = run_help(good, "--definitely-not-a-real-flag", bin_dir, log)
    assert p2.returncode == 2 and not log.exists()


# ---- advisory: a non-zero --help exit is reported, never failed (measured bucket B) ----
def test_gate_warns_and_passes_on_help_that_fails_only_on_a_missing_dependency(tmp_path: Path, capsys):
    script = tmp_path / "needs_dep.py"
    script.write_text(
        "import definitely_missing_module_xyz\n"
        "import sys\n"
        "if len(sys.argv) > 1 and sys.argv[1] in ('--help', '-h'):\n"
        "    print('usage: needs_dep.py')\n"
    )
    bin_dir, log = make_sandbox(tmp_path)
    proc = run_help(script, "--help", bin_dir, log)
    calls = log.read_text().splitlines() if log.exists() else []
    warnings = evaluate_help_result(script, "--help", proc, calls)  # must not raise
    assert warnings and "missing dependency" in warnings[0]
    assert "definitely_missing_module_xyz" in warnings[0]


def test_usage_printed_with_a_nonzero_exit_is_not_a_failure(tmp_path: Path):
    # Measured: a chat script's --help PRINTS ITS USAGE and exits 1.
    # Under the old returncode==0 assertion that was a gate failure; it is now one warning.
    script = tmp_path / "usage_exit1.sh"
    script.write_text('#!/bin/bash\necho "usage: $0 [--flag]" >&2\nexit 1\n')
    bin_dir, log = make_sandbox(tmp_path)
    proc = run_help(script, "--help", bin_dir, log)
    warnings = evaluate_help_result(script, "--help", proc, [])  # must not raise
    assert len(warnings) == 1 and "exited 1" in warnings[0]


def test_gate_still_fails_when_a_missing_dependency_help_also_runs_docker(tmp_path: Path, monkeypatch):
    # The docker call must happen BEFORE the import so it is actually recorded — this
    # proves the mutating-call check still bites even though stderr also carries a
    # ModuleNotFoundError; the exit-code advisory only ever adds a warning.
    monkeypatch.setenv("ORG_GATE_HELP_ENFORCE", "1")
    script = tmp_path / "needs_dep_and_docker.py"
    script.write_text(
        "import subprocess\n"
        "subprocess.run(['docker', 'build', '.'])\n"
        "import definitely_missing_module_xyz\n"
    )
    bin_dir, log = make_sandbox(tmp_path)
    proc = run_help(script, "--help", bin_dir, log)
    calls = log.read_text().splitlines() if log.exists() else []
    assert calls, "sandbox did not record the docker call"
    with pytest.raises(AssertionError, match="invoked mutating tools"):
        evaluate_help_result(script, "--help", proc, calls)


def test_advisory_default_warns_instead_of_failing_on_a_real_mutating_call(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ORG_GATE_HELP_ENFORCE", raising=False)
    script = tmp_path / "deploys.sh"
    script.write_text('#!/bin/bash\ndocker build .\n')
    bin_dir, log = make_sandbox(tmp_path)
    proc = run_help(script, "--help", bin_dir, log)
    calls = log.read_text().splitlines()
    warnings = evaluate_help_result(script, "--help", proc, calls)  # must not raise
    assert any("invoked mutating tools" in w and w.startswith("::warning file=") for w in warnings)


# ---- read-only classification: the 6 measured bucket-A false positives ------------------
@pytest.mark.parametrize("call", [
    "gh auth token --user octocat",
    "gh auth status",
    "docker ps --filter name=web",
    "launchctl list",
    "git rev-parse --abbrev-ref HEAD",
    "git status --porcelain",
    "rm -f /tmp/tmp.A1b2C3",                   # self-owned mktemp scratch
])
def test_measured_false_positives_are_classified_read_only(call):
    assert is_read_only(call), call
    assert mutating_calls([call]) == []


@pytest.mark.parametrize("call", [
    "gh issue create --title x",               # the origin defect
    "gcloud services enable run.googleapis.com",  # the other measured true positive
    "docker build .",
    "docker rm -f web",
    "rm -rf /x",                               # outside temp
    "rm -rf /tmp/../etc",                      # not a temp prefix after the literal check
    "sudo rm -rf /x",
    "git init",                                # creates a repo — not on the read-only list
    "git push origin main",
    "kubectl delete pod x",
    "git config user.email x@y",               # config/branch/remote have writing forms
    "git branch -D main",
    "rm -f",                                   # no path argument
])
def test_mutating_calls_stay_mutating(call):
    assert not is_read_only(call), call
    assert mutating_calls([call]) == [call]


def test_unparseable_quoting_is_never_called_read_only():
    assert not is_read_only('gh auth "unclosed')
