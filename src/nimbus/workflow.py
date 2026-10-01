"""Pure ticket rules. No database, models, HTTP, or environment access.

Call transition() with a snapshot and receive a new snapshot. Persistence decides
whether that snapshot is still current through a conditional version update.
"""

from copy import deepcopy

from pydantic import ValidationError

from .errors import NimbusError
from .schemas import Action, Actor, CheckEvidence, Role, Status
from .util import parse_time

FORM_FIELDS = {
    Action.REPORT: (
        ["title", "symptom", "reported_condition"],
        [
            "recent_change",
            "immediate_action",
            "vehicle_id",
            "part_name",
            "production_stage",
        ],
    ),
    Action.OBSERVATION: (
        ["observation"],
        [
            "fault_present",
            "reported_condition",
            "vehicle_id",
            "part_name",
            "production_stage",
            "context",
            "impact",
            "suspected_cause",
            "proposed_action",
        ],
    ),
    Action.INSPECTION: (
        ["check_subject", "method", "finding", "next_action"],
        ["fault_present", "reported_condition"],
    ),
    Action.START: (["work_intent"], []),
    Action.WORK: (
        ["work_summary", "result", "next_action"],
        ["fault_present", "reported_condition"],
    ),
    Action.REVIEW: (
        ["work_summary", "work_completed_at", "policy_id", "policy_version"],
        ["verification_due_at", "verification_shift"],
    ),
    Action.VERIFY: (["repair_cycle", "policy_id", "policy_version", "observed_at", "checks"], []),
    Action.ACKNOWLEDGE: ([], []),
    Action.REOPEN: (["reason", "observation"], []),
}

MAINTAINERS = {Role.SUPERVISOR, Role.MAINTENANCE}


def allowed_roles(action: Action) -> set[Role]:
    if action in {Action.REPORT, Action.VERIFY}:
        return {Role.OPERATOR}
    if action in {Action.INSPECTION, Action.START, Action.WORK, Action.REVIEW}:
        return MAINTAINERS
    return set(Role)


def validate_role(action: Action, actor: Actor):
    if actor.role not in allowed_roles(action):
        raise NimbusError(
            "action_not_allowed_for_role", f"{actor.role} cannot perform {action}.", 403
        )


def missing_fields(action: Action, fields: dict) -> list[str]:
    required, _ = FORM_FIELDS[action]
    return [
        name
        for name in required
        if name not in fields or fields[name] is None or fields[name] == ""
    ]


def validate_fields(action: Action, fields: dict):
    required, optional = FORM_FIELDS[action]
    unexpected = set(fields) - set(required + optional)
    if unexpected:
        raise NimbusError(
            "unexpected_fields",
            "This action does not accept those fields.",
            details={"fields": sorted(unexpected)},
        )
    missing = missing_fields(action, fields)
    if missing:
        raise NimbusError(
            "fields_missing", "Required fields are missing.", details={"fields": missing}
        )
    for name in required:
        if name not in {"policy_version", "repair_cycle", "checks"}:
            if not isinstance(fields[name], str) or not fields[name].strip():
                raise NimbusError("invalid_field", f"{name} must be nonempty text.")
    text_fields = {
        "vehicle_id",
        "part_name",
        "production_stage",
        "context",
        "impact",
        "suspected_cause",
        "proposed_action",
    }
    for name in text_fields & fields.keys():
        if fields[name] is not None and (
            not isinstance(fields[name], str) or not fields[name].strip()
        ):
            raise NimbusError("invalid_field", f"{name} must be nonempty text when provided.")
    if "reported_condition" in fields and fields["reported_condition"] not in {
        "running",
        "stopped",
        "restricted",
        "unknown",
    }:
        raise NimbusError("invalid_condition", "Select running, stopped, restricted, or unknown.")
    if (
        "fault_present" in fields
        and fields["fault_present"] is not None
        and type(fields["fault_present"]) is not bool
    ):
        raise NimbusError("invalid_fault_result", "Fault presence must be true, false, or unknown.")
    for name in ("policy_version", "repair_cycle"):
        if name in fields and (type(fields[name]) is not int or fields[name] < 1):
            raise NimbusError("invalid_version", f"{name} must be a positive integer.")
    if (
        fields.get("verification_shift") is not None
        and fields["verification_shift"] not in {"day", "night"}
    ):
        raise NimbusError("invalid_verification_shift", "Select the day or night shift.")


