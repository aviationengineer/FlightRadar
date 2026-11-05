"""Unit tests for the scheduled runner's missing-key behaviour:
with no AIRLABS_API_KEY it must log a clear message and exit 0
(graceful skip — a cron job must never error loudly, and no signup
is ever attempted).
"""

import os
import subprocess
import sys
from pathlib import Path

VENV_PY = Path.home() / "workspace" / "AIRLABS_FLEET_API" / ".venv" / "bin" / "python"
SCHEDULE_RUN = Path.home() / "workspace" / "AIRLABS_FLEET_API" / "schedule_run.py"


def test_schedule_run_missing_key_exits_zero():
    env = {k: v for k, v in os.environ.items() if k != "AIRLABS_API_KEY"}
    proc = subprocess.run(
        [str(VENV_PY), str(SCHEDULE_RUN), "--mode", "weekly"],
        capture_output=True, text=True, timeout=60, env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert "AIRLABS_API_KEY" in combined
    assert "airlabs.co" in combined
