"""Runs the small Node test files in tests/js (the Python suite otherwise has
no way to catch a broken browser-side module). Skipped where Node is absent."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("process_tz", ["America/New_York", "Asia/Tokyo", "UTC"])
def test_browser_modules_pass_under_node(process_tz):
    test_files = [str(p) for p in sorted((ROOT / "tests" / "js").glob("*.test.mjs"))]
    result = subprocess.run(
        [NODE, "--test", *test_files],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "TZ": process_tz},
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