def transition(
    ticket: dict | None,
    action: Action,
    actor: Actor,
    fields: dict,
    *,
    policy=None,
    policy_hash=None,
    demo_mode=True,
) -> dict:
    """Validate one reviewed action and return its prospective ticket state."""
    validate_role(action, actor)
    validate_fields(action, fields)
    if action == Action.REPORT:
        if ticket is not None:
            raise NimbusError("ticket_already_exists", "A fault report creates a new ticket.")
        return {
            "title": fields["title"],
            "symptom": fields["symptom"],
            "status": Status.OPEN.value,
            "version": 1,
            "content_revision": 1,
            "repair_cycle": 1,
            "cycle_requires_new_work": False,
            "reported_condition": fields["reported_condition"],
            "vehicle_id": fields.get("vehicle_id"),
            "part_name": fields.get("part_name"),
            "production_stage": fields.get("production_stage"),
            "verification_plan": None,
            "closure": None,
            "next_action": {"role": "supervisor", "description": "Inspect the reported fault"},
            "unresolved_contradiction": False,
            "activities": [],
            "handover_acknowledgments": [],
        }
    if ticket is None:
        raise NimbusError("ticket_required", "Select an existing ticket.")
    result = deepcopy(ticket)
    state = Status(ticket["status"])
    if action in {Action.OBSERVATION, Action.INSPECTION}:
        if state == Status.CLOSED and fields.get("fault_present") is True:
            raise NimbusError(
                "reopen_required", "Use Reopen to record recurrence against a closed fault."
            )
        if state == Status.UNDER_REVIEW and fields.get("fault_present") is True:
            result["unresolved_contradiction"] = True
    elif action == Action.START:
        if state == Status.CLOSED or (
            state == Status.IN_PROGRESS and not ticket["cycle_requires_new_work"]
        ):
            raise NimbusError("invalid_ticket_state", "There is no new work cycle to start.")
        if state == Status.UNDER_REVIEW or ticket["cycle_requires_new_work"]:
            result["repair_cycle"] += 1
        result.update(
            status=Status.IN_PROGRESS.value,
            cycle_requires_new_work=False,
            verification_plan=None,
            unresolved_contradiction=False,
        )
        result["next_action"] = {"role": actor.role.value, "description": fields["work_intent"]}
    elif action == Action.WORK:
        _require_active_work(ticket)
        result["next_action"] = {"role": actor.role.value, "description": fields["next_action"]}
    elif action == Action.REVIEW:
        _require_active_work(ticket)
        _validate_policy(policy, fields, demo_mode)
        try:
            completed = parse_time(fields["work_completed_at"])
        except (ValueError, TypeError) as error:
            raise NimbusError(
                "invalid_time", "Work completion time needs an ISO timestamp with timezone."
            ) from error
        due = None
        if "verification_due_at" in fields and fields["verification_due_at"] is not None:
            try:
                due = parse_time(fields["verification_due_at"])
            except (ValueError, TypeError) as error:
                raise NimbusError(
                    "invalid_time",
                    "Verification due time needs an ISO timestamp with timezone.",
                ) from error
            if due < completed:
                raise NimbusError(
                    "verification_due_predates_work",
                    "Verification cannot be scheduled before corrective work completed.",
                )
        result.update(status=Status.UNDER_REVIEW.value, unresolved_contradiction=False)
        result["verification_plan"] = {
            "policy_id": policy.source_id,
            "policy_version": policy.policy_version,
            "policy_content_hash": policy_hash,
            "repair_cycle": ticket["repair_cycle"],
            "work_completed_at": completed,
            "verification_due_at": due,
            "verification_shift": fields.get("verification_shift"),
            "required_checks": [check.model_dump() for check in policy.required_checks],
        }
        result["next_action"] = {
            "role": "operator",
            "description": "Complete the approved verification checks",
            "verification_due_at": due,
            "verification_shift": fields.get("verification_shift"),
        }
    elif action == Action.VERIFY:
        _verify(ticket, fields, result, policy, policy_hash, demo_mode)
    elif action == Action.REOPEN:
        if state != Status.CLOSED:
            raise NimbusError("invalid_ticket_state", "Only a closed fault can be reopened.")
        result.update(
            status=Status.OPEN.value,
            cycle_requires_new_work=True,
            verification_plan=None,
            unresolved_contradiction=True,
        )
        result["closure"] = None
        result["next_action"] = {"role": "supervisor", "description": fields["reason"]}
    if "reported_condition" in fields:
        result["reported_condition"] = fields["reported_condition"]
    for name in ("vehicle_id", "part_name", "production_stage"):
        if fields.get(name) is not None:
            result[name] = fields[name]
    result["version"] += 1
    if action != Action.ACKNOWLEDGE:
        result["content_revision"] += 1
    return result


