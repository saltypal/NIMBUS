"""Generate the standalone ShiftOver GPU launcher notebooks."""

import json

import nbformat as nb

from nimbus.config import ROOT
from nimbus.models import MODELS


PROFILES = {
    "speech": ("speech_runtime.ipynb", ("speech",)),
    "handwriting": ("handwriting_runtime.ipynb", ("handwriting",)),
    "media": ("media_runtime.ipynb", ("speech", "handwriting")),
    "llm": ("llm_runtime.ipynb", ("llm",)),
}


def _selectors(capabilities):
    model_keys = {"speech": "speech", "handwriting": "handwriting", "llm": "llm"}
    specs = {capability: MODELS[model_keys[capability]] for capability in capabilities}
    ids = {capability: spec.model_id for capability, spec in specs.items()}
    revisions = {capability: spec.revision for capability, spec in specs.items()}
    return ids, revisions


def create(profile, filename, capabilities):
    helpers = (ROOT / "src/nimbus/notebook_setup.py").read_text(encoding="utf-8")
    model_ids, model_revisions = _selectors(capabilities)
    allowed_sources = {
        "speech": ["audio"],
        "handwriting": ["handwriting"],
        "media": ["audio", "handwriting"],
        "llm": [],
    }[profile]
    default_test_source = allowed_sources[0] if allowed_sources else "text"
    configuration = f'''
# Configuration: change these variables, then run top to bottom.
import json
REPO_URL = "https://github.com/saltypal/NIMBUS.git"
GIT_REF = "main"  # Prefer the exact 40-character commit SHA you reviewed.
WORKLOAD = "{profile}"  # this notebook runs only: {" + ".join(capabilities)}
MODE = "worker"  # worker pulls real jobs; smoke only loads/tests the selected adapter(s)
BACKEND = "auto"  # auto | cuda | cpu; TPU adapters are not implemented
LLM_BACKEND = "auto"  # relevant only to the llm notebook
PIPELINE_PARALLEL_SIZE = None  # llm auto: 2 on dual GPUs, otherwise 1
CLEAN_RESET = True  # replaces only the dedicated, marked disposable clone
RESET_ENVIRONMENT = False  # True rebuilds only the marked worker venv
SEED = 42
BRIDGE_URL = ""  # HTTPS tunnel to restricted bridge :8001; worker mode only
MODEL_IDS = {json.dumps(model_ids, indent=4)}
MODEL_REVISIONS = {json.dumps(model_revisions, indent=4)}  # immutable HF commit SHAs
SMOKE_INPUTS = {{}}  # optional e.g. {{"speech": "/kaggle/input/sample/note.wav"}}

# Optional end-to-end API test. Leave empty on Kaggle and use the laptop browser Test tab.
# Kaggle cannot reach http://127.0.0.1 on your laptop. Configure only a private,
# authenticated Tailscale/SSH endpoint for the core app; never publish MongoDB.
APP_API_URL = ""
TEST_SOURCE_TYPE = "{default_test_source}"  # audio | handwriting; text does not queue a worker
TEST_TEXT = "Pump P-12 vibration increased after tool change."
TEST_AUDIO_PATH = ""
TEST_HANDWRITING_PATH = ""
TEST_TIMEOUT_SECONDS = 1200
ALLOWED_TEST_SOURCE_TYPES = {json.dumps(allowed_sources)}

RUNTIME_ROOT, RESULTS_DIR = runtime_paths()
if "COLAB_RELEASE_TAG" in os.environ and not Path("/content/drive/MyDrive").exists():
    from google.colab import drive
    drive.mount("/content/drive")
if "runtime_process" in globals() and runtime_process.poll() is None:
    stop_runtime_process(runtime_process, globals().get("config"))
source = sync_repository(REPO_URL, GIT_REF, RUNTIME_ROOT, RESULTS_DIR, CLEAN_RESET)
print(json.dumps(source, indent=2))
if len(GIT_REF) != 40:
    print("NOTE: the moving ref resolved to the exact commit above; pin that SHA for reruns.")
'''
    install = """
# Install outside the notebook kernel so model libraries cannot destabilize it.
import platform
cuda_available = False
gpu_capabilities = []
try:
    import torch
    cuda_available = torch.cuda.is_available()
    if cuda_available:
        gpu_capabilities = [
            torch.cuda.get_device_capability(i) for i in range(torch.cuda.device_count())
        ]
except ImportError:
    pass
resolved_llm_backend = LLM_BACKEND
if resolved_llm_backend == "auto":
    suitable = (BACKEND != "cpu" and cuda_available and platform.system() == "Linux"
                and all(cap >= (7, 5) for cap in gpu_capabilities))
    resolved_llm_backend = "vllm" if suitable else "transformers"
worker_python = install_environment(
    source["repo_dir"], RUNTIME_ROOT, WORKLOAD, resolved_llm_backend, RESET_ENVIRONMENT
)
snapshot = RESULTS_DIR / f"dependencies-{WORKLOAD}-{source['git_commit'][:12]}.txt"
print(save_dependency_snapshot(worker_python, snapshot))
"""
    diagnostics = """
# Inspect the exact worker interpreter and reject obvious hardware/model mismatches
# before any weights are downloaded. Passing is an estimate; the real load remains required.
probe_code = ("import json; from nimbus.runtime import environment_info; "
              "print(json.dumps(environment_info()))")
probe = subprocess.check_output([worker_python, "-c", probe_code], text=True)
hardware = json.loads(probe)
print(json.dumps(hardware, indent=2))
config = {
    **source, "workload": WORKLOAD, "mode": MODE, "backend": BACKEND,
    "llm_backend": resolved_llm_backend, "models": MODEL_IDS, "revisions": MODEL_REVISIONS,
    "inputs": SMOKE_INPUTS, "seed": SEED, "bridge_url": BRIDGE_URL,
    "max_model_len": 8192, "llm_port": 9000,
}
from datetime import datetime, timezone
from uuid import uuid4
config["run_id"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
if PIPELINE_PARALLEL_SIZE is not None:
    config["pipeline_parallel_size"] = PIPELINE_PARALLEL_SIZE
config_path = RESULTS_DIR / f"runtime-config-{WORKLOAD}-{config['run_id']}.json"
config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
layout_code = ("import json,sys; from nimbus.runtime import choose_layout; "
               "print(json.dumps(choose_layout(json.loads(sys.argv[1]), "
               "json.loads(sys.argv[2])), indent=2))")
subprocess.run([worker_python, "-c", layout_code, json.dumps(config), json.dumps(hardware)],
               check=True)
"""
    launch = """
# Keys are read from runtime secrets and never written to config, output, or Git.
worker_environment = os.environ.copy()
if MODE == "worker":
    if not BRIDGE_URL:
        raise ValueError("Set BRIDGE_URL to restricted bridge :8001, or choose MODE='smoke'.")
    selected = ["speech", "handwriting"] if WORKLOAD == "media" else [WORKLOAD]
    for capability in selected:
        name = f"NIMBUS_BRIDGE_{capability.upper()}_KEY"
        worker_environment[name] = fetch_secret(name)
controller_log = RESULTS_DIR / f"controller-{WORKLOAD}-{config['run_id']}.log"
log_handle = controller_log.open("w", encoding="utf-8")
command = [worker_python, "-m", "nimbus.cli", "runtime", "--config", str(config_path)]
runtime_process = subprocess.Popen(
    command, cwd=source["repo_dir"], env=worker_environment,
    stdout=log_handle, stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
)
log_handle.close()
print({"controller_pid": runtime_process.pid, "log": str(controller_log), "mode": MODE})
"""
    logs = """
# Rerun while the controller runs. Weight downloads and first load can take several minutes.
print({"controller_exit_code": runtime_process.poll()})
print(controller_log.read_text(encoding="utf-8", errors="replace")[-8000:])
for log_path in sorted(RESULTS_DIR.glob("*/**/*.log"))[-6:]:
    print(log_path.name, log_path.read_text(encoding="utf-8", errors="replace")[-2500:])
"""
    api_test = r'''
# Optional full path: notebook -> private app API -> local queue -> outbound worker pull -> result.
# The normal setup needs no app tunnel: leave APP_API_URL empty and submit in the laptop Test tab.
if not ALLOWED_TEST_SOURCE_TYPES:
    print("The inference-test endpoint does not queue an LLM job. Validate the LLM through "
          "ShiftOver's normal local draft flow while this worker runs.")
elif not APP_API_URL:
    print("APP_API_URL is empty. Use ShiftOver's local browser Test tab while this worker runs.")
else:
    from urllib.parse import urlparse
    parsed_api = urlparse(APP_API_URL)
    if Path("/kaggle").exists() or "COLAB_RELEASE_TAG" in os.environ:
        if parsed_api.hostname in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Notebook localhost is not the laptop. Use a private authenticated URL.")
        if parsed_api.scheme != "https":
            raise ValueError("Remote APP_API_URL must be private authenticated HTTPS.")
    if TEST_SOURCE_TYPE not in ALLOWED_TEST_SOURCE_TYPES:
        raise ValueError(f"Choose one of {ALLOWED_TEST_SOURCE_TYPES} for this worker profile.")
    test_file = (TEST_AUDIO_PATH if TEST_SOURCE_TYPE == "audio"
                 else TEST_HANDWRITING_PATH)
    if not test_file or not Path(test_file).is_file():
        raise ValueError(f"Set an existing local path for {TEST_SOURCE_TYPE} before testing.")
    api_test_code = r"""
import json, pathlib, sys, time
import httpx
base, source_type, text, filename, timeout_text = sys.argv[1:]
data = {"source_type": source_type}
if text:
    data["text"] = text
files = None
handle = None
try:
    if filename:
        path = pathlib.Path(filename)
        handle = path.open("rb")
        files = {"file": (path.name, handle, "application/octet-stream")}
    with httpx.Client(timeout=60, trust_env=False) as client:
        response = client.post(base.rstrip("/") + "/api/inference-tests", data=data, files=files)
        response.raise_for_status()
        state = response.json()
        test_id = state.get("id") or state.get("_id")
        if not test_id:
            raise RuntimeError("Inference-test response did not include an id")
        deadline = time.monotonic() + int(timeout_text)
        while state["status"] in {"queued", "leased"} and time.monotonic() < deadline:
            time.sleep(3)
            poll = client.get(base.rstrip("/") + f"/api/inference-tests/{test_id}")
            poll.raise_for_status()
            state = poll.json()
            print(json.dumps(state, indent=2))
        if state["status"] != "succeeded":
            raise RuntimeError(f"End-to-end inference test ended as {state['status']}: {state.get('error')}")
        print(json.dumps({"verified_status": state["status"], "job_id": state.get("job_id"),
                          "capability": state.get("capability"), "worker_id": state.get("worker_id"),
                          "model_id": state.get("model_id"),
                          "model_revision": state.get("model_revision"),
                          "transcript": state.get("transcript")}, indent=2))
finally:
    if handle:
        handle.close()
"""
    subprocess.run([worker_python, "-c", api_test_code, APP_API_URL, TEST_SOURCE_TYPE,
                    TEST_TEXT if TEST_SOURCE_TYPE == "text" else "", test_file,
                    str(TEST_TIMEOUT_SECONDS)], check=True)
'''
    stop = """
# Explicit shutdown, then create a portable archive before the temporary runtime is removed.
if runtime_process.poll() is None:
    stop_runtime_process(runtime_process, config)
print({"controller_exit_code": runtime_process.poll()})
archive_path = RESULTS_DIR.parent / f"shiftover-{WORKLOAD}-{config['run_id']}-results"
archive = shutil.make_archive(str(archive_path), "zip", RESULTS_DIR)
print({"results_archive": archive})
if Path("/kaggle").exists():
    print("Save a Kaggle version with outputs or download this archive before session reset.")
"""
    notebook = nb.v4.new_notebook(
        cells=[
            nb.v4.new_markdown_cell(
                f"""# ShiftOver · {profile} runtime

Standalone Local Jupyter / Colab / Kaggle launcher. Git is the source of truth. This
notebook runs **{" + ".join(capabilities)} only**. Internal Python package and secret names
remain `nimbus` / `NIMBUS_*` for compatibility.

**Validation status:** structure, clean-clone safety, configuration compilation, and local
contract tests are validated. Model loading, GPU memory peaks, latency, and real media
quality are unverified until you run the smoke and representative samples on target GPUs.
"""
            ),
            nb.v4.new_markdown_cell("## 1. Clean reset and sync\n\nEdit the variables below. Reset can delete only this notebook's marked clone. Results stay outside it. Prefer an exact commit SHA."),
            nb.v4.new_code_cell(helpers + "\n" + configuration),
            nb.v4.new_markdown_cell("## 2. Install the isolated worker environment\n\nThe app environment and GPU environment are separate. Installation ends with `pip check` and records an exact dependency snapshot."),
            nb.v4.new_code_cell(install),
            nb.v4.new_markdown_cell("## 3. Inspect hardware and preflight the model\n\nThis checks CUDA capability and conservative RAM/VRAM estimates. A pass does not prove the real model fits."),
            nb.v4.new_code_cell(diagnostics),
            nb.v4.new_markdown_cell("## 4. Launch\n\nWorkers connect outward to bridge port 8001. No notebook port or MongoDB connection is exposed. The LLM server binds runtime loopback only."),
            nb.v4.new_code_cell(launch),
            nb.v4.new_markdown_cell("## 5. Inspect bounded logs\n\nWorkers register only after adapter smoke. Synthetic smoke proves execution, not production accuracy."),
            nb.v4.new_code_cell(logs),
            nb.v4.new_markdown_cell("## 6. Optional end-to-end product test\n\nThe preferred path is the local ShiftOver browser Test tab. Configure `APP_API_URL` only when the core app is reachable through a private authenticated tunnel."),
            nb.v4.new_code_cell(api_test),
            nb.v4.new_markdown_cell("## 7. Stop and retain results\n\nStop owned processes and preserve the manifest, exact source/model revisions, dependency snapshot, and logs."),
            nb.v4.new_code_cell(stop),
        ],
        metadata={
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
        },
    )
    target = ROOT / "notebooks" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    nb.validate(notebook)
    nb.write(notebook, target)
    print(target)


if __name__ == "__main__":
    for profile, (filename, capabilities) in PROFILES.items():
        create(profile, filename, capabilities)
