# ShiftOver Kaggle quickstart

This setup uses two separately authorized Kaggle accounts:

- **Account A:** dual-GPU `media_runtime.ipynb`; speech uses GPU 0 and handwriting GPU 1.
- **Account B:** dual-GPU `llm_runtime.ipynb`; one Qwen3-8B vLLM replica uses PP=2, TP=1.

They are independent runtimes. They do not form a four-GPU cluster.

## 1. Publish the exact source

Remote notebooks clone Git and cannot see local uncommitted files. Test, commit, and push the
source, then record the commit:

```powershell
git status --short
git add src scripts notebooks requirements tests docs
git commit -m "Add ShiftOver remote model runtimes"
git push origin main
git rev-parse HEAD
```

Put that 40-character SHA in each notebook's `GIT_REF`. A branch works for exploration, but
the notebook will print the exact resolved commit and tell you to pin it.

## 2. Start only the local services

Follow the main dependency guide to start MongoDB and the ShiftOver API. Then configure
worker keys and run the restricted bridge:

```powershell
.\.venv\Scripts\python.exe scripts\configure-worker-keys.py
.\.venv\Scripts\python.exe -m nimbus.cli api --port 8000
.\.venv\Scripts\python.exe -m nimbus.cli bridge --port 8001
```

Expose **only bridge port 8001** through the chosen outbound tunnel. Do not expose MongoDB,
do not put Mongo credentials in Kaggle, and do not open incoming notebook ports. Store the
resulting HTTPS bridge origin in `BRIDGE_URL`.

## 3. Configure Account A

Upload `notebooks/media_runtime.ipynb`, enable Internet, and select two GPUs. Add these Kaggle
Secrets with the same values as the local bridge configuration:

- `NIMBUS_BRIDGE_SPEECH_KEY`
- `NIMBUS_BRIDGE_HANDWRITING_KEY`

Set `REPO_URL`, exact `GIT_REF`, and `BRIDGE_URL`. Keep the generated speech and handwriting
model IDs and revision SHAs together. First set `MODE="smoke"` and run through hardware
preflight/model execution. After that succeeds, change to `MODE="worker"`, rerun from the
clean-reset cell, and confirm both workers appear ready locally.

If only one GPU is available, use `speech_runtime.ipynb` or `handwriting_runtime.ipynb`.
Combined media intentionally fails on a one-GPU CUDA runtime.

## 4. Configure Account B

Upload `notebooks/llm_runtime.ipynb`, enable Internet, and select two GPUs. Add only:

- `NIMBUS_BRIDGE_LLM_KEY`

Set the same source/tunnel variables. The generated selector pins `Qwen/Qwen3-8B`. Preflight
expects roughly 10 GiB runtime capacity per pipeline stage and will reject an obvious
mismatch. This remains an estimate until the real server loads.

On one T4 or P100, use `Qwen/Qwen3-4B` and its registered revision instead. Do not select the
27B model: the repository has no validated two-T4 loader/quantization profile for it.

## 5. Verify the real product path

Leave `APP_API_URL=""` in Kaggle. On the laptop, open ShiftOver's Test tab at the local app,
then submit:

1. a short real audio file for speech in the Test tab;
2. a readable real handwritten note for vision in the Test tab;
3. a short text note through the normal capture/draft flow for the LLM worker.

The app stores media tests locally, the notebook workers pull through bridge port 8001, and
the browser polls the result. Text inference tests complete locally, so validate LLM drafting
through the real submission/draft flow. These paths require no core-app tunnel.

The optional notebook API test cell is for a deliberately configured private authenticated
Tailscale or SSH path to the app. Kaggle `127.0.0.1` is the Kaggle VM, not the laptop. Never
publish an unauthenticated core API for convenience.

## 6. Preserve evidence

Before ending each session:

1. inspect controller and worker logs;
2. run the explicit stop/archive cell;
3. save a Kaggle version with outputs or download the printed ZIP;
4. retain `run.json`, dependency snapshot, logs, receipts, exact Git SHA, and exact model SHAs;
5. label real measurements separately from calculated estimates and synthetic smoke results.

Kaggle working storage is temporary until outputs are saved. Local accepted results remain in
the laptop's MongoDB, but remote logs and diagnostics do not.

## 7. Repeat after a code change

The reproducible loop is:

```text
edit locally -> test -> commit -> push -> set new exact GIT_REF -> clean reset -> install/check
-> hardware preflight -> smoke -> worker -> browser Test tab -> save artifacts
```

Never pull new source underneath a running worker. Stop it, reset the owned clone, and start a
new run so every result maps to one source commit and one model revision.
