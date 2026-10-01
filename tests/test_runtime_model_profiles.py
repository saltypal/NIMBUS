import nbformat
import pytest

from nimbus.config import ROOT
from nimbus.errors import NimbusError
from nimbus.models import MODELS, list_models
from nimbus.runtime import choose_layout


def hardware(*gpus, ram=64.0):
    return {
        "cuda_available": bool(gpus),
        "tpu_detected": False,
        "system_memory_gib": ram,
        "gpus": list(gpus),
    }


T4 = {"name": "Tesla T4", "compute_capability": [7, 5], "vram_gib": 15.0}
P100 = {"name": "Tesla P100", "compute_capability": [6, 0], "vram_gib": 16.0}


def test_registry_defaults_have_immutable_revisions_and_explicit_status():
    for name in ("speech", "handwriting", "llm", "llm-small"):
        spec = MODELS[name]
        assert len(spec.revision) == 40
        assert all(character in "0123456789abcdef" for character in spec.revision)
        assert "unverified" in spec.validation_status
        assert spec.license in {"MIT", "Apache-2.0"}
    assert "revision" in list_models()["llm"]


def test_each_media_workload_has_only_its_requested_capability():
    speech = choose_layout({"workload": "speech"}, hardware(T4))
    handwriting = choose_layout({"workload": "handwriting"}, hardware(T4))
    media = choose_layout({"workload": "media"}, hardware(T4, T4))
    assert speech["capabilities"] == ["speech"]
    assert handwriting["capabilities"] == ["handwriting"]
    assert media["capabilities"] == ["speech", "handwriting"]
    assert media["models"] == {
        "speech": MODELS["speech"].model_id,
        "handwriting": MODELS["handwriting"].model_id,
    }


def test_dual_t4_selects_8b_and_p100_selects_transformer_4b(monkeypatch):
    monkeypatch.setattr("nimbus.runtime.platform.system", lambda: "Linux")
    dual_t4 = choose_layout({"workload": "llm"}, hardware(T4, T4))
    assert dual_t4["llm_backend"] == "vllm"
    assert dual_t4["pipeline_parallel_size"] == 2
    assert dual_t4["models"]["llm"] == MODELS["llm"].model_id
    p100 = choose_layout({"workload": "llm"}, hardware(P100))
    assert p100["llm_backend"] == "transformers"
    assert p100["models"]["llm"] == MODELS["llm-small"].model_id


def test_preflight_rejects_model_memory_mismatch_before_download(monkeypatch):
    monkeypatch.setattr("nimbus.runtime.platform.system", lambda: "Linux")
    with pytest.raises(NimbusError) as captured:
        choose_layout(
            {"workload": "llm", "models": {"llm": MODELS["llm"].model_id}},
            hardware(T4),
        )
    assert captured.value.code == "model_memory_incompatible"
    with pytest.raises(NimbusError) as captured:
        choose_layout({"workload": "handwriting", "backend": "cpu"}, hardware(ram=8.0))
    assert captured.value.code == "model_memory_incompatible"


@pytest.mark.parametrize(
    "filename,workload",
    [
        ("speech_runtime.ipynb", "speech"),
        ("handwriting_runtime.ipynb", "handwriting"),
        ("media_runtime.ipynb", "media"),
        ("llm_runtime.ipynb", "llm"),
    ],
)
def test_generated_notebooks_are_single_profile_and_include_product_test(filename, workload):
    notebook = nbformat.read(ROOT / "notebooks" / filename, as_version=4)
    nbformat.validate(notebook)
    code = "\n".join(cell.source for cell in notebook.cells if cell.cell_type == "code")
    assert f'WORKLOAD = "{workload}"' in code
    assert "MODEL_REVISIONS" in code
    assert "/api/inference-tests" in code
    assert "APP_API_URL = \"\"" in code
    assert "TEST_AUDIO_PATH" in code
    assert "TEST_HANDWRITING_PATH" in code
    assert "TEST_TIMEOUT_SECONDS" in code
    assert "127.0.0.1" in code
    for index, cell in enumerate(cell for cell in notebook.cells if cell.cell_type == "code"):
        compile(cell.source, f"{filename}:cell{index}", "exec")
