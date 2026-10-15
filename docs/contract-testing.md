# Contract Testing Guide

## What are contracts?

A contract is a pair of files that define what a feature must do:
- `contract.md` -- human-readable spec (goal, acceptance criteria, observability)
- `test_contract.py` -- machine-readable spec (pytest tests, start as xfail)

## Directory structure

```
tests/contracts/
    issue_NNN_short_name/
        __init__.py
        contract.md
        test_contract.py
```

## Lifecycle

1. **RED**: Write xfail tests defining acceptance criteria
2. **GREEN**: Implement feature, tests pass, remove xfail
3. **MONITOR**: Contract tests run in CI on every PR -- regressions caught immediately

## Writing a contract

### contract.md
- Goal: one sentence
- Acceptance criteria: bullet list (each maps to a test)
- Observability: what Logfire traces/metrics prove it works in prod
- Dependencies: what must land first

### test_contract.py
- All tests start `@pytest.mark.xfail(raises=AssertionError, reason="Issue #N: not implemented")`
- Use `@pytest.mark.integration` for tests needing live endpoints
- Remove xfail as each criterion is implemented

## CI enforcement

The org workflow checks:
- `tests/contracts/` exists if `tests/` exists
- At least one `test_*.py` file in contracts
- `[tool.mutmut]` configured in pyproject.toml
