# Implementation and validation plan

The source modules are the runtime source of truth. Notebooks clone the repository, select a workload, install that workload's dependencies, and invoke the same modules used by local commands.

## Delivery order

1. Typed contracts and a pure ticket state machine. Test role restrictions, ambiguous inspections, repair cycles, verification, and recurrence without a database or models.
2. Storage, source capture, and confirmation services. Provide MongoDB for persistence and an explicitly nonpersistent memory adapter for isolated tests. Validate retries, revision conflicts, and interrupted confirmation.
3. Durable processing jobs and the restricted worker bridge. Test claims, heartbeats, expiration, replay, and scope before loading models.
4. Markdown knowledge, retrieval, and processing. Keep lexical retrieval available without a model download; add an optional open embedding model through the same interface. Manual forms remain functional without inference.
5. Open-model adapters and configurable notebooks. Speech, handwriting, LLM, and combined media profiles have independent smoke commands and dependency groups. No local CUDA installation is required for the application.
6. Small React interface and end-to-end checks. Demonstrate the original incident, failed verification, and successful evidence-backed closure.

The dependency subagent owns environment installation, package metadata, dependency snapshots, and installation notes. The main agent owns source, tests, notebooks, and the UI. Every part has an independent command, diagnostic output, and focused tests before integration.

## Validation boundaries

Local tests must distinguish memory-adapter tests from real MongoDB tests. Notebook validation includes syntax, metadata, clean-clone setup, and workload selection. GPU model loading and accuracy cannot be claimed without actual GPU execution. Test doubles are labeled fixtures; they are never presented as model inference.

## Defaults

FastAPI/Pydantic/PyMongo, manual reporting roles, a four-state ticket workflow, three scoped worker capabilities, and optional MCP remain consistent with the architecture. Model candidates are the Systran faster-whisper large-v3 artifact, Qwen3-VL-4B-Instruct, Qwen3-8B, Qwen3-4B, and Qwen3-Embedding-0.6B. Adapters reject models outside the explicit open-model registry until the registry is deliberately extended. The previous Qwen2.5-VL-3B suggestion was replaced because its research license did not meet this project's permissive model-selection rule.

## Delivered module gates

| Part | Goal | Inputs → outputs | Dependencies | Owner | Acceptance |
| --- | --- | --- | --- | --- | --- |
| Contracts and workflow | Distinguish inspection from closure | Reviewed action/state/policy → prospective state | Pydantic | Main agent; user reviews core rules | Role/state/repair-cycle/evidence tests |
| Capture and storage | Preserve sources; apply one logical update | Capture/confirmation → durable records/receipt | Mongo or explicit isolated memory | Main agent | Retry, revisions, interrupted commit, real Mongo |
| Jobs and bridge | Distribute bounded inference work | Job → scoped lease → result | Store and HTTP | Main agent | Claims, expiration, replay, scope, heartbeat races |
| Knowledge and processing | Prepare traceable drafts | Text/state/retrieved context → draft/questions | Approved Markdown; optional models | Main agent | Citations, stale drafts, clarification, knowledge ambiguity |
| Adapters and runtime | Independent model capabilities | Audio/image/payload → transcript/draft | Separate worker environments | Main agent | Local adapter contracts; GPU execution pending |
| Notebook launchers | Reproduce remote source | Repo/ref/workload → clone/logs/manifest | Git, Python, profile | Main agent | Reset/results preservation/first-cell execution |
| Web interface | Exercise actual handover | Role/source/form → reviewed update | Local API | Main agent | Build, desktop/mobile browser workflow |
| Installation | Prevent dependency coupling | Manifests → checked environments | Python, Node, Mongo | Dependency subagent | Local installs, pip check, Mongo, npm checks |

Local gates passed at delivery; model/GPU/connectivity gates remain open. Run layers separately using the module guide. The next integration gate is `MODE="smoke"` on actual GPU hardware, followed by a worker connected to the bridge.
