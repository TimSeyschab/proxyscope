import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_branch_coverage.py"


@pytest.mark.parametrize(
    "totals,exit_code",
    [
        ({"num_branches": 100, "covered_branches": 81}, 0),
        ({"num_branches": 100, "covered_branches": 80}, 1),
        ({"num_branches": 10000, "covered_branches": 8099}, 1),
        ({"num_branches": 0, "covered_branches": 0}, 1),
        ({"percent_covered": 100}, 1),
    ],
)
def test_gate_uses_unrounded_branch_ratio_and_rejects_missing_measurement(tmp_path, totals, exit_code):
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps({"totals": totals}))
    result = subprocess.run([sys.executable, str(SCRIPT), str(report)], capture_output=True, text=True, check=False)
    assert result.returncode == exit_code
    assert "Branch coverage:" in result.stdout or "No branch coverage measured" in result.stdout


@pytest.mark.parametrize("minimum", ["-1", "101", "nan"])
def test_gate_rejects_invalid_threshold_before_reading_report(minimum):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "missing.json", "--minimum", minimum],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "minimum must be between 0 and 100" in result.stderr
