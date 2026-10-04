# ABOUTME: Tests exact-block lint debt exceptions and failing tool execution.
# ABOUTME: Uses real temporary source files and replaces only the external Ruff process.
import hashlib
import json
import subprocess

import pytest

import ci_lint


@pytest.fixture
def lint_repository(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/lint-baseline.json").write_text("[]")
    return tmp_path


@pytest.mark.parametrize(
    "source,baseline_source,code,expected",
    [
        pytest.param("import sys\nimport os\n", "import sys\nimport os\n", "I001", 0,
                     id="unchanged-debt"),
        pytest.param("import sys\nimport os\nimport json\n", "import sys\nimport os\n", "I001", 1,
                     id="changed-existing-block"),
        pytest.param("import sys\nimport os\n", None, "I001", 1,
                     id="new-unsorted-block"),
        pytest.param("print(missing_name)\n", "print(missing_name)\n", "F821", 1,
                     id="core-finding-cannot-be-baselined"),
    ],
)
def test_lint_rejects_regressions_but_allows_exact_import_debt(
    lint_repository, monkeypatch, capsys, source, baseline_source, code, expected
):
    path = lint_repository / "example.py"
    path.write_text(source)
    if baseline_source is not None:
        (lint_repository / "scripts/lint-baseline.json").write_text(json.dumps([
            {"path": "example.py", "sha256": hashlib.sha256(baseline_source.encode()).hexdigest()}
        ]))
    finding = {
        "filename": str(path),
        "code": code,
        "message": "Import block is un-sorted" if code == "I001" else "Undefined name",
        "location": {"row": 1},
        "end_location": {"row": len(source.splitlines())},
    }
    result = subprocess.CompletedProcess([], 1, json.dumps([finding]), "")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result)

    assert ci_lint.run_lint(lint_repository) == expected
    output = capsys.readouterr().out
    assert f"{expected} regressions" in output
    assert ("example.py:1:" in output) == bool(expected)


def test_clean_lint_passes_without_exercising_unused_baseline(lint_repository, monkeypatch, capsys):
    (lint_repository / "scripts/lint-baseline.json").write_text(json.dumps([
        {"path": "fixed.py", "sha256": "a" * 64}
    ]))
    result = subprocess.CompletedProcess([], 0, "[]", "")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result)
    assert ci_lint.run_lint(lint_repository) == 0
    output = capsys.readouterr().out
    assert "0 regressions; 0 unchanged baseline import blocks" in output
    assert "Unused baseline entries: 1" in output


@pytest.mark.parametrize("returncode", [2, 127, -9])
def test_lint_tool_failure_is_not_a_clean_result(lint_repository, monkeypatch, capsys, returncode):
    result = subprocess.CompletedProcess([], returncode, "", "Ruff tool failed\n")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result)
    assert ci_lint.run_lint(lint_repository) == returncode
    assert capsys.readouterr().out == "Ruff tool failed\n"


def test_malformed_lint_report_fails_closed(lint_repository, monkeypatch):
    result = subprocess.CompletedProcess([], 1, "not JSON", "")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result)
    with pytest.raises(json.JSONDecodeError):
        ci_lint.run_lint(lint_repository)
