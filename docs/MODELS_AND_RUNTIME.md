# ShiftOver models and remote runtime

ShiftOver keeps the FastAPI app and MongoDB on the laptop. Remote notebooks run only
open-weight inference workers and pull jobs outward through the restricted bridge on port
8001. The Python package and environment names remain `nimbus` and `NIMBUS_*` for backward
compatibility.

## Registered model profiles

The registry is an allowlist. Each default uses an immutable Hugging Face commit SHA; a
runtime manifest records the SHA actually resolved and used.

| Capability | Model | License | Default revision | Loader | Current evidence |
| --- | --- | --- | --- | --- | --- |
| Speech | [`Systran/faster-whisper-large-v3`](https://huggingface.co/Systran/faster-whisper-large-v3) | MIT | `edaa852ec7e145841d8ffdb056a99866b5f0a478` | faster-whisper | Contract tested; target GPU and factory audio unverified |
| Handwriting | [`Qwen/Qwen3-VL-4B-Instruct`](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct) | Apache-2.0 | `ebb281ec70b05090aa6165b016eac8ec08e71b17` | Transformers >=4.57 | Contract tested; target GPU and handwriting quality unverified |
| Drafting | [`Qwen/Qwen3-8B`](https://huggingface.co/Qwen/Qwen3-8B) | Apache-2.0 | `b968826d9c46dd6066d109eabc6255188de91218` | vLLM >=0.8.5 | Contract tested; dual-T4 execution unverified |
| Smaller drafting | [`Qwen/Qwen3-4B`](https://huggingface.co/Qwen/Qwen3-4B) | Apache-2.0 | `1cfa9a7208912126459214e8b04321603b3df60c` | Transformers or vLLM | Contract tested; target hardware unverified |
| Optional retrieval | [`Qwen/Qwen3-Embedding-0.6B`](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | Apache-2.0 | `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` | Sentence Transformers | Registry only; execution unverified |

Changing a notebook string cannot load an arbitrary model. A new entry requires a
permissive license, a loader implemented by the relevant adapter, a pinned revision, and
target-hardware validation.

## Why 27B is not the dual-T4 default

An official 27B post-trained model now exists:
[`Qwen/Qwen3.5-27B`](https://huggingface.co/Qwen/Qwen3.5-27B), Apache-2.0. It is not in the
runtime registry because the present adapter/environment does not establish a safe path on
two T4s:

- 27B parameters at two bytes per BF16 parameter is about **50.3 GiB of weights alone**.
  This calculation excludes the vision encoder, KV cache, activations, CUDA graphs, and
  allocator overhead.
- The official model card currently requires vLLM main/nightly and gives an eight-GPU
  reference command. The repository installs a bounded stable `vllm>=0.8.5,<1` profile.
- The official FP8 repository is still roughly 28B parameters and FP8 support on two T4s is
  not established by that card. T4 hardware also does not provide the newer native FP8 path
  implied by modern FP8 deployments.
- No official 4-bit artifact plus adapter path has been validated here. A community
  quantization is not accepted merely because its files may be smaller.

Those are compatibility and capacity findings, not a quality judgment. Add a 27B profile
only after choosing an officially supported quantization/loader and recording a real load,
structured-output request, peak VRAM, and restart test on the exact hardware.

## Calculated planning gates versus measured results

`choose_layout` checks conservative estimates before download. The current minimum runtime
estimates are 5 GiB for speech, 11 GiB for handwriting, 20 GiB total for Qwen3-8B, and 11
GiB for Qwen3-4B. For pipeline-parallel vLLM the LLM estimate is divided across its stages.
CPU mode checks physical RAM. Missing memory information fails closed.

These figures are **calculated planning limits**, not measured peaks. Passing preflight only
means the mismatch is not obvious. A successful target run must still record:

- exact Git commit and model revision;
- dependency snapshot, GPU name, compute capability, and VRAM;
- successful model load and smoke result;
- peak VRAM/RAM, cold-start time, request latency, and representative quality metrics.

No target GPU execution was performed while authoring this code.

## Hardware routing

| Hardware | Default behavior |
| --- | --- |
| CPU | Transformers/faster-whisper only; physical RAM must pass the estimate |
| One T4 | One media capability, or Qwen3-4B; explicit Qwen3-8B is rejected by the memory gate |
| Dual T4 | Combined media uses one GPU per capability; LLM uses Qwen3-8B with PP=2, TP=1 |
| P100 | Transformers Qwen3-4B fallback because vLLM profile requires compute capability >=7.5 |
| Larger supported CUDA GPU | Layout follows detected count/capability and still checks VRAM |
| TPU | Rejected; no XLA adapter exists |

`vLLM` binds only to `127.0.0.1` inside the notebook runtime. Workers make outbound bridge
requests. Never expose a notebook port or give the notebook MongoDB credentials.

## Generated notebooks

Run `scripts/create_notebooks.py` after changing notebook helpers or templates:

```powershell
$env:PYTHONPATH = "src"
python scripts/create_notebooks.py
```

Generated artifacts:

| Notebook | Workload |
| --- | --- |
| `notebooks/speech_runtime.ipynb` | Speech only |
| `notebooks/handwriting_runtime.ipynb` | Handwriting only |
| `notebooks/media_runtime.ipynb` | Speech on GPU 0 and handwriting on GPU 1 |
| `notebooks/llm_runtime.ipynb` | LLM only; dual-GPU Account B profile |

Each notebook performs a marked clean clone, checks out the requested ref detached, prints
the exact source commit, installs an isolated environment, records `pip freeze`, validates
hardware and resource estimates, starts owned processes, tails bounded logs, and archives
results. `MODEL_IDS` and `MODEL_REVISIONS` are capability-specific. Results live outside the
disposable clone.

Kaggle `/kaggle/working` survives only when you save a version with outputs or download the
archive. Colab defaults to mounted Drive. Local Jupyter defaults to `artifacts/notebook`.

## Product end-to-end test

The normal and safer route needs no core-app tunnel:

1. Start ShiftOver locally on port 8000 and the restricted bridge on port 8001.
2. Expose only port 8001 to the worker and start the notebook in `MODE="worker"`.
3. Open the local browser Test tab and submit audio or handwriting. Use the normal local
   capture/draft flow for LLM validation; a text inference-test completes locally and does
   not queue an LLM worker.
4. The local API queues the test, the remote worker pulls it through the bridge, and the Test
   tab polls the local result.

The media notebooks also contain an optional API cell using `POST /api/inference-tests` and
`GET /api/inference-tests/{id}`. `APP_API_URL` defaults empty because Kaggle localhost is not
the laptop. The LLM notebook explicitly skips this test because that endpoint does not queue
LLM work. Configure an app URL only through a private authenticated Tailscale or SSH path.
Do not publish the unauthenticated core API merely to run that cell.

## Reproducible commands

From the relevant worker environment:

```bash
python -m nimbus.cli infer speech --device cuda:0 --input note.wav
python -m nimbus.cli infer handwriting --device cuda:0 --input note.png
python -m nimbus.cli infer llm --device cpu --model-id Qwen/Qwen3-4B --revision 1cfa9a7208912126459214e8b04321603b3df60c --llm-backend transformers --input draft.json
python -m nimbus.cli runtime --config runtime-config.json
```

For the full two-account setup, follow [KAGGLE_QUICKSTART.md](KAGGLE_QUICKSTART.md).
