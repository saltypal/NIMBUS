import pytest

from nimbus.database import MemoryStore
from nimbus.errors import NimbusError
from nimbus.processing import Coordinator
from nimbus.schemas import Action, Capture, Confirmation
from nimbus.service import Service


def report_capture(operator, key="first"):
    return Capture(
        client_operation_id=key,
        actor=operator,
        shift_id="day",
        machine_id="machine_a",
        action=Action.REPORT,
        manual_fields={
            "title": "Vibration",
            "symptom": "Unusual vibration",
            "reported_condition": "running",
        },
    )


def confirmation(submission, operator, fields=None, key="confirm-first", ticket_version=None):
    return Confirmation(
        operation_id=key,
        draft_revision=submission["draft_revision"],
        text_revision=submission["selected_text_revision"],
        expected_processing_version=submission["processing_version"],
        expected_ticket_version=ticket_version,
        reviewed_by=operator,
        fields=fields or submission["draft"]["fields"],
    )


def test_capture_draft_confirmation_and_idempotency(service, operator):
    capture = report_capture(operator)
    submission = service.capture(capture, text="Vibration after tool change")
    assert service.capture(capture, text="Vibration after tool change")["_id"] == submission["_id"]
    ready = Coordinator(service).process(submission["_id"])
    form = confirmation(ready, operator)
    accepted = service.confirm(ready["_id"], form)
    assert accepted["status"] == "open"
    assert service.confirm(ready["_id"], form) == accepted
    assert len(service.store.find("tickets")) == 1
    with pytest.raises(NimbusError):
        service.capture(capture, text="Different input")
    altered = form.model_copy(update={"fields": {**form.fields, "title": "Resolved"}})
    with pytest.raises(NimbusError):
        service.confirm(ready["_id"], altered)


def test_human_correction_preserves_original_and_rejects_old_draft(service, operator):
    submission = service.capture(report_capture(operator), text="Vibration")
    ready = Coordinator(service).process(submission["_id"])
    old_form = confirmation(ready, operator)
    service.revise_text(ready["_id"], "Vibration on machine A after tool change", operator)
    with pytest.raises(NimbusError) as captured:
        service.confirm(ready["_id"], old_form)
    assert captured.value.code == "submission_revision_conflict"
    current = Coordinator(service).process(ready["_id"])
    assert current["source"]["original_text"] == "Vibration"
    assert len(current["text_revisions"]) == 2
    assert current["draft_revision"] == 2


def test_clarification_attaches_and_does_not_create_second_ticket(service, operator):
    parent = service.capture(report_capture(operator), text="Vibration")
    Coordinator(service).process(parent["_id"])
    child_capture = report_capture(operator, "answer").model_copy(
        update={
            "purpose": "clarification",
            "parent_submission_id": parent["_id"],
            "manual_fields": {},
        }
    )
    child = service.capture(child_capture, text="Started after tool change")
    Coordinator(service).process(child["_id"])
    parent = Coordinator(service).process(parent["_id"])
    assert parent["clarification_ids"] == [child["_id"]]
    assert service.capture(child_capture, text="Started after tool change")["_id"] == child["_id"]
    with pytest.raises(NimbusError) as captured:
        service.confirm(child["_id"], confirmation(parent, operator))
    assert captured.value.code == "confirm_parent_required"
    service.confirm(parent["_id"], confirmation(parent, operator))
    assert len(service.store.find("tickets")) == 1


def test_machine_observation_is_a_note_without_fault_ticket(service, operator):
    capture = report_capture(operator).model_copy(
        update={
            "action": Action.OBSERVATION,
            "manual_fields": {"observation": "Routine reading recorded"},
        }
    )
    ready = Coordinator(service).process(service.capture(capture)["_id"])
    form = confirmation(ready, operator)
    accepted = service.confirm(ready["_id"], form)
    assert accepted["status"] == "recorded"
    assert not service.store.find("tickets")
    assert len(service.store.find("observations")) == 1
    assert service.confirm(ready["_id"], form) == accepted


def test_interrupted_confirmation_recovers_without_duplicate_activity(settings, operator):
    class InterruptStore(MemoryStore):
        interrupted = False

        def replace(self, collection, document, expected):
            if (
                collection == "submissions"
                and document.get("confirmation")
                and not self.interrupted
            ):
                self.interrupted = True
                raise RuntimeError("Injected interruption after ticket insert")
            return super().replace(collection, document, expected)

    service = Service(InterruptStore(), settings)
    service.seed()
    ready = Coordinator(service).process(service.capture(report_capture(operator))["_id"])
    form = confirmation(ready, operator)
    with pytest.raises(RuntimeError, match="Injected interruption"):
        service.confirm(ready["_id"], form)
    assert service.required("submissions", ready["_id"])["processing_status"] == "committing"
    assert service.reconcile() == 1
    accepted = service.confirm(ready["_id"], form)
    assert len(service.required("tickets", accepted["ticket_id"])["activities"]) == 1


def test_ticket_compare_and_swap_prevents_overwrite(service, operator, supervisor):
    coordinator = Coordinator(service)
    ready = coordinator.process(service.capture(report_capture(operator))["_id"])
    accepted = service.confirm(ready["_id"], confirmation(ready, operator))
    drafts = []
    for index in range(2):
        capture = Capture(
            client_operation_id=f"inspection-{index}",
            actor=supervisor,
            shift_id="day",
            machine_id="machine_a",
            ticket_id=accepted["ticket_id"],
            action=Action.INSPECTION,
            manual_fields={
                "check_subject": "Mounting",
                "method": "Visual",
                "finding": "Checked",
                "next_action": "Monitor",
            },
        )
        drafts.append(coordinator.process(service.capture(capture)["_id"]))
    service.confirm(
        drafts[0]["_id"], confirmation(drafts[0], supervisor, key="one", ticket_version=1)
    )
    with pytest.raises(NimbusError) as captured:
        service.confirm(
            drafts[1]["_id"], confirmation(drafts[1], supervisor, key="two", ticket_version=1)
        )
    assert captured.value.code == "ticket_version_conflict"
    assert service.required("tickets", accepted["ticket_id"])["version"] == 2
