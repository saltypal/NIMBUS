# MongoDB, job, and workflow audit

**Audit date:** 2 October 2026  
**Scope:** real local MongoDB behavior exercised by `tests/test_mongo_audit.py`  
**Evidence type:** local integration run with fixture model outputs; no model-weight inference

## Local MongoDB observed

The audit connected to `mongodb://127.0.0.1:27017`. The server process was PID 2728 at `D:\Bunker\BaseCamp\Agents\NIMBUS\.tools\mongodb\bin\mongod.exe`; `buildInfo.version` reported MongoDB **8.0.16**. The server listed `admin`, `config`, `local`, and the application database `nimbus`.

The following read-only snapshot was taken before the audit tests. Counts can change as the application is used.

| Database | Collection | Documents at snapshot | Indexes observed |
|---|---|---:|---|
| `nimbus` | `machines` | 1 | `_id_` |
| `nimbus` | `submissions` | 0 | `_id_`, unique `client_operation_id_1` |
| `nimbus` | `tickets` | 0 | `_id_`, unique `origin_submission_id_1`, `machine_id_1_status_1` |
| `nimbus` | `jobs` | 0 | `_id_`, unique `logical_key_1`, `capability_1_status_1` |

The five opt-in audit tests each use a separate `shiftover_audit_<32-hex-uuid>` database and drop only that exact database during fixture cleanup. They never use or drop `nimbus`. The core audio-to-ticket test observed this scratch database before cleanup:

| Collection | Documents |
|---|---:|
| `machines` | 1 |
| `submissions` | 1 |
| `tickets` | 1 |
| `jobs` | 1 |
| `workers` | 1 |
| `knowledge_chunks` | 2 |

`audit_records` also held one document in the separate store-contract test. The scratch DB is removed at test teardown, so those counts describe the assertion-time fixture, not durable application data.

`MongoStore.initialize()` creates unique indexes for submission client operation IDs, ticket origin submissions, and job logical keys. It also creates the ticket machine/status and job capability/status compound indexes. Machines and workers currently rely on MongoDB's `_id` index. There is no MongoDB delete operation in the `Store` protocol; application-level deletion is not exposed. The audit's destructive cleanup is confined to its private disposable test database.

## What the tests establish

`tests/test_mongo_audit.py` runs only when `NIMBUS_TEST_MONGO=1` is set. It covers:

- `MongoStore` insert/read/filter/update with a version compare-and-swap; an update with an old version is rejected and leaves the newer document intact.
- A stale ticket version is rejected by the service and does not append an activity to the current ticket.
- Ticket activities persisted across a new Mongo client through operator report → operator handover acknowledgment → supervisor start and review → operator verification → reopen. Acknowledgment leaves the ticket open and has no closure. Successful fixture verification closes it through the backend policy; reopen clears the current closure while retaining it in the reopen activity's `previous_closure`.
- Job logical-key idempotency, registered worker heartbeat, capability scoping, queue claim, retry after failure, rejection of an old attempt credential, expired-lease reaping, reassignment, and acceptance of the current attempt result.
- An audio file receipt saved by the core, converted into a scoped speech job, fetched by the bridge under the active lease, completed with an explicitly simulated transcript, then persisted as a text revision. The coordinator builds a lexical retrieval snapshot and the core API can read and confirm the result into a ticket.
- The `/api/inference-tests` path for synthetic audio and a valid PNG. Each upload is stored separately from production submissions and tickets; scoped workers download the exact original bytes and return fixture transcripts. Core reads expose success status plus worker/model/revision provenance, while omitting the source object and lease token.
- Automotive demo seeding twice against real MongoDB. The first call creates the fictional organization, 12 automotive machines alongside legacy `machine_a`, seven sample tickets across all four statuses, and one sample observation. Every sample ticket has persisted activity records. The second call returns the same seven ticket IDs and leaves organization, machine, submission, ticket, and observation counts unchanged.

The bridge test registers the supported `Systran/faster-whisper-large-v3` model ID with a fake `sha256:` revision. The payload is a short synthetic byte fixture and the transcript is fixture text. This proves the API/bridge/storage contract and status progression only; it does not exercise model loading, speech accuracy, handwriting OCR, LLM inference, or GPU behavior.

The separate inference-test API exercises both audio and handwriting transport with supported registry model IDs and fake immutable revision strings. Its accepted transcripts are simulated. They prove that original media, job ownership, and provenance cross the worker bridge and are readable from the core API; they say nothing about transcription or OCR quality. These records are stored under `inference_tests`, not operational `submissions`, and they do not create tickets.

The product seeding route is `POST /api/organization/seed`; it is separate from legacy `POST /api/demo/seed`, which only ensures the legacy `machine_a` demo asset. Automotive seeding includes that legacy asset for compatibility, then adds the fictional ShiftOver Motors organization, twelve synthetic automotive machines, seven status-varied sample tickets created through reviewed service actions, and one machine observation. The audit verifies replay idempotency against persisted counts and activity history. These are demo records, not production factory records.

The state progression tested is the repository's explicit job/worker and ticket workflow. It does not imply a general autonomous-agent framework. Workers register one capability (`speech`, `handwriting`, or `llm`), claim matching jobs, and return an attempt-scoped result. The local `Coordinator` advances submissions as durable results arrive.

## Retrieval boundary

The observed run used `retrieval_backend=lexical`; the persisted draft snapshot identifies that backend and contains matching knowledge chunks. The configured path does **not** use MongoDB Atlas Vector Search or another Mongo vector index. The optional `embedding` retrieval mode uses a local encoder and Python/NumPy similarity computation over candidates; the audit does not enable or benchmark it. No embedding-vector search claim should be inferred from these lexical results.

## Reproduce

From the repository root, with local MongoDB running:

```powershell
$env:NIMBUS_TEST_MONGO = '1'
.venv\Scripts\python.exe -m pytest tests\test_mongo_audit.py -q -s
```

To run the existing Mongo, worker, processing, service, and workflow regression checks alongside the audit:

```powershell
$env:NIMBUS_TEST_MONGO = '1'
.venv\Scripts\python.exe -m pytest tests\test_mongo.py tests\test_mongo_audit.py tests\test_jobs.py tests\test_worker.py tests\test_processing.py tests\test_service.py tests\test_workflow.py tests\test_http.py -q
```

The test fixture checks its database name against the private `shiftover_audit_<uuid>` pattern both before connecting and before dropping it. The tests use the project's existing virtual environment and do not install packages or change project configuration.
