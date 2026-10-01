from datetime import UTC, datetime

import pytest

from nimbus.database import MemoryStore
from nimbus.errors import NimbusError
from nimbus.knowledge import Knowledge
from nimbus.processing import Coordinator
from nimbus.schemas import Action, Capture, Confirmation
from nimbus.service import Service
from nimbus.workflow import transition


def confirm_manual(service, capture, fields, *, ticket_version=None):
    submission = service.capture(capture)
    ready = Coordinator(service).process(submission["_id"])
    return service.confirm(
        ready["_id"],
        Confirmation(
            operation_id=f"confirm-{capture.client_operation_id}",
            draft_revision=ready["draft_revision"],
            text_revision=ready["selected_text_revision"],
            expected_processing_version=ready["processing_version"],
            expected_ticket_version=ticket_version,
            reviewed_by=capture.actor,
            fields=fields,
        ),
    )


def test_automotive_seed_is_idempotent_and_uses_reviewed_transitions(service):
    existing_ticket = {
        "_id": "existing_real_ticket",
        "origin_submission_id": "existing_real_submission",
        "status": "open",
        "title": "Existing user record",
    }
    service.store.insert("tickets", existing_ticket)
    first = service.seed_automotive()
    counts = {
        name: len(service.store.find(name))
        for name in (
            "organizations",
            "machines",
            "submissions",
            "tickets",
            "observations",
            "vehicles",
            "part_checks",
        )
    }
    second = service.seed_automotive()

    assert first["_id"] == "machine_a"  # legacy seed response remains usable
    assert service.required("tickets", existing_ticket["_id"]) == existing_ticket
    assert first["legacy"] is True
    assert first["organization"]["_id"] == "shift_over_motors"
    assert len(first["machines"]) >= 10
    assert all(machine["parts"] for machine in first["machines"])
    assert {machine["production_stage"] for machine in first["machines"]} >= {
        "stamping",
        "body",
        "welding",
        "paint",
        "powertrain",
        "trim",
        "final_qa",
    }
    assert {ticket["status"] for ticket in first["tickets"]} == {
        "open",
        "in_progress",
        "under_review",
        "closed",
    }
    assert all(ticket["origin_submission_id"] for ticket in first["tickets"])
    assert any(ticket["vehicle_id"] for ticket in first["tickets"])
    assert all(ticket["part_name"] and ticket["production_stage"] for ticket in first["tickets"])
    assert len(first["vehicles"]) == 7
    assert len(first["part_checks"]) == 49
    assert {check["result"] for check in first["part_checks"]} == {"pass", "issue", "pending"}
    for vehicle in first["vehicles"]:
        checks = [
            check for check in first["part_checks"] if check["vehicle_id"] == vehicle["vehicle_id"]
        ]
        assert {check["production_stage"] for check in checks} == set(
            first["organization"]["production_stages"]
        )
        assert vehicle["inspection_summary"] == {
            check["production_stage"]: check["result"] for check in checks
        }
    assert second["tickets"] == first["tickets"]
    assert {
        name: len(service.store.find(name))
        for name in (
            "organizations",
            "machines",
            "submissions",
            "tickets",
            "observations",
            "vehicles",
            "part_checks",
        )
    } == counts


def test_product_context_is_promoted_and_observation_context_remains_reported(
    service, operator
):
    machine_id = service.seed_automotive()["machines"][0]["_id"]
    report_fields = {
        "title": "Panel locator drift",
        "symptom": "Panel edge is outside the synthetic demo locator mark",
        "reported_condition": "restricted",
        "vehicle_id": "SOV-DEMO-0091",
        "part_name": "Front door outer LH",
        "production_stage": "stamping",
    }
    report = Capture(
        client_operation_id="automotive-context-report",
        actor=operator,
        shift_id="day",
        machine_id=machine_id,
        action=Action.REPORT,
        manual_fields=report_fields,
    )
    accepted = confirm_manual(service, report, report_fields)
    ticket = service.required("tickets", accepted["ticket_id"])
    assert (ticket["vehicle_id"], ticket["part_name"], ticket["production_stage"]) == (
        "SOV-DEMO-0091",
        "Front door outer LH",
        "stamping",
    )

    observation_fields = {
        "observation": "Locator witness mark moved after the last synthetic cycle",
        "context": "Observed during the demo handover walk",
        "impact": "Demo unit held for review",
        "suspected_cause": "Locator movement is suspected, not confirmed",
        "proposed_action": "Have maintenance inspect the locator",
        "vehicle_id": "SOV-DEMO-0091",
        "part_name": "Front door outer LH",
        "production_stage": "stamping",
        "fault_present": True,
    }
    observation = Capture(
        client_operation_id="automotive-context-observation",
        actor=operator,
        shift_id="day",
        machine_id=machine_id,
        ticket_id=ticket["_id"],
        action=Action.OBSERVATION,
        manual_fields=observation_fields,
    )
    confirm_manual(service, observation, observation_fields, ticket_version=ticket["version"])
    ticket = service.required("tickets", ticket["_id"])
    assert ticket["activities"][-1]["payload"]["suspected_cause"].endswith("not confirmed")
    assert "root_cause" not in ticket


