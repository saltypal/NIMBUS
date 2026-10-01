"""Standard-library-only clone/bootstrap helpers, also embedded in first cells.

The repository may be absent, so the first notebook cell cannot import this file.
The notebook generator copies these small helpers rather than inference code.
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse


def remove_owned_directory(target, parent):
    target, parent = Path(target), Path(parent).resolve()
    resolved = target.resolve()
    if target.is_symlink() or resolved.parent != parent:
        raise ValueError("Deletion target escaped the dedicated runtime root.")

    def remove_readonly(function, filename, exception):
        if not isinstance(exception[1], PermissionError):
            raise exception[1]
        path = Path(filename).resolve()
        if resolved not in path.parents:
            raise ValueError("Read-only cleanup target escaped the owned directory.")
        os.chmod(filename, stat.S_IREAD | stat.S_IWRITE)
        function(filename)

    # Git marks object files read-only on Windows. Only remove that attribute
    # inside the already verified disposable clone/environment.
    shutil.rmtree(resolved, onerror=remove_readonly)


def runtime_paths(environment=None):
    environment = environment or (
        "kaggle"
        if Path("/kaggle").exists()
        else "colab"
        if "COLAB_RELEASE_TAG" in os.environ
        else "local"
    )
    if environment == "kaggle":
        return Path("/kaggle/working/nimbus-runtime"), Path("/kaggle/working/nimbus-results")
    if environment == "colab":
        return Path("/content/nimbus-runtime"), Path("/content/drive/MyDrive/nimbus-results")
    return Path(
        tempfile.gettempdir()
    ) / "nimbus-notebook-runtime", Path.cwd() / "artifacts/notebook"


def stop_runtime_process(process, config=None):
    """Stop this notebook's controller and its owned workers before reset.

    Windows terminate() bypasses Python finally blocks, so stop the owned process
    tree explicitly. Linux uses the controller's cooperative signal handler.
    """
    if process.poll() is not None:
        return process.returncode
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    else:
        process.terminate()
    code = process.wait(timeout=45)
    if os.name == "nt" and config and config.get("run_id"):
        import json

        manifest = Path(config["results_dir"]) / config["run_id"] / "run.json"
        if manifest.is_file():
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
            if metadata["status"] in {"starting", "running", "resolving_models"}:
                metadata.update(status="stopped", stop_method="windows_owned_process_tree")
                manifest.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return code


def sync_repository(repo_url, git_ref, runtime_root, results_dir, clean_reset=True):
    runtime_root, results_dir = Path(runtime_root).resolve(), Path(results_dir).resolve()
    source = runtime_root / "source"
    if source == Path.cwd().resolve() or source in Path.cwd().resolve().parents:
        raise ValueError("The disposable clone cannot contain the working notebook directory.")
    if results_dir == source or source in results_dir.parents:
        raise ValueError("Results must live outside the disposable source clone.")
    parsed = urlparse(str(repo_url))
    if parsed.username or parsed.password:
        raise ValueError("Do not embed a Git credential in the repository URL.")
    if not git_ref or git_ref.startswith("-"):
        raise ValueError("Choose a branch, tag, or commit SHA.")
    runtime_root.mkdir(parents=True, exist_ok=True)
    marker = source / ".nimbus-runtime-clone"
    if source.exists() and clean_reset:
        if (
            source.is_symlink()
            or not marker.is_file()
            or marker.read_text(encoding="utf-8").strip() != str(repo_url)
        ):
            raise ValueError(
                "Refusing to reset a directory without this notebook's clone ownership marker."
            )
        if source.resolve().parent != runtime_root:
            raise ValueError("Clone reset target escaped the dedicated runtime root.")
        remove_owned_directory(source, runtime_root)
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if not source.exists():
        subprocess.run(
            ["git", "clone", "--no-hardlinks", "--no-checkout", "--", str(repo_url), str(source)],
            check=True,
            env=environment,
        )
        marker.write_text(str(repo_url), encoding="utf-8")
    elif not marker.exists() or marker.read_text(encoding="utf-8").strip() != str(repo_url):
        raise ValueError("Existing source directory is not the requested disposable clone.")
    subprocess.run(["git", "fetch", "origin", git_ref], cwd=source, check=True, env=environment)
    subprocess.run(
        ["git", "checkout", "--detach", "FETCH_HEAD"], cwd=source, check=True, env=environment
    )
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if not (source / "pyproject.toml").exists() or not (source / "src/nimbus/runtime.py").exists():
        raise ValueError(
            "This commit lacks the NIMBUS implementation. Commit and push the local source first."
        )
    results_dir.mkdir(parents=True, exist_ok=True)
    return {"repo_dir": str(source), "results_dir": str(results_dir), "git_commit": commit}


def install_environment(repo_dir, runtime_root, profile, llm_backend="vllm", reset=False):
    repo_dir, runtime_root = Path(repo_dir).resolve(), Path(runtime_root).resolve()
    name = "media" if profile in {"speech", "handwriting", "media"} else "llm"
    environment = runtime_root / f"venv-{name}-{llm_backend if name == 'llm' else 'torch'}"
    marker = environment / ".nimbus-worker-env"
    if reset and environment.exists():
        if (
            environment.is_symlink()
            or environment.resolve().parent != runtime_root
            or not marker.is_file()
        ):
            raise ValueError("Refusing to reset an environment outside the owned runtime root.")
        remove_owned_directory(environment, runtime_root)
    if not environment.exists():
        # Media and transformer fallbacks inherit the platform's CUDA-enabled
        # torch. vLLM uses an isolated environment with its own matched stack.
        arguments = [sys.executable, "-m", "venv"]
        if name == "media" or llm_backend == "transformers":
            arguments.append("--system-site-packages")
        subprocess.run([*arguments, str(environment)], check=True)
        marker.write_text("nimbus", encoding="utf-8")
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(executable), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    # CPU notebook users without any preinstalled torch get an explicit CPU wheel.
    torch_present = (
        subprocess.run(
            [str(executable), "-c", "import torch"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )
    if not torch_present:
        if name == "media" or llm_backend == "transformers":
            subprocess.run(
                [
                    str(executable),
                    "-m",
                    "pip",
                    "install",
                    "torch",
                    "--index-url",
                    "https://download.pytorch.org/whl/cpu",
                ],
                check=True,
            )
    profile_file = (
        "remote-media-cuda.txt"
        if name == "media" or llm_backend == "transformers"
        else "remote-llm-cuda.txt"
    )
    subprocess.run(
        [
            str(executable),
            "-m",
            "pip",
            "install",
            "-e",
            str(repo_dir),
            "-r",
            str(repo_dir / "requirements" / profile_file),
        ],
        check=True,
    )
    subprocess.run([str(executable), "-m", "pip", "check"], check=True)
    return str(executable)


def fetch_secret(name):
    value = os.environ.get(name)
    if value:
        return value
    if Path("/kaggle").exists():
        from kaggle_secrets import UserSecretsClient

        return UserSecretsClient().get_secret(name)
    if "COLAB_RELEASE_TAG" in os.environ:
        from google.colab import userdata

        return userdata.get(name)
    raise ValueError(f"Set environment variable {name} for worker mode.")


def save_dependency_snapshot(executable, destination):
    output = subprocess.check_output([executable, "-m", "pip", "freeze"], text=True)
    Path(destination).write_text(output, encoding="utf-8")
    return {"snapshot": str(destination), "lines": len(output.splitlines())}
