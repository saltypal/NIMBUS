"""Hardware diagnostics and multi-process notebook orchestration, outside cells."""

import importlib.metadata
import json
import os
import platform
import random
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from .errors import NimbusError
from .models import MODELS, resolve_model


def environment_info():
    environment = (
        "kaggle"
        if Path("/kaggle").exists()
        else "colab"
        if "COLAB_RELEASE_TAG" in os.environ
        else "local"
    )
    info = {
        "environment": environment,
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {},
        "gpus": [],
        "cuda_available": False,
        "system_memory_gib": _system_memory_gib(),
        "tpu_detected": any(
            name in os.environ for name in ("TPU_NAME", "COLAB_TPU_ADDR", "TPU_WORKER_ID")
        ),
    }
    for name in (
        "torch",
        "transformers",
        "vllm",
        "faster-whisper",
        "ctranslate2",
        "pymongo",
        "numpy",
    ):
        try:
            info["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    try:
        import torch

        info["cuda_available"] = torch.cuda.is_available()
        info["torch_cuda"] = torch.version.cuda
        if info["cuda_available"]:
            for index in range(torch.cuda.device_count()):
                properties = torch.cuda.get_device_properties(index)
                info["gpus"].append(
                    {
                        "index": index,
                        "name": properties.name,
                        "vram_gib": round(properties.total_memory / 1024**3, 2),
                        "compute_capability": list(torch.cuda.get_device_capability(index)),
                    }
                )
    except ImportError:
        info["torch_installed"] = False
    return info


def _system_memory_gib():
    """Return physical RAM without adding a runtime dependency."""
    try:
        if os.name == "nt":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong),
                    ("available_physical", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended_virtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return round(status.total_physical / 1024**3, 2)
            return None
        page_size = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        return round(page_size * pages / 1024**3, 2)
    except (AttributeError, OSError, ValueError):
        return None


def source_info(directory=None):
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=directory, text=True, stderr=subprocess.DEVNULL
        ).strip()
        changed = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=directory, text=True
        )
        # The notebook-owned clone marker is runtime metadata, not source.
        dirty = any(".nimbus-runtime-clone" not in line for line in changed.splitlines())
        return {"git_commit": commit, "working_tree_dirty": dirty}
    except subprocess.CalledProcessError:
        return {"git_commit": None, "working_tree_dirty": True}


def _selected_specs(config, capabilities, llm_backend, stages, info):
    selected = {}
    configured = config.get("models") or {}
    for capability in capabilities:
        if configured.get(capability):
            model_id = configured[capability]
        elif capability == "llm":
            gpu_sizes = [gpu.get("vram_gib", 0) for gpu in info.get("gpus", [])]
            large_default = llm_backend == "vllm" and (
                stages >= 2 or (gpu_sizes and max(gpu_sizes) >= MODELS["llm"].minimum_runtime_gib)
            )
            model_id = MODELS["llm" if large_default else "llm-small"].model_id
        else:
            model_id = MODELS[capability].model_id
        spec = resolve_model(model_id, capability)
        if capability == "llm" and llm_backend not in spec.supported_backends:
            raise NimbusError(
                "model_backend_incompatible",
                f"{model_id} is not registered for the {llm_backend} backend.",
            )
        selected[capability] = spec
    return selected


def _check_resource_plan(specs, devices, info, llm_backend, stages):
    """Reject obvious memory mismatches before any model is downloaded."""
    resource_plan = {}
    if info.get("cuda_available"):
        for capability, spec in specs.items():
            if capability == "llm" and llm_backend == "vllm":
                assigned = list(range(stages))
                required_each = spec.minimum_runtime_gib / stages
            else:
                assigned = [int(devices[capability].split(":")[1])]
                required_each = spec.minimum_runtime_gib
            available = []
            for index in assigned:
                try:
                    value = info["gpus"][index].get("vram_gib")
                except IndexError as error:
                    raise NimbusError(
                        "insufficient_gpus", "The selected model has no assigned GPU."
                    ) from error
                if value is None:
                    raise NimbusError(
                        "gpu_memory_unknown",
                        "GPU memory could not be detected, so model fit cannot be checked safely.",
                    )
                available.append(float(value))
            if any(value < required_each for value in available):
                raise NimbusError(
                    "model_memory_incompatible",
                    f"{spec.model_id} needs an estimated {required_each:.1f} GiB per assigned "
                    f"GPU for this layout; detected {available}. Choose a smaller model or "
                    "different hardware. This is a conservative estimate, not a measured peak.",
                )
            resource_plan[capability] = {
                "assigned_gpu_indices": assigned,
                "available_vram_gib": available,
                "estimated_weight_gib": spec.estimated_weight_gib,
                "minimum_runtime_gib": spec.minimum_runtime_gib,
                "status": "estimate_passed_real_load_required",
            }
    else:
        available = info.get("system_memory_gib")
        if available is None:
            raise NimbusError(
                "system_memory_unknown",
                "System RAM could not be detected, so CPU model fit cannot be checked safely.",
            )
        required = sum(spec.minimum_system_ram_gib for spec in specs.values())
        if float(available) < required:
            raise NimbusError(
                "model_memory_incompatible",
                f"Selected CPU models need an estimated {required:.1f} GiB system RAM; "
                f"detected {available} GiB. Select one smaller workload or different hardware.",
            )
        resource_plan["cpu"] = {
            "available_system_ram_gib": float(available),
            "minimum_system_ram_gib": required,
            "status": "estimate_passed_real_load_required",
        }
    return resource_plan


