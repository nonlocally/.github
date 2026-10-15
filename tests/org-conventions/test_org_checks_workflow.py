"""Static checks on the reusable workflow every consumer calls (`org-checks.yml`).

Measured origin (upstream review, 2026-09-06): `placeholder-enforce` was declared as a
`workflow_call` input with no `type:`. GitHub's syntax reference requires `type` on every
`workflow_call` input and actionlint reports it as a syntax error — a consumer calling
`org-checks.yml@main` would have had the whole reusable workflow rejected, for every
consumer at once. Nothing in CI exercised that path: `self-check.yml` calls
`actions/org-gates` directly and no job calls `org-checks.yml` via `workflow_call`.

Run locally: pytest tests/org-conventions/test_org_checks_workflow.py -v --timeout=30
"""
from pathlib import Path

import yaml

ORG_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ORG_ROOT / ".github" / "workflows" / "org-checks.yml"
# The values GitHub accepts for a workflow_call input's `type`.
WORKFLOW_CALL_INPUT_TYPES = {"boolean", "number", "string"}


def _workflow_call_inputs() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text())
    # PyYAML parses the bare key `on` as boolean True (YAML 1.1); accept either spelling.
    on = doc.get("on", doc.get(True))
    return on["workflow_call"]["inputs"]


def test_every_workflow_call_input_declares_a_valid_type():
    inputs = _workflow_call_inputs()
    assert inputs, "org-checks.yml declares no workflow_call inputs — did the file move?"
    missing = {name: spec for name, spec in inputs.items() if "type" not in spec}
    assert not missing, f"workflow_call inputs without `type:` (GitHub rejects the workflow): {sorted(missing)}"
    bad = {name: spec["type"] for name, spec in inputs.items() if spec["type"] not in WORKFLOW_CALL_INPUT_TYPES}
    assert not bad, f"workflow_call inputs with an invalid `type:`: {bad}"


def test_enforce_inputs_are_strings_so_consumers_can_pass_the_documented_quoted_true():
    # The docs tell a consumer to pass `placeholder-enforce: "true"` — a string. If the type
    # were `boolean`, GitHub would reject that quoted value at the call site.
    inputs = _workflow_call_inputs()
    for name in ("placeholder-enforce", "help-enforce"):
        assert inputs[name]["type"] == "string", f"{name} must be a string input"
        assert inputs[name]["default"] == "false"
