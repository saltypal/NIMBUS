import json

import pytest

from nimbus.errors import NimbusError
from nimbus.inference.llm import packed_messages, parse_draft
from nimbus.models import resolve_model


class CountingTokenizer:
    """Context-packing fixture. It counts characters, not actual model tokens."""

    def apply_chat_template(self, conversation, **kwargs):
        return json.dumps(conversation)


def test_context_packing_keeps_current_input_and_drops_reference_context():
    current = "Vibration after tool change"
    payload = {
        "text": current,
        "context": {
            "knowledge": [{"text": "x" * 20_000}],
            "verified_history": [{"title": "y" * 20_000}],
        },
        "draft_schema": {"metadata": "unused in prompt"},
    }
    conversation = packed_messages(payload, CountingTokenizer(), context_limit=4000, max_tokens=200)
    packed = json.loads(conversation[1]["content"])
    assert packed["text"] == current
    assert packed["context"]["knowledge"] == []
    assert len(payload["context"]["knowledge"]) == 1
    with pytest.raises(NimbusError) as captured:
        packed_messages(
            {"text": "z" * 20_000}, CountingTokenizer(), context_limit=4000, max_tokens=200
        )
    assert captured.value.code == "input_context_too_long"


def test_json_contract_does_not_repair_model_fabrications():
    assert parse_draft('{"summary":"Vibration reported"}')["fields"] == {}
    with pytest.raises(ValueError):
        parse_draft('```json\n{"summary":"Checked"}\n```')
    with pytest.raises(ValueError):
        parse_draft('{"status":"closed"}')


def test_closed_license_model_is_not_in_registry():
    with pytest.raises(NimbusError):
        resolve_model("Qwen/Qwen2.5-VL-3B-Instruct", "handwriting")
    assert resolve_model("Qwen/Qwen3-VL-4B-Instruct", "handwriting").license == "Apache-2.0"
