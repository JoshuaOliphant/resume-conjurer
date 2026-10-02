# ABOUTME: Runs pinned Ruff against the repository and rejects lint regressions.
# ABOUTME: Allows only exact import blocks recorded in the reviewed debt baseline.
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUFF_VERSION = "0.12.11"


def finding_key(root: Path, finding: dict) -> tuple[str, str, str]:
    path = Path(finding["filename"])
    lines = path.read_bytes().splitlines(keepends=True)
    start = finding["location"]["row"] - 1
    end = finding["end_location"]["row"]
    block = b"".join(lines[start:end])
    return (
        path.relative_to(root).as_posix(),
        finding["code"],
        hashlib.sha256(block).hexdigest(),
    )


def run_lint(root: Path) -> int:
    result = subprocess.run(
        [
            "uvx", "--no-config", "--from", f"ruff=={RUFF_VERSION}",
            "ruff", "check", "--config", str(root / "ruff.toml"),
            "--output-format", "json", ".",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        print(result.stderr, end="")
        return result.returncode
    baseline = json.loads((root / "scripts/lint-baseline.json").read_text())
    allowed = {(item["path"], "I001", item["sha256"]) for item in baseline}
    findings = json.loads(result.stdout)
    regressions = []
    used = set()
    for item in findings:
        key = finding_key(root, item)
        if key in allowed:
            used.add(key)
        else:
            regressions.append(item)
    for item in regressions:
        path = Path(item["filename"]).relative_to(root)
        print(f"{path}:{item['location']['row']}: {item['code']} {item['message']}")
    print(f"Ruff {RUFF_VERSION}: {len(regressions)} regressions; "
          f"{len(findings) - len(regressions)} unchanged baseline import blocks.")
    print(f"Unused baseline entries: {len(allowed - used)}; remove entries for fixed blocks.")
    return int(bool(regressions))


if __name__ == "__main__":
    raise SystemExit(run_lint(ROOT))
