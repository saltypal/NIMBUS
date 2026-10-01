"""Explicit permissively licensed model registry; model loading is lazy.

Resource figures are conservative planning gates, not measured utilization. A
successful preflight still has to be followed by a real model load and smoke
request on the target runtime.
"""

from dataclasses import asdict, dataclass

from .errors import NimbusError


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    revision: str
    capability: str
    license: str
    backend: str
    supported_backends: tuple[str, ...]
    estimated_weight_gib: float
    minimum_runtime_gib: float
    minimum_system_ram_gib: float
    validation_status: str
    description: str


MODELS = {
    "speech": ModelSpec(
        "Systran/faster-whisper-large-v3",
        "edaa852ec7e145841d8ffdb056a99866b5f0a478",
        "speech",
        "MIT",
        "faster-whisper",
        ("faster-whisper",),
        2.9,
        5.0,
        8.0,
        "contract-tested; target-GPU execution unverified",
        "Multilingual speech; converted Whisper large-v3 artifact",
    ),
    "handwriting": ModelSpec(
        "Qwen/Qwen3-VL-4B-Instruct",
        "ebb281ec70b05090aa6165b016eac8ec08e71b17",
        "handwriting",
        "Apache-2.0",
        "transformers",
        ("transformers",),
        8.5,
        11.0,
        16.0,
        "contract-tested; handwriting quality and target-GPU execution unverified",
        "Vision transcription candidate; evaluate representative handwriting",
    ),
    "llm": ModelSpec(
        "Qwen/Qwen3-8B",
        "b968826d9c46dd6066d109eabc6255188de91218",
        "llm",
        "Apache-2.0",
        "vllm",
        ("vllm", "transformers"),
        15.3,
        20.0,
        24.0,
        "contract-tested; dual-T4 execution unverified",
        "Post-trained Qwen3 drafting candidate for a dual-GPU vLLM runtime",
    ),
    "embedding": ModelSpec(
        "Qwen/Qwen3-Embedding-0.6B",
        "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
        "embedding",
        "Apache-2.0",
        "sentence-transformers",
        ("sentence-transformers",),
        1.2,
        2.5,
        4.0,
        "registry-only; execution unverified",
        "Optional CPU retrieval encoder",
    ),
    "llm-small": ModelSpec(
        "Qwen/Qwen3-4B",
        "1cfa9a7208912126459214e8b04321603b3df60c",
        "llm",
        "Apache-2.0",
        "transformers",
        ("transformers", "vllm"),
        7.6,
        11.0,
        16.0,
        "contract-tested; target-hardware execution unverified",
        "Smaller post-trained drafting fallback for one GPU, P100, or CPU",
    ),
}


def resolve_model(model_id: str, capability: str) -> ModelSpec:
    for spec in MODELS.values():
        if spec.model_id == model_id and spec.capability == capability:
            return spec
    raise NimbusError("model_not_allowed", "Select a model from the explicit open-model registry.")


def list_models():
    return {name: asdict(spec) for name, spec in MODELS.items()}
