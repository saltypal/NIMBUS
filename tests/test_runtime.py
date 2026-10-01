import json
import subprocess
import sys
import time

import nbformat
import pytest

from nimbus.config import ROOT
from nimbus.errors import NimbusError
from nimbus.notebook_setup import stop_runtime_process, sync_repository
from nimbus.runtime import choose_layout, run_runtime, vllm_command


def hardware(names):
    return {
        "cuda_available": bool(names),
        "tpu_detected": False,
        "system_memory_gib": 64.0,
        "gpus": [
            {
                "name": name,
                "compute_capability": [7, 5] if name == "T4" else [6, 0],
                "vram_gib": 15.0 if name == "T4" else 16.0,
            }
            for name in names
        ],
    }


def test_dual_media_separate_devices_and_llm_pipeline(monkeypatch):
    monkeypatch.setattr("nimbus.runtime.platform.system", lambda: "Linux")
    media = choose_layout({"workload": "media"}, hardware(["T4", "T4"]))
    assert media["devices"] == {"speech": "cuda:0", "handwriting": "cuda:1"}
    llm = choose_layout({"workload": "llm"}, hardware(["T4", "T4"]))
    assert llm["llm_backend"] == "vllm"
    command = vllm_command("Qwen/Qwen3-8B", "fixture-sha", {}, llm)
    assert command[command.index("--pipeline-parallel-size") + 1] == "2"
    assert command[command.index("--tensor-parallel-size") + 1] == "1"
    assert command[command.index("--host") + 1] == "127.0.0.1"


def test_cpu_p100_and_tpu_are_distinct(monkeypatch):
    monkeypatch.setattr("nimbus.runtime.platform.system", lambda: "Linux")
    assert choose_layout({"workload": "llm"}, hardware([]))["llm_backend"] == "transformers"
    assert choose_layout({"workload": "llm"}, hardware(["P100"]))["llm_backend"] == "transformers"
    with pytest.raises(NimbusError) as captured:
        choose_layout({"workload": "media"}, hardware(["T4"]))
    assert captured.value.code == "media_requires_two_gpus"
    with pytest.raises(NimbusError) as captured:
        choose_layout({"workload": "llm"}, {**hardware([]), "tpu_detected": True})
    assert captured.value.code == "tpu_backend_not_implemented"


@pytest.mark.parametrize(
    "config,code",
    [
        ({"backend": "typo"}, "unknown_backend"),
        ({"llm_backend": "typo"}, "unknown_llm_backend"),
        ({"mode": "typo"}, "unknown_mode"),
        ({"pipeline_parallel_size": 0}, "invalid_pipeline_size"),
    ],
)
def test_invalid_runtime_config_fails_before_downloading(config, code):
    with pytest.raises(NimbusError) as captured:
        choose_layout(config, hardware([]))
    assert captured.value.code == code


def test_model_resolution_failure_keeps_a_run_manifest(tmp_path, monkeypatch):
    def fail_resolution(*arguments):
        raise NimbusError("fixture_download_failure", "Synthetic model download failure.")

    monkeypatch.setattr("nimbus.runtime.environment_info", lambda: hardware([]))
    monkeypatch.setattr(
        "nimbus.runtime.subprocess.check_output", lambda *args, **kwargs: "fixture-sha"
    )
    monkeypatch.setattr("nimbus.inference.base.pinned_revision", fail_resolution)
    config = {
        "workload": "speech",
        "mode": "smoke",
        "repo_dir": str(tmp_path),
        "results_dir": str(tmp_path / "results"),
        "run_id": "resolution_failure",
    }
    with pytest.raises(NimbusError):
        run_runtime(config)
    manifest = json.loads((tmp_path / "results/resolution_failure/run.json").read_text())
    assert manifest["git_commit"] == "fixture-sha"
    assert manifest["status"] == "failed"
    assert manifest["error"]["code"] == "fixture_download_failure"