def test_review_schedule_is_enforced_before_operator_verification(
    operator, supervisor, settings
):
    report = transition(
        None,
        Action.REPORT,
        operator,
        {
            "title": "Synthetic end-of-line alert",
            "symptom": "Demo alert remains active",
            "reported_condition": "stopped",
            "vehicle_id": "SOV-DEMO-0104",
            "part_name": "Vehicle unit",
            "production_stage": "final_qa",
        },
    )
    active = transition(report, Action.START, supervisor, {"work_intent": "Run demo correction"})
    policy, policy_hash = Knowledge(settings.knowledge_dir).policy(
        "automotive_demo_verification"
    )
    review_fields = {
        "work_summary": "Synthetic corrective step complete",
        "work_completed_at": "2026-09-15T10:00:00Z",
        "policy_id": policy.source_id,
        "policy_version": policy.policy_version,
        "verification_due_at": "2026-09-15T12:00:00Z",
        "verification_shift": "day",
    }
    reviewed = transition(
        active,
        Action.REVIEW,
        supervisor,
        review_fields,
        policy=policy,
        policy_hash=policy_hash,
    )
    assert reviewed["status"] == "under_review"
    assert reviewed["verification_plan"]["verification_due_at"].isoformat().startswith(
        "2026-09-15T12:00:00"
    )
    assert reviewed["next_action"]["verification_shift"] == "day"

    evidence = {
        "repair_cycle": reviewed["repair_cycle"],
        "policy_id": policy.source_id,
        "policy_version": policy.policy_version,
        "observed_at": "2026-09-15T11:59:59Z",
        "checks": [
            {
                "check_id": "synthetic_demo_cycle",
                "result": "pass",
                "evidence_text": "Operator observed three synthetic cycles",
                "cycles": 3,
                "condition": "synthetic_demo_condition",
                "fault_present": False,
            }
        ],
    }
    with pytest.raises(NimbusError) as captured:
        transition(
            reviewed,
            Action.VERIFY,
            operator,
            evidence,
            policy=policy,
            policy_hash=policy_hash,
        )
    assert captured.value.code == "verification_before_due"

    invalid_review = {**review_fields, "verification_due_at": "2026-09-15T09:59:59Z"}
    with pytest.raises(NimbusError) as captured:
        transition(
            active,
            Action.REVIEW,
            supervisor,
            invalid_review,
            policy=policy,
            policy_hash=policy_hash,
        )
    assert captured.value.code == "verification_due_predates_work"


def test_service_clock_rejects_future_observations(settings, operator):
    now = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)
    service = Service(MemoryStore(), settings, clock=lambda: now)
    service.seed()
    capture = Capture(
        client_operation_id="future-observation",
        actor=operator,
        shift_id="day",
        machine_id="machine_a",
        action=Action.OBSERVATION,
        observed_at=datetime(2026, 9, 15, 13, 1, tzinfo=UTC),
        manual_fields={"observation": "Impossible future reading"},
    )
    with pytest.raises(NimbusError) as captured:
        service.capture(capture)
    assert captured.value.code == "observation_in_future"

    seeded = service.seed_automotive()
    ticket = next(ticket for ticket in seeded["tickets"] if ticket["status"] == "under_review")
    verification_fields = {
        "repair_cycle": ticket["repair_cycle"],
        "policy_id": "automotive_demo_verification",
        "policy_version": 1,
        "observed_at": "2026-09-15T13:01:00Z",
        "checks": [
            {
                "check_id": "synthetic_demo_cycle",
                "result": "pass",
                "evidence_text": "This future evidence must not be accepted",
                "cycles": 3,
                "condition": "synthetic_demo_condition",
                "fault_present": False,
            }
        ],
    }
    verification = Capture(
        client_operation_id="future-verification",
        actor=operator,
        shift_id="day",
        machine_id=ticket["machine_id"],
        ticket_id=ticket["_id"],
        action=Action.VERIFY,
        manual_fields=verification_fields,
    )
    with pytest.raises(NimbusError) as captured:
        confirm_manual(
            service,
            verification,
            verification_fields,
            ticket_version=ticket["version"],
        )
    assert captured.value.code == "observation_in_future"