def choose_layout(config, info):
    workload = config.get("workload", "llm")
    if workload not in {"speech", "handwriting", "media", "llm"}:
        raise NimbusError("unknown_workload", "Choose speech, handwriting, media, or llm.")
    backend = config.get("backend", "auto")
    if backend not in {"auto", "cuda", "cpu", "tpu"}:
        raise NimbusError("unknown_backend", "Choose auto, cuda, or cpu.")
    if config.get("mode", "worker") not in {"worker", "smoke"}:
        raise NimbusError("unknown_mode", "Choose worker or smoke.")
    if backend == "tpu" or (
        backend == "auto" and info["tpu_detected"] and not info["cuda_available"]
    ):
        raise NimbusError(
            "tpu_backend_not_implemented",
            "These adapters use CUDA or CPU. TPU needs a separate XLA adapter.",
        )
    cuda = backend != "cpu" and info["cuda_available"]
    if backend == "cuda" and not cuda:
        raise NimbusError("cuda_unavailable", "CUDA was requested but is unavailable.")
    if workload == "media" and cuda and len(info["gpus"]) < 2:
        raise NimbusError(
            "media_requires_two_gpus", "Use a dual-GPU runtime or select one media workload."
        )
    capabilities = ["speech", "handwriting"] if workload == "media" else [workload]
    devices = {cap: f"cuda:{index}" if cuda else "cpu" for index, cap in enumerate(capabilities)}
    llm_backend = config.get("llm_backend", "auto")
    if llm_backend not in {"auto", "vllm", "transformers"}:
        raise NimbusError("unknown_llm_backend", "Choose auto, vllm, or transformers.")
    suitable_vllm = (
        cuda
        and platform.system() == "Linux"
        and all(tuple(gpu["compute_capability"]) >= (7, 5) for gpu in info["gpus"])
    )
    if llm_backend == "auto":
        llm_backend = "vllm" if suitable_vllm else "transformers"
    if workload == "llm" and llm_backend == "vllm" and not suitable_vllm:
        raise NimbusError(
            "vllm_hardware_incompatible",
            "Use Linux CUDA with compute capability >=7.5, or choose transformers.",
        )
    stages = config.get(
        "pipeline_parallel_size",
        2 if workload == "llm" and llm_backend == "vllm" and len(info["gpus"]) >= 2 else 1,
    )
    if type(stages) is not int or stages < 1:
        raise NimbusError(
            "invalid_pipeline_size", "Pipeline stage count must be a positive integer."
        )
    if workload == "llm" and llm_backend == "vllm" and stages > len(info["gpus"]):
        raise NimbusError("insufficient_gpus", "Pipeline stage count exceeds visible GPUs.")
    specs = _selected_specs(config, capabilities, llm_backend, stages, info)
    resource_plan = _check_resource_plan(specs, devices, info, llm_backend, stages)
    configured_revisions = config.get("revisions") or {}
    return {
        "capabilities": capabilities,
        "devices": devices,
        "llm_backend": llm_backend,
        "pipeline_parallel_size": stages,
        "tensor_parallel_size": 1,
        "models": {capability: spec.model_id for capability, spec in specs.items()},
        "model_revisions": {
            capability: configured_revisions.get(capability) or spec.revision
            for capability, spec in specs.items()
        },
        "resource_plan": resource_plan,
    }


def vllm_command(model_id, revision, config, layout):
    resolve_model(model_id, "llm")
    return [
        sys.executable,
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        model_id,
        "--revision",
        revision,
        "--host",
        "127.0.0.1",
        "--port",
        str(config.get("llm_port", 9000)),
        "--dtype",
        "float16",
        "--max-model-len",
        str(config.get("max_model_len", 8192)),
        "--max-num-seqs",
        "1",
        "--pipeline-parallel-size",
        str(layout["pipeline_parallel_size"]),
        "--tensor-parallel-size",
        "1",
        "--distributed-executor-backend",
        "mp",
        "--gpu-memory-utilization",
        "0.85",
        "--seed",
        str(config.get("seed", 42)),
        "--enforce-eager",
    ]


