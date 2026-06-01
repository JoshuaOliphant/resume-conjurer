---
paths:
  - "web/**/*.py"
  - "plugins/**/*.py"
---

# Testing & Coverage Rules

## The bar: 100% coverage, line AND branch

Every Python change ships with tests that bring it to **100% line and branch coverage**. This is
not about a number for its own sake: driving to 100% reliably surfaces unreachable code paths, dead
branches, and untested error handling that partial coverage hides. If a line cannot be covered,
that is a signal to either test it or delete it.

## How to run the gate

```
cd web && uv run pytest          # coverage is wired into addopts; the run fails under 100%
```

The gate is enforced mechanically in `web/pyproject.toml`:
- `[tool.coverage.run] branch = true`, `source = ["app"]`
- `[tool.coverage.report] fail_under = 100`

A `uv run pytest` that passes has already proven 100% line+branch coverage of `app/`. Use
`--cov-report=term-missing` to see exactly which lines/branches are uncovered while iterating.

## Practice TDD

Write the failing test first, then the minimal code to pass it, then refactor. New behavior arrives
with its test, not after.

## `# pragma: no cover` is a last resort, and must be justified

Prefer testing the path over excluding it. Only exclude genuinely unreachable or
defensive-only code, and leave a one-line reason next to the pragma. Lines already excluded by
project policy (in `[tool.coverage.report] exclude_lines`): Protocol method stubs (`...`),
`if __name__ == "__main__":` blocks, and `if TYPE_CHECKING:` imports. Do not add blanket file-level
exclusions.

## Note on enforcement

Per Claude Code's docs, a rule is guidance Claude reads, not configuration Claude Code enforces.
The real teeth here is the `pytest` coverage gate above (and any CI that runs it); this rule
explains the intent and the workflow so changes are written to clear that gate the first time.
