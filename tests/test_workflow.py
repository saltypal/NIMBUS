from copy import deepcopy

import pytest

from nimbus.errors import NimbusError
from nimbus.knowledge import Knowledge
from nimbus.schemas import Action
from nimbus.workflow import transition


def open_ticket(operator):
    return transition(
        None,
        Action.REPORT,
        operator,
        {
            "title": "Vibration after tool change",
            "symptom": "Unusual vibration",
            "reported_condition": "running",
        },
    )


def review_ticket(operator, supervisor, settings):
    ticket = open_ticket(operator)
    ticket = transition(ticket, Action.START, supervisor, {"work_intent": "Inspect and repair"})
    policy, content_hash = Knowledge(settings.knowledge_dir).policy("demo_vibration_verification")
    ticket = transition(
        ticket,
        Action.REVIEW,
        supervisor,
        {
            "work_summary": "Corrective work complete",
            "work_completed_at": "2026-10-01T20:00:00Z",
            "policy_id": policy.source_id,
            "policy_version": policy.policy_version,
        },
        policy=policy,
        policy_hash=content_hash,
    )
    return ticket, policy, content_hash


def evidence(ticket, result="pass", cycles=5):
    return {
        "repair_cycle": ticket["repair_cycle"],
        "policy_id": "demo_vibration_verification",
        "policy_version": 1,
        "observed_at": "2026-10-01T22:00:00Z",
        "checks": [
            {
                "check_id": "demo_cycle_test",
                "result": result,
                "evidence_text": "Observed the test and recorded the result",
                "cycles": cycles,
                "condition": "demo_test_condition",
                "fault_present": result == "fail",
            }
        ],
    }


def test_checked_and_acknowledgment_do_not_close(operator, supervisor):
    ticket = open_ticket(operator)
    original = deepcopy(ticket)
    with pytest.raises(NimbusError, match="Required fields"):
        transition(ticket, Action.INSPECTION, supervisor, {"finding": "Checked"})
    assert ticket == original
    checked = transition(
        ticket,
        Action.INSPECTION,
        supervisor,
        {
            "check_subject": "Tool mounting",
            "method": "Visual inspection",
            "finding": "Checked",
            "next_action": "Continue monitoring",
        },
    )
    acknowledged = transition(checked, Action.ACKNOWLEDGE, operator, {})
    assert acknowledged["status"] == "open"
    assert acknowledged["closure"] is None
    assert acknowledged["content_revision"] == checked["content_revision"]


def test_roles_are_enforced_without_llm(operator, supervisor):
    with pytest.raises(NimbusError) as captured:
        open_ticket(supervisor)
    assert captured.value.status == 403
    with pytest.raises(NimbusError):
        transition(open_ticket(operator), Action.START, operator, {"work_intent": "Repair"})


def test_operator_verification_closes_automatically(operator, supervisor, settings):
    ticket, policy, content_hash = review_ticket(operator, supervisor, settings)
    closed = transition(
        ticket, Action.VERIFY, operator, evidence(ticket), policy=policy, policy_hash=content_hash
    )
    assert ticket["status"] == "under_review"
    assert closed["status"] == "closed"
    assert closed["closure"]["decision"]["engine"] == "backend_policy"


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda fields: fields["checks"][0].update(cycles=4), "verification_fields_missing"),
        (
            lambda fields: fields["checks"][0].update(fault_present=None),
            "verification_fields_missing",
        ),
        (lambda fields: fields["checks"][0].update(cycles="5"), "invalid_verification"),
        (
            lambda fields: fields.update(observed_at="2026-10-01T19:00:00Z"),
            "verification_predates_work",
        ),
        (lambda fields: fields.update(repair_cycle=2), "repair_cycle_conflict"),
        (
            lambda fields: fields["checks"].append(deepcopy(fields["checks"][0])),
            "invalid_check_ids",
        ),
    ],
)
def test_incomplete_stale_and_untyped_evidence_rejected(
    operator, supervisor, settings, mutation, code
):
    ticket, policy, content_hash = review_ticket(operator, supervisor, settings)
    fields = evidence(ticket)
    mutation(fields)
    with pytest.raises(NimbusError) as captured:
        transition(ticket, Action.VERIFY, operator, fields, policy=policy, policy_hash=content_hash)
    assert captured.value.code == code


def test_failed_verification_requires_new_work_cycle(operator, supervisor, settings):
    ticket, policy, content_hash = review_ticket(operator, supervisor, settings)
    failed = transition(
        ticket,
        Action.VERIFY,
        operator,
        evidence(ticket, "fail"),
        policy=policy,
        policy_hash=content_hash,
    )
    assert failed["status"] == "in_progress"
    assert failed["cycle_requires_new_work"]
    with pytest.raises(NimbusError):
        transition(
            failed,
            Action.WORK,
            supervisor,
            {"work_summary": "Fixed", "result": "Pass", "next_action": "Test"},
        )
    restarted = transition(
        failed, Action.START, supervisor, {"work_intent": "Investigate recurrence"}
    )
    assert restarted["repair_cycle"] == ticket["repair_cycle"] + 1


def test_new_fault_blocks_review_and_changed_policy_blocks_closure(operator, supervisor, settings):
    ticket, policy, content_hash = review_ticket(operator, supervisor, settings)
    contradicted = transition(
        ticket,
        Action.OBSERVATION,
        operator,
        {"observation": "Vibration persists", "fault_present": True},
    )
    with pytest.raises(NimbusError) as captured:
        transition(
            contradicted,
            Action.VERIFY,
            operator,
            evidence(ticket),
            policy=policy,
            policy_hash=content_hash,
        )
    assert captured.value.code == "contradictory_evidence"
    with pytest.raises(NimbusError) as captured:
        transition(
            ticket, Action.VERIFY, operator, evidence(ticket), policy=policy, policy_hash="changed"
        )
    assert captured.value.code == "policy_version_conflict"


def test_demo_policy_cannot_authorize_real_mode(operator, supervisor, settings):
    ticket, policy, content_hash = review_ticket(operator, supervisor, settings)
    with pytest.raises(NimbusError) as captured:
        transition(
            ticket,
            Action.VERIFY,
            operator,
            evidence(ticket),
            policy=policy,
            policy_hash=content_hash,
            demo_mode=False,
        )
    assert captured.value.code == "demo_policy_not_allowed"
