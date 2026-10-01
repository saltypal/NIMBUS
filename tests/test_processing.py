import pytest
from test_service import report_capture

from nimbus.errors import NimbusError
from nimbus.processing import Coordinator
from nimbus.schemas import Action


def test_llm_fixture_result_is_reviewed_never_committed(service, operator):
    service.settings.inference_enabled = True
    submission = service.capture(report_capture(operator), text="Unusual vibration")
    coordinator = Coordinator(service)
    pending = coordinator.process(submission["_id"])
    assert pending["processing_status"] == "awaiting_draft"
    queue = coordinator.queue
    worker = queue.register("llm", {"ready": True, "fixture": True})
    lease = queue.claim(worker["_id"], "llm")
    queue.result(
        lease["job_id"],
        "llm",
        lease["attempt_token"],
        worker["_id"],
        lease["attempt_id"],
        {
            "draft": {
                "fields": {"symptom": "Unusual vibration"},
                "field_evidence": {"symptom": "Unusual vibration"},
                "summary": "Vibration reported",
            },
        },
    )
    ready = coordinator.process(submission["_id"])
    assert ready["processing_status"] == "ready_for_review"
    assert service.store.find("tickets") == []


def test_model_cannot_invent_fields_or_citations():
    with pytest.raises(NimbusError):
        Coordinator.validate_model_draft(
            {"fields": {"symptom": "Resolved"}, "field_evidence": {"symptom": "Resolved"}},
            Action.REPORT,
            "Vibration",
            {"knowledge": []},
        )
    with pytest.raises(NimbusError):
        Coordinator.validate_model_draft(
            {"fields": {"status": "closed"}}, Action.REPORT, "Vibration", {"knowledge": []}
        )
    with pytest.raises(NimbusError):
        Coordinator.validate_model_draft(
            {"citations": [{"source_id": "invented", "chunk_id": "fake"}]},
            Action.REPORT,
            "Vibration",
            {"knowledge": []},
        )


def test_stale_llm_result_does_not_replace_human_correction(service, operator):
    service.settings.inference_enabled = True
    coordinator = Coordinator(service)
    submission = service.capture(report_capture(operator), text="Vibration")
    first = coordinator.process(submission["_id"])
    service.revise_text(first["_id"], "Vibration after replacement", operator)
    second = coordinator.process(first["_id"])
    assert first["draft_job_id"] != second["draft_job_id"]
    assert second["text_revisions"][-1]["origin"] == "human_correction"


def test_lexical_rag_returns_source_ids_and_persists_snapshot(service, operator):
    coordinator = Coordinator(service)
    ready = coordinator.process(
        service.capture(report_capture(operator), text="vibration verification cycles")["_id"]
    )
    context = ready["draft_context"]
    assert context["retrieval_backend"] == "lexical"
    assert context["knowledge"]
    assert context["policies"][0]["source_id"] == "demo_vibration_verification"
    assert service.store.find("knowledge_chunks")
