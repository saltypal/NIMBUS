# Dependency and environment setup

## Boundary between the local app and model workers

The local application is a Python 3.11 modular monolith. It contains FastAPI,
the ticket workflow, MongoDB access, job coordination, retrieval orchestration,
and tests. Its environment must remain CPU-friendly and reproducible on Windows.

Speech, handwriting/OCR, embedding experiments, and LLM inference are separate
open-source model workers. They run in a Linux CUDA environment such as Kaggle,
where the notebook validates the accelerator and records the exact versions it
actually used. Do not install PyTorch, CTranslate2 CUDA packages, or vLLM into
the Windows application environment merely to make imports succeed.

## Local prerequisites

Use Python 3.11. The project intentionally supports `>=3.11,<3.14`: the local
model-worker ecosystem has compiled dependencies that may lag behind a newly
released Python version. Node/npm is required by the React UI and the isolated
browser-check tool.

MongoDB is an external service. The application has no hidden embedded database.
Set `NIMBUS_MONGO_URI` in `.env` when a MongoDB server is available. Unit tests
use fakes and pure modules; Mongo integration tests activate with
`NIMBUS_TEST_MONGO=1`. A non-service local MongoDB helper is included for development:

```powershell
.\scripts\install-mongodb-local.ps1
.\scripts\start-mongodb.ps1
```

It downloads the official Windows ZIP into the ignored `.tools/mongodb` path,
stores data in ignored `.data/mongodb`, and binds only to `127.0.0.1:27017`.
It never registers a Windows service or changes the global `PATH`. Stop it with
`Ctrl+C` in the terminal that started it. The database is intentionally not
exposed through the web or worker tunnel.

With `mongod` running, prove the database is reachable with one isolated,
auto-cleaned read/write test:

```powershell
.\scripts\test-mongodb.ps1
```

From the repository root, create or refresh the environment:

```powershell
.\scripts\bootstrap-local.ps1
```

To recreate it from scratch:

```powershell
.\scripts\bootstrap-local.ps1 -Recreate
```

This creates `.venv`, installs the local application plus development tools,
runs `pip check`, and writes an exact local `requirements/local.lock.txt` snapshot.
The lock snapshot is evidence of one tested environment; `pyproject.toml` remains
the editable dependency contract.

## Local commands

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pip check
```

The implemented modules can run independently:

```powershell
.\.venv\Scripts\python.exe -m nimbus.cli doctor
.\.venv\Scripts\python.exe -m nimbus.cli --storage mongo process --once
.\.venv\Scripts\python.exe -m nimbus.cli api --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m nimbus.cli bridge --host 127.0.0.1 --port 8001
```

Global CLI options, including `--output`, must precede the command:

```powershell
.\.venv\Scripts\python.exe -m nimbus.cli --output output\doctor.json doctor
```

Build and check the frontend from its own directory:

```powershell
npm --prefix web ci
npm --prefix web run build
npm --prefix web audit --omit=dev --audit-level=high
```

## Headless browser smoke setup

Browser tooling is intentionally outside `web/node_modules` so a smoke tool never
changes application dependencies. Bootstrap it from the repository root:

```powershell
.\scripts\bootstrap-browser-check.ps1
```

This uses installed Google Chrome through Playwright's `chrome` channel and runs
headlessly unless `--headed` is explicitly passed. If Chrome is unavailable, download
a Playwright-managed Chromium build with:

```powershell
.\scripts\bootstrap-browser-check.ps1 -InstallManagedChromium
```

The exact CLI is `.tools\browser-check\node_modules\.bin\playwright-cli.cmd`.
After the frontend preview is running, a CLI-first smoke loop is:

```powershell
Set-Location .tools\browser-check
.\node_modules\.bin\playwright-cli.cmd open http://127.0.0.1:4173 --browser chrome
.\node_modules\.bin\playwright-cli.cmd snapshot
.\node_modules\.bin\playwright-cli.cmd close
```

Save any screenshots, traces, or PDFs to `output/playwright/`; this generated
directory is ignored by Git.

## CUDA worker dependencies

The remote requirements are capability profiles for a fresh Linux/CUDA runtime:
`requirements/remote-media-cuda.txt` for speech/handwriting/embedding work and
`requirements/remote-llm-cuda.txt` for vLLM. `requirements/remote-cuda.txt` is
only an index. A notebook must install exactly the profile selected by its runtime
variable, then write a run manifest containing the Git SHA, Python version,
package versions, GPU name/count, CUDA driver/runtime, selected model revision,
and worker configuration.

Recommended open models, pending actual GPU benchmarks:

| Worker | Initial model | Why it is isolated |
| --- | --- | --- |
| Speech | `openai/whisper-large-v3` through `faster-whisper` | CUDA/CTranslate2 compatibility belongs in the speech notebook. |
| Handwriting | `Qwen/Qwen3-VL-4B-Instruct` | Apache-2.0 model; needs image-quality and handwriting accuracy evaluation. |
| LLM | `Qwen/Qwen3-8B` via vLLM | vLLM is Linux/CUDA only and needs dual-GPU startup validation. |
| Retrieval embeddings | `Qwen/Qwen3-Embedding-0.6B` | Start on local CPU; move only if measurement shows it is needed. |

`Qwen/Qwen3-VL-4B-Instruct` requires Transformers support for the `qwen3_vl`
architecture. The remote requirement begins at 4.57, but the notebook must verify
that its installed package imports the architecture before downloading weights.
Kaggle supplies PyTorch with its CUDA image; the notebook must retain that build
and fail its preflight if `torch.cuda.is_available()` is false instead of replacing
it with an arbitrary PyPI wheel.

The [`Qwen3-Embedding-0.6B` model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
documents `sentence-transformers>=2.7.0` and `transformers>=4.51.0`. The local
optional extra keeps `sentence-transformers>=3.3,<4`, which exceeds that minimum;
no dependency change is required. `OpenEncoder` remains lazy, so this optional
extra and its model weights are not part of the normal local application install.

Model selections are suggestions, not tested performance claims. No remote CUDA
dependency is considered working until the dedicated notebook completes its
health, one-input inference, and restart/recovery checks.

## Current machine availability check

Validated locally on 2026-10-02:

| Component | Evidence |
| --- | --- |
| Python app environment | Python 3.11.15; `pip check` passes. |
| MongoDB | Portable MongoDB 8.0.16 is installed in `.tools/mongodb`, listening only on `127.0.0.1:27017`; the isolated smoke test and enabled Mongo integration test pass. |
| Backend/module tests | 55 tests pass with `NIMBUS_TEST_MONGO=1`, including the real Mongo integration check; see `VALIDATION.md` for scope. |
| Frontend dependencies | `npm ci` and `npm --prefix web run build` pass; production dependency audit reports zero vulnerabilities. |
| Browser smoke tooling | Playwright 1.57.0 and `@playwright/cli` 0.1.22 are isolated under `.tools/browser-check`; a headless Chrome-channel open/snapshot/close check passes. |

Docker is not installed. No remote GPU model package, model weight, CUDA runtime,
or Kaggle worker has been validated in this environment.
