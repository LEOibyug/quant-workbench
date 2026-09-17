import json
import subprocess
import sys


def test_doctor_runs_from_another_directory_without_optional_gpu_packages(tmp_path):
    output = subprocess.run(
        [sys.executable, "-m", "quant_workbench.cli", "doctor"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    diagnostic = json.loads(output.stdout)
    assert diagnostic["default_compute"] == "cpu"
    assert diagnostic["data_directory"] == str(tmp_path / "data")
    assert diagnostic["disk_free_gib"] >= 0


def test_cli_returns_nonzero_for_invalid_input():
    result = subprocess.run(
        [sys.executable, "-m", "quant_workbench.cli", "estimate", "--symbols", "0"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "positive integer" in result.stderr
