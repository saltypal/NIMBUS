# Validation evidence and limits

Validated locally on 2 October 2026. These are implementation checks, not a factory pilot or a GPU benchmark. All incident records, policies, and reported measurements used in testing are synthetic.

## Passed checks

| Check | Observed outcome |
| --- | --- |
| `NIMBUS_TEST_MONGO=1 python -m pytest -q` | **55 passed**, including real Mongo persistence/index/replay integration |
| Ruff source/test/script lint | Passed |
| Local `pip check` | No broken requirements |
| React TypeScript + Vite production build | Passed |
| Frontend dependency audit | Zero reported vulnerabilities at setup; this is a dated dependency check |
| CLI synthetic incident replay | Incomplete “Checked” rejected; inspection/acknowledgment preserve open state; valid operator evidence closes |
| Headless Chrome desktop/mobile UI | Report, incomplete inspection, correction, handover ack, work/review, insufficient verification, correction and closure passed |
| Mobile 390 × 844 viewport | Document width 390; no horizontal overflow |
| Pointer handwriting capture | Original PNG source saved; human transcript correction and machine-note confirmation passed |
| Voice controls | Recording and upload controls present; physical microphone capture was not exercised |
| Both notebooks | nbformat validation and code-cell compilation passed |
| Notebook first setup cell | Executed against a disposable local Git fixture without hidden project imports |
| Clean clone/reset | Fetched new fixture commit, handled Windows read-only Git files, retained results, refused unowned directories |
| Runtime layout | Fixture hardware tests cover CPU, P100, dual T4, unsupported TPU, invalid configuration, and PP2/TP1 command construction |
| Runtime failure metadata | Synthetic model-resolution failure retained a traceable failed manifest |
| Notebook shutdown | Stopped an actual owned controller/child process tree on Windows; the child's fixture heartbeat ceased |

Pytest reports one upstream Starlette/FastAPI TestClient deprecation warning about the httpx transport. The test suite passes; the warning is not a model/runtime result.

## Test ownership by layer

| Test module | What it verifies |
| --- | --- |
| `test_workflow.py` | Roles, state transitions, ambiguous checks, repair cycles, stale times, contradictions, policy changes, evidence limits |
| `test_service.py` | Source/revision retention, idempotency, clarification, machine notes, interrupted commits and recovery |
| `test_jobs.py` | Exclusive claims, readiness, capability scope, expiry, deadlines, replay, heartbeat/result races |
| `test_processing.py` | Draft review boundary, provenance/citations, stale-model jobs, lexical RAG snapshots |
| `test_knowledge.py` | Duplicate authorities, malformed metadata, revoked sources, vector dimensions/zero vectors |
| `test_http.py` | Multipart contracts, incomplete inspection, bridge credentials and result replay |
| `test_mongo.py` | Real opt-in Mongo persistence and index behavior; isolated database removed afterward |
| `test_worker.py` | Outbound HTTP consumer using an explicitly labeled fixture adapter |
| `test_runtime.py` | Hardware/config routing, clean reset, standalone first-cell execution, notebook contracts, failed manifest, owned process shutdown |
| `test_inference_contracts.py` | Prompt budget preservation, JSON parsing, open-model registry restrictions; no model weights |
| `test_cli.py` | Separate capture/process/inspect/confirm commands and Windows UTF-8 BOM handling |

The design specification's planned F01–F44 acceptance matrix is a separate future acceptance plan. Passing 55 implementation tests does not imply every item in that matrix, or every future feature, is complete.

## Reproduce fast and real-database checks

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
$env:NIMBUS_TEST_MONGO = '1'
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:NIMBUS_TEST_MONGO
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m pip check
npm.cmd --prefix web run build
```

Without the Mongo flag, the database check skips intentionally. The remaining tests use explicitly isolated stores/fixtures. Do not interpret an in-memory test as evidence that Mongo was exercised.

## Reproduce the browser workflow

Start Mongo, build the UI, and use an isolated demo database for the test app:

```powershell
$env:NIMBUS_DATABASE = 'nimbus_ui_smoke'
$env:NIMBUS_INFERENCE_ENABLED = 'false'
.\.venv\Scripts\python.exe -m nimbus.cli api
```

In another terminal at the repository root:

```powershell
.\scripts\bootstrap-browser-check.ps1
New-Item -ItemType Directory -Path output\playwright -Force | Out-Null
& '.\.tools\browser-check\node_modules\.bin\playwright-cli.cmd' open http://127.0.0.1:8000 --browser chrome
& '.\.tools\browser-check\node_modules\.bin\playwright-cli.cmd' snapshot
& '.\.tools\browser-check\node_modules\.bin\playwright-cli.cmd' run-code --filename scripts\smoke-ui.js
& '.\.tools\browser-check\node_modules\.bin\playwright-cli.cmd' close
```

The script writes uniquely named synthetic records and screenshots to `output/playwright/mobile.png` and `desktop.png`. It requires localhost, demo mode, and LLM drafting disabled. Expected HTTP 422 responses for intentionally rejected forms can appear as browser resource errors; they are verified rejections. It does not evaluate handwriting or speech model quality.

## Not yet validated

- Actual GPU package installation and model loading on Kaggle/Colab/local CUDA.
- Real speech, handwriting, embedding, or LLM outputs, accuracy, latency, and peak memory.
- Dual-T4 vLLM startup and a real structured-output request.
- Public tunnel authentication/connectivity and notebook session restart/reconnect.
- Physical microphones on phones/laptops and permission handling on representative browsers.
- Complete top-to-bottom execution of either GPU notebook. Structure/setup tests are not full notebook execution.
- Remote publication of this local implementation. Notebooks need a committed/pushed source ref.

## Current scope and hardening

Manual identities are client supplied; staff authentication is deferred. Verification records reported evidence and has no independent sensor truth. Current timestamps are checked for timezone and ordering, not synchronized against a factory clock. Scheduled maintenance intervals are not yet automatically generated.

Approved Markdown is Git managed. Policies are checked exactly by ID/version/hash, but there is no knowledge-author approval UI, staged index publication, or superseded-policy migration service. Retrieval uses bounded scans and optional freshly computed embeddings rather than an incremental vector index.

Tickets embed activities and stop at a configured size bound; archive/split large histories and paginate list endpoints before scale. Source files need backup alongside Mongo. Media garbage collection, superseded-job cancellation, job backoff/priorities, persistent local process supervision, and a stable tunnel hostname remain hardening work.

The next meaningful gate is one-input adapter execution on actual GPU hardware, followed by all three workers connected to the local bridge and representative-source evaluations. Keep those measured results separate from the fixture outcomes recorded here.
