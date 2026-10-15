# Org gates

The `conventions` suite of `nonlocally/.github/actions/org-gates` (called from every
consumer via the reusable workflow `.github/workflows/org-checks.yml`) runs four gates on
every pull request. All four are **scoped to the PR's own range** — the diff between the
PR's base and head — never a full-repo sweep, so pre-existing debt in a repo only surfaces
when a PR actually touches it (see `tests/org-conventions/_orggate.py`).

This page documents what each gate checks, how it fails, and its escape hatch. The escape
hatches are `.confidential-allow` and `# gate: allow-placeholder` — nothing else in this
suite has one.

## help-inert

**File**: `tests/org-conventions/test_scripts_help_is_inert.py`

**Checks**: every script under `scripts/**` that the PR *changed*, run with `--help`, `-h`,
and one made-up flag (`--definitely-not-a-real-flag`), inside a `PATH` sandbox where every
mutating tool (`docker`, `kubectl`, `gcloud`, `ssh`, `rm`, `git`, `gh`, `pip`, `sudo`, …) is a
stub that records the call and exits 1. A help or unknown-flag request must exit **before**
touching any of them — measured origin: a deploy script only parsed `--dry-run`,
so `--help` fell through to a live `docker build/rm/run`.

**Scope**: only scripts changed in the PR range.

**Fails when**: a mutating tool is invoked during a help/unknown-flag run AND the consumer
has opted into enforcement (`help-enforce: "true"`); until then the finding is a `::warning`
annotation and the job passes. A non-zero `--help`/`-h` exit is **never** a failure: it is
reported as a `::warning` (with the reason — a missing dependency in the gate's bare sandbox,
or the script's own stderr) so a help arm that prints usage and exits 1 can be fixed, but it
is not the side-effect property this gate is named for. Measured origin of that split: six of
twelve false positives in the 28-PR replay were inert `--help`s that exited non-zero.

**Sandbox dependencies (why `--help` may exit non-zero here and nowhere else)**: the gate runs
scripts under a bare `/usr/bin/python3` with none of the consumer's own dependencies
installed. Measured on one consumer: 8.4% of `scripts/**/*.py` import a module
(`pint`, `z3`, `logfire`, `gdsfactory`, …) that a bare interpreter can't resolve. The warning
names the missing module; the script's help arm may still deserve a real fix (make it
import-free, or install the dependency where the gate can see it).

**No escape hatch** — fix the script's help arm (parse `--help`/`-h`/unknown flags before any
mutating call) or its imports.

## confidential-blobs

**File**: `tests/org-conventions/test_no_confidential_blobs.py`

**Checks**: every file the PR **adds** (not modifies — pre-existing committed history is a
separate cleanup) that is either (a) a binary larger than 1 MiB, (b) a `.pdf`/`.docx`/
`.pptx` whose extracted text matches a confidentiality marker (`confidential`, `privileged`,
`trade secret`, `proprietary and confidential`, …), or (c) private-key material: a
`-----BEGIN … PRIVATE KEY-----` PEM header anywhere in the first 8 KiB (any suffix), or a
binary keystore by suffix (`.p12`, `.pfx`, `.jks`, `.keystore`). Public certificates, public
keys and CSRs do not match. Measured origin: a long PDF containing other institutions' forms,
self-described as privileged, was committed to a project repo.

**Scope**: only files added in the PR range.

**Fails when**: a matching marker is found in an added document, an added binary exceeds
1 MiB, or an added file is private-key material. A document that can't be text-extracted (corrupt or encrypted) also fails — closed,
not open — with a message asking for manual review, since it can't be waved through either.

**Escape hatch**: `.confidential-allow` at the repo root — one POSIX-style path per line,
relative to the repo root (no leading `./`, no backslashes), for a file that legitimately
belongs in the repo despite tripping any of the checks above. Every failure message names
this file directly.

## placeholders (advisory)

**File**: `tests/org-conventions/test_no_placeholders_added.py`

**Checks**: every line the PR **adds** to non-test source (`.py`, `.ts`, `.tsx`, `.js`,
`.svelte`, `.go`, `.rs`, `.sh`, `.lean`) for `TODO`/`FIXME`/`XXX`/`HACK`, `placeholder` (not
an attribute/key use like `placeholder="…"`), `mock*`/`stub*`, `NotImplementedError()`, or a
stub `return {}`/`[]`/`None`  comment. Mechanizes the org's no-placeholder rule.
Test files, docs, fixtures, and a handful of other directories are exempt.

