"""Org convention: repos with tests must have contract tests and mutmut config.

These checks run on every PR across the org via the reusable workflow.
They ensure repos follow the contract-driven development pattern.
"""
import os
from pathlib import Path
import pytest

REPO_ROOT = Path(os.environ.get("REPO_ROOT", "."))


class TestContractHealth:
    """Every repo with tests should have contract tests."""

    def test_contracts_dir_exists_if_tests_exist(self):
        """If a repo has tests/, it should have tests/contracts/."""
        tests_dir = REPO_ROOT / "tests"
        if not tests_dir.is_dir():
            pytest.skip("No tests/ directory — not a testable repo")
        contracts_dir = tests_dir / "contracts"
        assert contracts_dir.is_dir(), (
            "tests/ exists but tests/contracts/ does not. "
            "Add contract tests for open issues. See: "
            "https://github.com/nonlocally/.github/blob/main/docs/contract-testing.md"
        )

    def test_contracts_dir_has_test_files(self):
        """Contract directory must have at least one test file."""
        contracts_dir = REPO_ROOT / "tests" / "contracts"
        if not contracts_dir.is_dir():
            pytest.skip("No tests/contracts/ directory")
        test_files = list(contracts_dir.glob("**/test_*.py"))
        assert len(test_files) > 0, (
            "tests/contracts/ exists but has no test_*.py files. "
            "Add contract tests defining acceptance criteria for open issues."
        )


class TestMutmutHealth:
    """Python repos with tests should have mutation testing configured."""

    def test_mutmut_configured_if_python_project(self):
        """If pyproject.toml has pytest config, mutmut should be configured too."""
        pyproject = REPO_ROOT / "pyproject.toml"
        if not pyproject.is_file():
            pytest.skip("No pyproject.toml — not a Python project")
        content = pyproject.read_text()
        if "[tool.pytest" not in content:
            pytest.skip("No pytest config — tests may use a different runner")
        assert "[tool.mutmut]" in content, (
            "Python project with pytest but no mutmut config. "
            "Add [tool.mutmut] to pyproject.toml. See: "
            "https://github.com/nonlocally/.github/blob/main/docs/contract-testing.md#ci-enforcement"
        )

    def test_mutmut_paths_not_empty(self):
        """mutmut paths_to_mutate must list at least one source path."""
        pyproject = REPO_ROOT / "pyproject.toml"
        if not pyproject.is_file():
            pytest.skip("No pyproject.toml")
        content = pyproject.read_text()
        if "[tool.mutmut]" not in content:
            pytest.skip("No mutmut config")
        assert "paths_to_mutate" in content, (
            "mutmut configured but paths_to_mutate not set. "
            "List source directories to mutate."
        )
