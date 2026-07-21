from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest


def _load_run_benchmark():
    path = Path(__file__).resolve().parents[2] / "scripts/run_benchmark.py"
    spec = importlib.util.spec_from_file_location("overseaark_run_benchmark", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_timeout_terminates_child_process_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    child_pid_path = tmp_path / "benchmark-child.pid"
    script = tmp_path / "benchmark_process_tree.py"
    script.write_text(
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OVERSEAARK_BENCH_TIMEOUT", "1")
    monkeypatch.setenv("OVERSEAARK_TEST_COMMAND", f"{sys.executable} {script} {child_pid_path}")
    benchmark = _load_run_benchmark()

    with pytest.raises(RuntimeError, match="process group was terminated"):
        benchmark.run_adapter("OVERSEAARK_TEST_COMMAND", {})

    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    for _ in range(100):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.01)
    else:
        pytest.fail("benchmark timeout left a child process running")
