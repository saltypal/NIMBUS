"""Synthetic incident replay through the same capture/confirm path as the UI."""

from datetime import timedelta

from .errors import NimbusError
from .processing import Coordinator
from .schemas import Action, Actor, Capture, Confirmation, Role
from .util import identifier, utcnow


def replay(service):
    service.seed()
    coordinator = Coordinator(service)
    day = Actor(person_id="op_day", display_name="Day operator", role=Role.OPERATOR)
    night = Actor(person_id="op_night", display_name="Night operator", role=Role.OPERATOR)
    supervisor = Actor(person_id="supervisor", display_name="Supervisor", role=Role.SUPERVISOR)
    ticket_id = None
    stages = []

    def record(action, actor, fields, text=None):
        nonlocal ticket_id
        current = service.store.get("tickets", ticket_id) if ticket_id else None
        capture = Capture(
            client_operation_id=identifier("demo_capture"),
            actor=actor,
            shift_id="night" if actor == night else "day",
            machine_id="machine_a",
            ticket_id=ticket_id,
            action=action,
            manual_fields=fields,
            use_ai=False,
        )
        ready = coordinator.process(service.capture(capture, text=text)["_id"])
        form = Confirmation(
            operation_id=identifier("demo_confirm"),
            reviewed_by=actor,
            draft_revision=ready["draft_revision"],
            text_revision=ready["selected_text_revision"],
            expected_processing_version=ready["processing_version"],
            expected_ticket_version=current["version"] if current else None,
            fields=fields,
        )
        result = service.confirm(ready["_id"], form)
        ticket_id = result["ticket_id"]
        stages.append(
            {
                "action": action.value,
                "status": result["status"],
                "ticket_version": result["ticket_version"],
            }
        )
        return result

    record(
        Action.REPORT,
        day,
        {
            "title": "Vibration after tool change",
            "symptom": "Unusual vibration",
            "reported_condition": "running",
            "recent_change": "Tool change",
        },
    )
    try:
        record(
            Action.INSPECTION, supervisor, {"finding": "Checked"}, "Checked; continue monitoring"
        )
    except NimbusError as error:
        stages.append({"action": "ambiguous_inspection", "rejected": error.code})
    record(
        Action.INSPECTION,
        supervisor,
        {
            "check_subject": "Tool mounting",
            "method": "Visual inspection",
            "finding": "No visible loose fastener",
            "next_action": "Monitor vibration",
        },
    )
    record(Action.ACKNOWLEDGE, night, {})
    record(Action.START, supervisor, {"work_intent": "Investigate and correct tool mounting"})
    record(
        Action.WORK,
        supervisor,
        {
            "work_summary": "Performed synthetic corrective action",
            "result": "Ready for demo verification",
            "next_action": "Test five demo cycles",
        },
    )
    record(
        Action.REVIEW,
        supervisor,
        {
            "work_summary": "Synthetic corrective work complete",
            "work_completed_at": (utcnow() - timedelta(minutes=5)).isoformat(),
            "policy_id": "demo_vibration_verification",
            "policy_version": 1,
        },
    )
    record(
        Action.VERIFY,
        night,
        {
            "repair_cycle": 1,
            "policy_id": "demo_vibration_verification",
            "policy_version": 1,
            "observed_at": utcnow().isoformat(),
            "checks": [
                {
                    "check_id": "demo_cycle_test",
                    "result": "pass",
                    "cycles": 5,
                    "condition": "demo_test_condition",
                    "fault_present": False,
                    "evidence_text": "Synthetic fixture: no vibration across five demo cycles",
                }
            ],
        },
    )
    return {
        "synthetic": True,
        "ticket_id": ticket_id,
        "stages": stages,
        "final_ticket": service.required("tickets", ticket_id),
    }