def test_clean_clone_refreshes_source_and_preserves_results(tmp_path):
    remote = tmp_path / "fixture-remote"
    remote.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(remote)], check=True, capture_output=True)
    (remote / "src/nimbus").mkdir(parents=True)
    (remote / "src/nimbus/runtime.py").write_text("# test fixture", encoding="utf-8")
    (remote / "pyproject.toml").write_text("# fixture", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=remote, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=remote,
        check=True,
        capture_output=True,
    )
    results = tmp_path / "results"
    first = sync_repository(str(remote), "main", tmp_path / "runtime", results)
    (results / "retain.json").write_text(json.dumps({"keep": True}), encoding="utf-8")
    (remote / "new.txt").write_text("new source", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=remote, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-m",
            "new",
        ],
        cwd=remote,
        check=True,
        capture_output=True,
    )
    second = sync_repository(str(remote), "main", tmp_path / "runtime", results)
    assert first["git_commit"] != second["git_commit"]
    assert (results / "retain.json").exists()
    with pytest.raises(ValueError, match="outside"):
        sync_repository(
            str(remote), "main", tmp_path / "runtime", tmp_path / "runtime/source/results"
        )


def test_reset_refuses_unowned_source_directory(tmp_path):
    source = tmp_path / "runtime/source"
    source.mkdir(parents=True)
    with pytest.raises(ValueError, match="ownership marker"):
        sync_repository(
            "https://example.test/repo.git", "main", tmp_path / "runtime", tmp_path / "results"
        )
    assert source.exists()


def test_notebook_shutdown_stops_its_owned_child_process(tmp_path):
    heartbeat = tmp_path / "child-heartbeat.txt"
    child_code = """
import sys, time
from pathlib import Path
for number in range(2400):
    Path(sys.argv[1]).write_text(str(number))
    time.sleep(0.05)
"""
    parent_code = f"""
import signal, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', {child_code!r}, sys.argv[1]])
def stop(signum, frame):
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
print('ready', flush=True)
try:
    time.sleep(120)
finally:
    if child.poll() is None:
        child.terminate()
    child.wait(timeout=10)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", parent_code, str(heartbeat)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        deadline = time.monotonic() + 5
        while not heartbeat.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert heartbeat.exists()
        stop_runtime_process(process)
        time.sleep(0.1)
        last = heartbeat.read_text()
        time.sleep(0.2)
        assert heartbeat.read_text() == last
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            stop_runtime_process(process)
        process.stdout.close()


def test_embedded_first_cell_runs_without_hidden_imports(tmp_path):
    remote = tmp_path / "fixture"
    remote.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(remote)], check=True, capture_output=True)
    (remote / "src/nimbus").mkdir(parents=True)
    (remote / "src/nimbus/runtime.py").write_text("# notebook setup fixture", encoding="utf-8")
    (remote / "pyproject.toml").write_text("# fixture", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=remote, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=remote,
        check=True,
        capture_output=True,
    )
    notebook = nbformat.read(ROOT / "notebooks/media_runtime.ipynb", as_version=4)
    cell = next(cell for cell in notebook.cells if cell.cell_type == "code")
    code = cell.source.replace(
        'REPO_URL = "https://github.com/saltypal/NIMBUS.git"', f"REPO_URL = {str(remote)!r}"
    )
    code = code.replace(
        "RUNTIME_ROOT, RESULTS_DIR = runtime_paths()",
        f"RUNTIME_ROOT, RESULTS_DIR = Path({str(tmp_path / 'runtime')!r}), "
        f"Path({str(tmp_path / 'results')!r})",
    )
    namespace = {}
    exec(compile(code, "first-cell-fixture", "exec"), namespace)
    assert namespace["source"]["git_commit"]
    assert (tmp_path / "runtime/source/.nimbus-runtime-clone").exists()


@pytest.mark.parametrize("filename", ["media_runtime.ipynb", "llm_runtime.ipynb"])
def test_notebooks_valid_and_all_code_cells_compile(filename):
    notebook = nbformat.read(ROOT / "notebooks" / filename, as_version=4)
    nbformat.validate(notebook)
    cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    assert "sync_repository" in cells[0].source
    assert "CLEAN_RESET = True" in cells[0].source
    for index, cell in enumerate(cells):
        compile(cell.source, f"{filename}:cell{index}", "exec")
