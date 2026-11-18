import os
import subprocess
import sys
from pathlib import Path


def test_import_leaves_working_directory_empty(tmp_path):
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [sys.executable, "-c", "import src.data.historical"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(root)},
        check=True,
    )
    assert not (tmp_path / "data").exists()
