# NIMBUS

NIMBUS is a modular shift handover and maintenance ticket prototype. Operators report faults through text, voice, or handwriting. Supervisors record what they checked and found. A ticket closes automatically after an operator confirms evidence that satisfies an approved verification policy.

**“Checked” and “read” never mean “resolved.”** The backend owns workflow decisions; an LLM prepares drafts, questions, and suggestions.

## Implemented

- React interface: manual identity/role selection, per-machine Kanban, ticket history, handover, text/voice/drawing/image capture, transcript correction, form review, and processing inspection.
- FastAPI core, MongoDB persistence, preserved source files, append-only text corrections, idempotent confirmation, and ticket version checks.
- Independently runnable coordinator, capability-scoped worker bridge, durable jobs, leases, heartbeats, replay, expiration, and manual fallback.
- Markdown knowledge, citations, lexical retrieval, optional open embeddings, and retrieval of verified previous fixes.
- Open-model adapters and standalone repository-cloning notebooks for speech, handwriting, and LLM workloads.

Local workflow, real MongoDB, HTTP contracts, notebook reset, and browser flows have been tested. **Actual model inference, GPU package compatibility, handwriting accuracy, and Kaggle/tunnel connectivity remain unvalidated.** See [validation evidence](docs/VALIDATION.md).

## Run locally

From this repository root, in PowerShell:

```powershell
.\scripts\bootstrap-local.ps1
npm.cmd --prefix web ci
npm.cmd --prefix web run build
```

Start MongoDB in its own terminal if it is not already running:

```powershell
.\scripts\install-mongodb-local.ps1
.\scripts\start-mongodb.ps1
```

Then run the app in another terminal:

```powershell
.\.venv\Scripts\python.exe -m nimbus.cli doctor
.\.venv\Scripts\python.exe -m nimbus.cli api
```

Open [the local UI](http://127.0.0.1:8000) and choose **Load demo asset**. The [API reference](http://127.0.0.1:8000/docs) describes the implemented endpoints. No model download or worker is needed to use text and manual forms. Original audio/images can be saved, then manually transcribed while workers are unavailable.

Defaults are in `.env.example`; copy it to `.env` when changing configuration. Manual role selection is prototype identity, not staff authentication. All sample assets and verification criteria are synthetic.

## Run parts independently

```powershell
# Pure workflow: no database, HTTP server, or models.
.\.venv\Scripts\python.exe -m nimbus.cli workflow examples\workflow-report.json

# Full synthetic incident, explicitly nonpersistent storage.
.\.venv\Scripts\python.exe -m nimbus.cli --storage memory --output artifacts\demo.json demo

# Source capture and processing are separate steps with real persistence.
.\.venv\Scripts\python.exe -m nimbus.cli seed
.\.venv\Scripts\python.exe -m nimbus.cli capture examples\report-capture.json --input examples\report.txt
.\.venv\Scripts\python.exe -m nimbus.cli process --once

# Retrieval and registry do not require a running database.
.\.venv\Scripts\python.exe -m nimbus.cli retrieve "vibration verification"
.\.venv\Scripts\python.exe -m nimbus.cli models

# Separate bridge; keep the application and MongoDB local.
.\.venv\Scripts\python.exe -m nimbus.cli bridge
```

Global `--storage` and `--output` arguments go **before** the subcommand. A memory-store instance lasts for one process; separate commands use MongoDB to share state. Replaying the example capture is intentionally idempotent; change `client_operation_id` for a new report.

## Remote inference

Use [media_runtime.ipynb](notebooks/media_runtime.ipynb) for Account A and [llm_runtime.ipynb](notebooks/llm_runtime.ipynb) for Account B. Both contain their own setup, clone the repository, install a separate worker environment, detect hardware, and execute source modules.

Set `WORKLOAD` to `speech`, `handwriting`, `media`, or `llm`. Start with `MODE="smoke"`; use `MODE="worker"` after model execution succeeds. Set `REPO_URL`, `GIT_REF`, model IDs/revisions, backend, bridge URL, and results directory in the first setup cell.

The planned dual-T4 allocation is speech on Account A GPU 0, handwriting on GPU 1, and one LLM replica split across Account B's two GPUs. Workers make outward HTTPS requests to a restricted bridge; Kaggle does not need an incoming port. [Models and connection procedure](docs/MODELS_AND_RUNTIME.md) explain the complete setup.

**Commit and push the local implementation before a remote notebook can clone it.** A notebook deliberately fails when the selected remote commit lacks the source. Publishing this checkout is a separate action; no implementation commit has been made during this build.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest -q
$env:NIMBUS_TEST_MONGO = '1'
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:NIMBUS_TEST_MONGO
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m pip check
```

The Mongo test uses and deletes its own temporary database. It is opt-in and never silently substitutes memory storage.

## Learn and debug

| Document | Start here for |
| --- | --- |
| [Module guide](docs/MODULE_GUIDE.md) | Responsibilities, inputs/outputs, functions, independent commands, APIs, and debugging each stage |
| [Models and runtime](docs/MODELS_AND_RUNTIME.md) | Open-model choices, hardware, notebooks, secrets, tunneling, and persistence |
| [Dependency setup](docs/DEPENDENCY_SETUP.md) | Installed environments and reproducible bootstrap |
| [Implementation plan](docs/IMPLEMENTATION.md) | Delivery order and validation gates |
| [Validation](docs/VALIDATION.md) | Actual evidence and remaining limits |
| [System specification](docs/SYSTEM_ARCHITECTURE.md) | Detailed design, future scale requirements, and planned acceptance suite |

The prototype uses bounded collection scans, embedded ticket activities, and simple retrieval. Authentication, scalable indexes, archiving, knowledge publishing, persistent process supervision, and real model evaluations are later hardening work.
