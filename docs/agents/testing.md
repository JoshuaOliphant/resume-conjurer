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
| Plugin and CI tooling coverage | `uv run --locked --offline pytest -q` | 100% line and branch, enforced by root `pyproject.toml` |
| Web suite and coverage | `uv run --locked --offline pytest -q` from `web/` | 100% line and branch, enforced by `web/pyproject.toml` |
| Lint regressions | `uv run --locked python scripts/ci_lint.py` | pinned Ruff; exact existing import-block exceptions only |
| Types | `uvx --no-config --from ty==0.0.84 ty check --config-file ty.toml --python web/.venv --error-on-warning web scripts` from root | pinned Ty and explicit configuration |

Not gates: `ruff format` has never been applied (26 files would be reformatted) and there is no
formatter config. The type gate supplies the web environment and the plugin script search path
explicitly; an unconfigured root `ty check` is not equivalent.

## Offline CI

`.github/workflows/checks.yml` runs on pull requests, main pushes, and manual dispatch. Independent
Plugin and Web matrix jobs each install their own lockfile with `uv sync --locked`, then run pytest
offline. A separate job runs lint and types. Tool versions are uv 0.11.8, Ruff 0.12.11, Ty 0.0.84,
and CPython 3.12.7; dependency versions come from the two existing lockfiles.

No job consumes Claude or TypeSafe secrets, invokes semantic lint, uploads artifacts, or reads an
external career workspace. Tests use temporary synthetic files and localhost HTTP fixtures.
The web tests retain their default `not live` selection. Real API checks remain an explicit local
`uv run --locked pytest -m live` from `web/`, with separately authorized credentials/data.
This workflow does not change branch protection.

The clean Python 3.11.10 baseline at `d485a0d` passes the plugin suite but fails three pre-existing
web metrics assertions on the exact sum of floating-point costs. CPython 3.12.7 passes both suites;
the CI runtime matches that measured baseline. Supporting the older interpreter's float-sum
behavior requires separate product/test work, not a CI-only silent assertion change.

## Lint profile and existing debt

`ruff.toml` enables E4/E7/E9/F/I, fixes Python and source-directory classification, and is always
passed explicitly. `uvx --no-config` prevents uv configuration discovery. Ruff and Ty configuration
paths are explicit so ambient user rule sets cannot change the gates. To sort a touched file,
run `uvx --no-config --from ruff==0.12.11 ruff check --config ruff.toml --fix <path>` from root;
use an absolute config path when running from another directory.

At `d485a0d`, the selected core E4/E7/E9/F rules have no findings. The explicit import profile
has 23 existing I001 blocks, recorded in `scripts/lint-baseline.json`. Each exception is tied
to the exact file and SHA-256 of the reported source block, not a whole-file ignore. Changed
blocks and additional unsorted blocks fail. Unused baseline entries are counted in the gate output;
remove entries for fixed blocks during integration so the reviewed baseline cannot accumulate silently.
Do not regenerate the baseline to admit new findings. A broader ambient profile previously
reported 49 findings; it is not claimed clean or silently adopted. Unrelated lint cleanup stays
outside the product slices.

`tests/test_ci_lint.py` covers unchanged debt, changed/new blocks, a core finding that cannot be
baselined, clean output, tool failure, and malformed output. The repository lint gate also runs
against real Ruff; prove it detects a planted unsorted block before relying on it.

## Coverage

Threshold: 100% line and branch coverage, for both `web/app/` and the plugin scripts
(`.claude/rules/testing.md`). It is a gate, not a target to pad: when reaching it would take
tests that prove nothing, bring the uncovered lines to the user with a proposed exclusion or a
lower threshold. When running unattended, under `compost:implement`, or as a worker, post the
proposal as a ruling comment on the issue, list it in the PR's Risk section, and continue; the
user decides at `compost:finish`.

Exclusions agreed so far (`[tool.coverage.report] exclude_lines` in each project's `pyproject.toml`):

- Protocol method stubs (`...`): no body to run.
- `if __name__ == "__main__":` and `if TYPE_CHECKING:`: never executed under test. Plugin CLI `main()` functions are covered through direct calls with real temporary files.
- `raise NotImplementedError`: live-only methods on the offline fake repository, never called in
  `fake` mode.

## Generation recovery

Issue #41 maps initial generation, partial completion, targeted retry, and storage behavior to the existing run, repository, and route suites. Issue #42 maps restart recovery to `web/tests/test_generation_routes.py`, reusing the live-flow synthetic workspace. The issue comments hold the AC-to-node evidence tables. `web/tests/conftest.py` initializes the existing plugin script path so isolated test modules do not depend on collection order.
