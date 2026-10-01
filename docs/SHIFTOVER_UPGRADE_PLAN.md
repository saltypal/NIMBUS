# ShiftOver implementation plan

## Objective and constraints

Turn the existing shift handover prototype into an automotive operations workspace while preserving its evidence-based ticket workflow. Keep MongoDB and the core API local; GPU workers pull jobs from the restricted HTTPS bridge. Keep modules independently runnable and testable. Existing Python imports and environment variable names remain compatible during the product rename.

## Module contracts and ownership

| Module | Input → output | Dependencies | Owner | Acceptance gate |
| --- | --- | --- | --- | --- |
| Automotive organization | Idempotent seed → stations, machines, parts, vehicle identifiers, tickets | Service, policy engine, Markdown knowledge | Automotive agent | Repeat seed creates no duplicates; examples use normal reviewed transitions |
| Observation and review | Reviewed notes/work → auditable activity, scheduled verification | Pure workflow and CAS persistence | Automotive agent | No speculative cause becomes verified evidence; early verification is rejected |
| Operations UI | Role, machine, capture → board, history, draft | Core HTTP API | Frontend agent | Centered wheel selects; dark theme persists; narrow viewport remains usable |
| Inference tests and diagnostics | Original text/audio/image → receipt, job progress, transcript | Media store, job queue, worker bridge | Root | Core-to-bridge round trip uses the same worker contracts as normal capture |
| Kaggle runtime | Git ref, workload, models, secrets → workers and persistent run records | Owned environments and open models | Runtime agent | Speech/handwriting/LLM independently selectable; hardware incompatibility fails clearly |
| Database audit | Isolated Mongo fixture → CRUD, activity, job/workflow evidence | Real portable MongoDB | Audit agent | No user database deletion; stale writes/results rejected; final closure follows evidence |
| Integration | Built modules → usable local ShiftOver | All modules | Root | Python tests, frontend build, browser flow, real Mongo diagnostic check |

## Decisions

- Vehicle, part, and production stage are reported context attached to observations/tickets. A suspected cause remains a hypothesis.
- Completing corrective work moves a ticket to **Under review**. An operator records the approved verification checks at or after its scheduled time; the backend closes only when the evidence satisfies the current plan.
- There are no arbitrary Kanban status writes. Board actions invoke the existing workflow.
- Test uploads create inference-test records and normalization jobs, not production tickets.
- The browser polls the local API. Workers return results to the bridge; MongoDB holds the accepted job result. Notebook ports and MongoDB stay private.
- Keyword RAG remains the default. Optional embedding retrieval currently computes similarity in Python; it is not a MongoDB vector-search index.
- A 27B model in FP16 needs approximately 54 GB for weights alone. Dual 16 GB T4s cannot host that profile; any quantized larger model needs an explicit supported loader and a real GPU validation run.

## Validation and limitations

Validate each module before relying on it, then test the joined flow against real MongoDB and a browser. Test inference fixtures prove transport and persistence only. GPU inference, model accuracy, and a live Kaggle tunnel require the user’s remote runtime and are reported separately from local checks.