**Scope**: only lines added in the PR range.

**Fails when**: `ORG_GATE_PLACEHOLDER_ENFORCE` is set (`1`/`true`) AND an offending line was
added. **By default this gate is advisory** — offending lines are printed as `::warning`
GitHub annotations and the test passes regardless, because a 2026-09-06 measurement across
60 merged PRs across three repos found a ~5% false-positive rate, too high to fail real PRs
outright.

**`placeholder-enforce` flag — the real flip path**: `ORG_GATE_PLACEHOLDER_ENFORCE` is set
from the `placeholder-enforce` input, threaded consumer → `org-checks.yml` (`workflow_call`
input, default `"false"`) → `actions/org-gates` (composite input, same default) → the test
process's environment. Flipping it is a **one-line, per-repo opt-in** on the consumer's own
caller workflow:

```yaml
jobs:
  org-checks:
    uses: nonlocally/.github/.github/workflows/org-checks.yml@main
    with:
      placeholder-enforce: "true"
```

This does **not** touch `org-checks.yml` itself and does not flip every consumer at once —
each repo opts in independently once its own measured warning rate looks clean.

**Escape hatch**: append `# gate: allow-placeholder` to the line — it is grep-able and shows
up in the diff during review.

## pr-conventions

**File**: `tests/org-conventions/test_pr_conventions.py`

**Checks**: a bundle of RED-spec/TDD and repo-hygiene conventions from the org's agent instructions — no
all-skipped test files, `xfail` markers carry a reason, no empty test files, no generic
`MagicMock` in spec-quality-sensitive code, error-path coverage on contract tests, no `mock`
usage outside test files, no API keys/secrets in source or config, conventional-commit
subject lines on recent commits (with a Copilot-initial-plan exemption), and a sane
`pytest` timeout in `pyproject.toml`.

**Scope**: commits in the PR's window (base..HEAD), excluding base-branch history.

**Fails when**: any of the above conventions is violated. No dedicated escape hatch beyond
fixing the violation — this gate predates the confidential/placeholder gates and does not use
`.confidential-allow` or `# gate: allow-placeholder`.

## contract-health (second suite)

**File**: `tests/org-conventions/test_contract_health.py`, selected with
`suite: contract-health` on `actions/org-gates` (the `conventions` suite above is the
default; these are the only two suites the action accepts).

**Checks**: that a repo carrying `tests/` also carries `tests/contracts/` with at least one
`test_*.py`, and that a Python repo configuring `[tool.pytest…]` also configures
`[tool.mutmut]` with a non-empty `paths_to_mutate`.

**Scope**: repo-wide, NOT PR-scoped — unlike the four `conventions` gates, this one asks a
question about the repo's shape, which a diff cannot answer. A repo adopting it therefore
goes red until it complies, which is why it is a separate suite rather than a fifth gate.

**Fails when**: `tests/` exists without `tests/contracts/`, that directory holds no test
files, or pytest is configured without mutmut. Each skips cleanly when its precondition is
absent (no `tests/`, no `pyproject.toml`, a non-pytest runner). No escape hatch — the remedy
is to add the contract tests or the mutmut config, both named in the failure message.

**This repo's own compliance**: `tests/contracts/test_org_gate_contracts.py` (the composite
action must reference no `secrets.*`, must not interpolate caller input into a `run:` body,
and every suite it accepts must appear on this page). This repo has no `pyproject.toml`, so
the mutmut checks skip. `self-check.yml` runs this gate against the repo itself.


---

## repo-tests (optional job)

**Where**: the `repo-tests` job of `.github/workflows/org-checks.yml`, not part of either suite.

**Inputs**: `test-dirs` (space-separated directories, default empty) and `pytest-extra-args`
(default empty). For each directory in `test-dirs` that exists, the job runs
`pytest <dir> -v --timeout=30 --tb=short` followed by `pytest-extra-args`, unquoted so the shell
splits it into separate arguments (so an argument cannot itself contain a space). The job has a
10-minute timeout.

**Skips when**: `test-dirs` is empty. A caller whose own required job already runs its tests
should leave it empty rather than run the suite twice.