def _require_active_work(ticket):
    if ticket["status"] != Status.IN_PROGRESS or ticket["cycle_requires_new_work"]:
        raise NimbusError(
            "invalid_ticket_state",
            "Start the required work cycle before recording or submitting work.",
        )


def _validate_policy(policy, fields, demo_mode):
    if policy is None or policy.approval_status not in {"approved", "approved_demo"}:
        raise NimbusError("policy_not_approved", "An approved verification policy is required.")
    if policy.approval_status == "approved_demo" and not demo_mode:
        raise NimbusError(
            "demo_policy_not_allowed", "Demo policies cannot authorize this deployment."
        )
    if fields["policy_id"] != policy.source_id or fields["policy_version"] != policy.policy_version:
        raise NimbusError(
            "policy_version_conflict", "The selected policy is not the current approved version."
        )


def _verify(ticket, fields, result, policy, policy_hash, demo_mode):
    if ticket["status"] != Status.UNDER_REVIEW:
        raise NimbusError("invalid_ticket_state", "Verification requires a ticket under review.")
    _validate_policy(policy, fields, demo_mode)
    plan = ticket["verification_plan"]
    if (
        fields["repair_cycle"] != ticket["repair_cycle"]
        or plan["repair_cycle"] != ticket["repair_cycle"]
    ):
        raise NimbusError("repair_cycle_conflict", "Evidence must verify the current repair cycle.")
    if plan["policy_content_hash"] != policy_hash:
        raise NimbusError(
            "policy_version_conflict", "Policy changed; record a reviewed replacement plan."
        )
    try:
        observed = parse_time(fields["observed_at"])
        checks = [CheckEvidence.model_validate(check) for check in fields["checks"]]
    except (ValueError, TypeError, ValidationError) as error:
        raise NimbusError(
            "invalid_verification", "Provide typed check evidence and a timezone-aware test time."
        ) from error
    if observed < parse_time(plan["work_completed_at"]):
        raise NimbusError(
            "verification_predates_work",
            "An earlier test cannot verify the latest corrective work.",
        )
    if plan.get("verification_due_at") and observed < parse_time(plan["verification_due_at"]):
        raise NimbusError(
            "verification_before_due",
            "Verification evidence was recorded before the scheduled verification time.",
        )
    required = {check.check_id: check for check in policy.required_checks}
    provided = {check.check_id: check for check in checks}
    if len(provided) != len(checks) or set(provided) - set(required):
        raise NimbusError(
            "invalid_check_ids", "Check IDs must be unique and belong to the verification plan."
        )
    failed = any(check.result == "fail" or check.fault_present is True for check in checks)
    if failed:
        result.update(
            status=Status.IN_PROGRESS.value,
            cycle_requires_new_work=True,
            unresolved_contradiction=True,
        )
        result["next_action"] = {
            "role": "maintenance",
            "description": "Start a new corrective cycle after failed verification",
        }
        return
    if ticket["unresolved_contradiction"]:
        raise NimbusError(
            "contradictory_evidence", "New fault evidence requires another corrective cycle."
        )
    missing = []
    for check_id, rule in required.items():
        evidence = provided.get(check_id)
        if evidence is None or evidence.result != "pass" or evidence.fault_present is not False:
            missing.append(check_id)
            continue
        if rule.minimum_cycles is not None and (
            evidence.cycles is None or evidence.cycles < rule.minimum_cycles
        ):
            missing.append(f"{check_id}.cycles")
        if rule.minimum_duration_seconds is not None and (
            evidence.duration_seconds is None
            or evidence.duration_seconds < rule.minimum_duration_seconds
        ):
            missing.append(f"{check_id}.duration_seconds")
        if rule.required_condition is not None and evidence.condition != rule.required_condition:
            missing.append(f"{check_id}.condition")
    if missing:
        raise NimbusError(
            "verification_fields_missing",
            "The required checks have not all passed.",
            details={"fields": missing},
        )
    result["status"] = Status.CLOSED.value
    result["closure"] = {
        "policy_id": policy.source_id,
        "policy_version": policy.policy_version,
        "repair_cycle": ticket["repair_cycle"],
        "observed_at": observed,
        "checks": [check.model_dump() for check in checks],
        "decision": {"engine": "backend_policy", "reason_code": "required_checks_passed"},
    }
    result["next_action"] = None