def _wait_server(process, url, timeout=900):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if process.poll() is not None:
            raise NimbusError(
                "model_server_exited",
                "Private LLM server exited; inspect vllm.log in the run directory.",
            )
        try:
            response = httpx.get(url + "/models", timeout=5, trust_env=False)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise NimbusError(
        "model_server_timeout", "Model server did not become ready; inspect vllm.log."
    )


def run_runtime(config):
    from .inference.base import pinned_revision

    info = environment_info()
    layout = choose_layout(config, info)
    run_id = (
        config.get("run_id") or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    )
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise NimbusError("invalid_run_id", "Run ID must be a simple directory name.")
    results = Path(config["results_dir"]).resolve() / run_id
    results.mkdir(parents=True, exist_ok=False)
    root = Path(config["repo_dir"]).resolve()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    seed = int(config.get("seed", 42))
    random.seed(seed)
    revisions = {}
    models = {}
    metadata = {
        "git_commit": commit,
        "environment": info,
        "layout": layout,
        "models": models,
        "model_revisions": revisions,
        "seed": seed,
        "config": {
            key: value
            for key, value in config.items()
            if "key" not in key.lower() and "token" not in key.lower()
        },
        "status": "resolving_models",
    }
    (results / "run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    processes, logs = [], []
    previous_handler = signal.getsignal(signal.SIGTERM)

    def stop_requested(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_requested)

    def launch(arguments, name, environment=None):
        log = (results / f"{name}.log").open("w", encoding="utf-8")
        logs.append(log)
        process = subprocess.Popen(
            arguments,
            cwd=root,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        processes.append(process)
        return process

    try:
        for capability in layout["capabilities"]:
            model_id = layout["models"][capability]
            models[capability] = model_id
            revisions[capability] = pinned_revision(
                model_id, capability, layout["model_revisions"][capability]
            )
        metadata["status"] = "starting"
        (results / "run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        llm_url = f"http://127.0.0.1:{config.get('llm_port', 9000)}/v1"
        if layout["capabilities"] == ["llm"] and layout["llm_backend"] == "vllm":
            server = launch(vllm_command(models["llm"], revisions["llm"], config, layout), "vllm")
            _wait_server(server, llm_url)
        for capability in layout["capabilities"]:
            worker_mode = config.get("mode", "worker") == "worker"
            command = [
                sys.executable,
                "-m",
                "nimbus.cli",
                "worker" if worker_mode else "infer",
                capability,
                "--model-id",
                models[capability],
                "--revision",
                revisions[capability],
                "--device",
                layout["devices"][capability],
            ]
            if capability == "llm":
                command += ["--llm-backend", layout["llm_backend"], "--llm-url", llm_url]
            if worker_mode:
                command += [
                    "--bridge-url",
                    config["bridge_url"],
                    "--results-dir",
                    str(results / capability),
                ]
                if config.get("once"):
                    command.append("--once")
            elif config.get("inputs", {}).get(capability):
                command += ["--input", config["inputs"][capability]]
            environment = os.environ.copy()
            environment["PYTHONUNBUFFERED"] = "1"
            environment["PYTHONHASHSEED"] = str(seed)
            environment["NIMBUS_RUNTIME_SEED"] = str(seed)
            # Each media subprocess sees exactly its assigned physical GPU.
            if capability != "llm" and layout["devices"][capability].startswith("cuda"):
                environment["CUDA_VISIBLE_DEVICES"] = layout["devices"][capability].split(":")[1]
                command[command.index("--device") + 1] = "cuda:0"
            launch(command, capability, environment)
        metadata["status"] = "running"
        (results / "run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(
            json.dumps({"run_id": run_id, "results_dir": str(results), "layout": layout}),
            flush=True,
        )
        # Worker mode remains alive until interrupted or a process exits. Smoke
        # mode waits for all consumer adapters and leaves logs for inspection.
        consumer_count = len(layout["capabilities"])
        consumers = processes[-consumer_count:]
        while True:
            exits = [process.poll() for process in consumers]
            if config.get("mode", "worker") == "worker" and not config.get("once"):
                if any(code is not None for code in exits):
                    raise NimbusError(
                        "worker_exited", "A worker exited; inspect its log before restarting."
                    )
            elif all(code is not None for code in exits):
                if any(code != 0 for code in exits):
                    raise NimbusError(
                        "smoke_execution_failed",
                        "One or more model execution checks failed; inspect the logs.",
                    )
                metadata["status"] = "completed"
                return {"results_dir": str(results), "status": "completed"}
            time.sleep(2)
    except KeyboardInterrupt:
        metadata["status"] = "stopped"
        return {"results_dir": str(results), "status": "stopped"}
    except Exception as error:
        metadata.update(
            status="failed",
            error={"type": type(error).__name__, "code": getattr(error, "code", None)},
        )
        raise
    finally:
        for process in reversed(processes):
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.terminate()
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
        for log in logs:
            log.close()
        (results / "run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        signal.signal(signal.SIGTERM, previous_handler)
