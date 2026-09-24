# Tests and gates

## Test convention

Plain pytest, adopted from the existing suite. The repo has two separate uv projects, each with
its own suite.

- Plugin scripts: tests live in `tests/` at the repo root, one `test_<script>.py` per script in
  `plugins/conjurer/skills/conjurer/scripts/`. `tests/conftest.py` puts that scripts directory on
  `sys.path`, so tests import `stitch`, `lint`, and the rest by bare name.
- Web app: tests live in `web/tests/`, named `test_<module>.py` after the `web/app/` module they
  cover, with file fixtures under `web/tests/fixtures/`. The offline suite runs on the `fake` backend pair
  (`FakeWorkspaceRepository`, `FakeGenerationPort`); tests that call the real API are marked
  `live` and deselected by default.
- Each acceptance criterion AC-N maps to a test node id or parametrize id, recorded in the
  issue's AC table.
- BDD feature files: no.

## Gates

`compost:verify` runs these in order and stops at the first failure. Run the web gates from
`web/`; the rest from the repo root.

| Gate | Command | Status |
|---|---|---|
| Plugin suite | `uv run pytest -q` | passing (42 tests) |
| Plugin coverage | `uv run pytest -q --cov=plugins --cov-branch --cov-report=term-missing --cov-fail-under=100` | broken: `FAIL Required test coverage of 100% not reached. Total coverage: 86.61%` |
| Web suite and coverage | `cd web && uv run pytest -q` | passing (154 tests, 100% line and branch, enforced by `fail_under` in `web/pyproject.toml`) |
| Lint | `uvx ruff check .` | passing |
| Types | `cd web && uvx ty check` | passing |

Not gates: `ruff format` has never been applied (26 files would be reformatted) and there is no
formatter config. `ty check` from the repo root reports unresolved imports because it doesn't see
the web venv or the scripts `sys.path` insert; only `web/` configures ty. There is no CI, so
these gates are only as green as the last local run.

## Coverage

Threshold: 100% line and branch coverage, for both `web/app/` and the plugin scripts
(`.claude/rules/testing.md`). It is a gate, not a target to pad: when reaching it would take
tests that prove nothing, bring the uncovered lines to the user with a proposed exclusion or a
lower threshold. When running unattended, under `compost:implement`, or as a worker, post the
proposal as a ruling comment on the issue, list it in the PR's Risk section, and continue; the
user decides at `compost:finish`.

Exclusions agreed so far (`[tool.coverage.report] exclude_lines` in `web/pyproject.toml`):

- Protocol method stubs (`...`): no body to run.
- `if __name__ == "__main__":` and `if TYPE_CHECKING:`: never executed under test.
- `raise NotImplementedError`: live-only methods on the offline fake repository, never called in
  `fake` mode.
