"""Synthetic automotive demo domain and replay-safe seed scenarios."""

from copy import deepcopy
from datetime import UTC, datetime

from .schemas import Action, Actor, Capture, Confirmation, Role

ORGANIZATION = {
    "_id": "shift_over_motors",
    "name": "ShiftOver Motors",
    "plant_name": "Northstar Assembly Plant",
    "description": "A fictional vehicle plant used for the ShiftOver product experience.",
    "fictional": True,
    "demo_asset": True,
    "production_stages": [
        "stamping",
        "body",
        "welding",
        "paint",
        "powertrain",
        "trim",
        "final_qa",
    ],
    "stage_descriptions": {
        "stamping": "Forms exterior and structural sheet-metal parts.",
        "body": "Locates and frames the body structure.",
        "welding": "Joins body assemblies in robotic cells.",
        "paint": "Prepares, coats, and cures the body shell.",
        "powertrain": "Builds, tests, and installs the propulsion system.",
        "trim": "Installs cabin, restraint, electrical, and closure parts.",
        "final_qa": "Checks alignment, functions, and release evidence.",
    },
}


STAGE_PARTS = {
    "stamping": ["Hood outer", "Front door outer LH", "Body side outer RH"],
    "body": ["Body side aperture RH", "Underbody assembly", "Roof bow"],
    "welding": ["Roof rail joint LH", "B-pillar joint", "Rear floor crossmember"],
    "paint": ["Painted body shell", "E-coat surface", "Topcoat finish"],
    "powertrain": ["Powertrain carrier", "E-drive assembly", "Halfshaft connection"],
    "trim": ["Driver seat rail fastener", "Instrument panel harness", "Door weather seal"],
    "final_qa": ["Forward camera module", "Wheel alignment", "Vehicle unit"],
}


def _machine(machine_id, name, machine_type, stage, aliases=()):
    return {
        "_id": machine_id,
        "organization_id": ORGANIZATION["_id"],
        "name": name,
        "machine_type": machine_type,
        "production_stage": stage,
        "parts": STAGE_PARTS[stage],
        "aliases": list(aliases),
        "reported_condition": "unknown",
        "demo_asset": True,
        "synthetic": True,
        "legacy": False,
        "primary_product": True,
    }


MACHINES = [
    _machine("press_line_01", "Transfer Press Line 01", "transfer_press", "stamping", ["Press 01"]),
    _machine("blanking_line_02", "Laser Blanking Line 02", "laser_blanking", "stamping"),
    _machine("body_framer_01", "Body Framing Station 01", "body_framer", "body"),
    _machine("weld_cell_07", "Robotic Weld Cell 07", "robotic_weld_cell", "welding"),
    _machine("weld_cell_12", "Robotic Weld Cell 12", "robotic_weld_cell", "welding"),
    _machine("paint_pretreat_01", "Paint Pretreatment 01", "paint_pretreatment", "paint"),
    _machine("paint_booth_02", "Topcoat Booth 02", "paint_booth", "paint"),
    _machine("engine_line_01", "Engine Marriage Station 01", "engine_marriage", "powertrain"),
    _machine("edrive_test_01", "E-Drive Test Stand 01", "powertrain_test", "powertrain"),
    _machine("trim_line_01", "Trim Conveyor 01", "trim_conveyor", "trim"),
    _machine("alignment_01", "Wheel Alignment Rig 01", "wheel_alignment", "final_qa"),
    _machine("eol_qa_01", "End-of-Line QA 01", "end_of_line_test", "final_qa", ["EOL QA"]),
]


TICKET_SCENARIOS = [
    {
        "key": "stamping-locator",
        "machine_id": "press_line_01",
        "status": "open",
        "title": "Panel locator drift",
        "symptom": "Locator witness mark is offset after cycling",
        "reported_condition": "restricted",
        "vehicle_id": "SOV-0184",
        "part_name": "Front door outer LH",
        "production_stage": "stamping",
    },
    {
        "key": "body-clamp",
        "machine_id": "body_framer_01",
        "status": "open",
        "title": "Body fixture clamp indication",
        "symptom": "Clamp-ready indication is intermittent",
        "reported_condition": "stopped",
        "vehicle_id": "SOV-0188",
        "part_name": "Body side aperture RH",
        "production_stage": "body",
    },
    {
        "key": "weld-tip",
        "machine_id": "weld_cell_07",
        "status": "in_progress",
        "title": "Weld cell current warning",
        "symptom": "Current warning appeared on the trace",
        "reported_condition": "stopped",
        "vehicle_id": "SOV-0192",
        "part_name": "Roof rail joint LH",
        "production_stage": "welding",
    },
    {
        "key": "paint-airflow",
        "machine_id": "paint_booth_02",
        "status": "under_review",
        "title": "Paint booth airflow deviation",
        "symptom": "Airflow reading moved outside the target band",
        "reported_condition": "restricted",
        "vehicle_id": "SOV-0197",
        "part_name": "Painted body shell",
        "production_stage": "paint",
    },
    {
        "key": "engine-marriage",
        "machine_id": "engine_line_01",
        "status": "in_progress",
        "title": "Powertrain carrier position alert",
        "symptom": "Carrier position signal did not settle",
        "reported_condition": "stopped",
        "vehicle_id": "SOV-0201",
        "part_name": "Powertrain carrier",
        "production_stage": "powertrain",
    },
    {
        "key": "trim-torque",
        "machine_id": "trim_line_01",
        "status": "open",
        "title": "Trim tool torque trace missing",
        "symptom": "Torque trace was absent for one vehicle unit",
        "reported_condition": "restricted",
        "vehicle_id": "SOV-0205",
        "part_name": "Driver seat rail fastener",
        "production_stage": "trim",
    },
    {
        "key": "eol-camera",
        "machine_id": "eol_qa_01",
        "status": "closed",
        "title": "End-of-line camera alert",
        "symptom": "Camera check requested a repeat cycle",
        "reported_condition": "stopped",
        "vehicle_id": "SOV-0210",
        "part_name": "Forward camera module",
        "production_stage": "final_qa",
    },
]

STAGE_MACHINE = {
    "stamping": "press_line_01",
    "body": "body_framer_01",
    "welding": "weld_cell_07",
    "paint": "paint_booth_02",
    "powertrain": "engine_line_01",
    "trim": "trim_line_01",
    "final_qa": "eol_qa_01",
}


OPERATOR = Actor(person_id="demo_operator", display_name="Maya Rao", role=Role.OPERATOR)
SUPERVISOR = Actor(
    person_id="demo_supervisor", display_name="Elena Brooks", role=Role.SUPERVISOR
)
MAINTENANCE = Actor(
    person_id="demo_maintenance", display_name="Jon Bell", role=Role.MAINTENANCE
)


def seed_automotive(service, legacy_machine):
    """Seed stable demo records without replacing any existing document."""
    _insert_if_absent(service, "organizations", ORGANIZATION)
    for machine in MACHINES:
        _insert_if_absent(service, "machines", machine)

    seeded_tickets = []
    for scenario in TICKET_SCENARIOS:
        ticket = _seed_ticket(service, scenario)
        seeded_tickets.append(ticket)

    _seed_machine_observation(service)
    ticket_by_vehicle = {ticket["vehicle_id"]: ticket for ticket in seeded_tickets}
    for scenario in TICKET_SCENARIOS:
        _insert_if_absent(service, "vehicles", _vehicle_document(scenario))
        for check in _part_checks(scenario, ticket_by_vehicle[scenario["vehicle_id"]]):
            _insert_if_absent(service, "part_checks", check)
    return {
        **legacy_machine,
        "organization": service.required("organizations", ORGANIZATION["_id"]),
        "machines": [service.required("machines", machine["_id"]) for machine in MACHINES],
        "tickets": seeded_tickets,
        "vehicles": [
            service.required("vehicles", scenario["vehicle_id"])
            for scenario in TICKET_SCENARIOS
        ],
        "part_checks": service.store.find(
            "part_checks", {"organization_id": ORGANIZATION["_id"]}, limit=200
        ),
    }


def _insert_if_absent(service, collection, document):
    if service.store.get(collection, document["_id"]) is None:
        service.store.insert(collection, deepcopy(document))


def _vehicle_document(scenario):
    stage_index = ORGANIZATION["production_stages"].index(scenario["production_stage"])
    inspection_summary = {}
    for index, stage in enumerate(ORGANIZATION["production_stages"]):
        if index < stage_index or scenario["status"] == "closed":
            inspection_summary[stage] = "pass"
        elif index == stage_index:
            inspection_summary[stage] = "issue"
        else:
            inspection_summary[stage] = "pending"
    return {
        "_id": scenario["vehicle_id"],
        "vehicle_id": scenario["vehicle_id"],
        "organization_id": ORGANIZATION["_id"],
        "model": "Orion X1",
        "line": "Northstar Line A",
        "build": "2026-09-15 day shift",
        "current_stage": scenario["production_stage"],
        "disposition": "released" if scenario["status"] == "closed" else "held_for_review",
        "inspection_summary": inspection_summary,
        "synthetic": True,
    }


def _part_checks(scenario, ticket):
    stages = ORGANIZATION["production_stages"]
    issue_index = stages.index(scenario["production_stage"])
    checks = []
    for index, stage in enumerate(stages):
        if scenario["status"] == "closed" or index < issue_index:
            result = "pass"
            note = "Recorded inspection evidence met the fictional build criteria."
        elif index == issue_index:
            result = "issue"
            note = scenario["symptom"]
        else:
            result = "pending"
            note = "Inspection awaits the vehicle's arrival at this stage."
        part_name = scenario["part_name"] if index == issue_index else STAGE_PARTS[stage][0]
        checks.append(
            {
                "_id": f"check_{scenario['vehicle_id'].lower().replace('-', '_')}_{stage}",
                "organization_id": ORGANIZATION["_id"],
                "vehicle_id": scenario["vehicle_id"],
                "machine_id": STAGE_MACHINE[stage],
                "production_stage": stage,
                "part_name": part_name,
                "result": result,
                "note": note,
                "observed_at": datetime(2026, 9, 15, 6 + index, 0, tzinfo=UTC),
                "linked_ticket_id": ticket["_id"] if index == issue_index else None,
                "synthetic": True,
            }
        )
    return checks


def _seed_ticket(service, scenario):
    fields = {
        name: scenario[name]
        for name in (
            "title",
            "symptom",
            "reported_condition",
            "vehicle_id",
            "part_name",
            "production_stage",
        )
    }
    response = _confirm(
        service,
        key=f"seed-auto-{scenario['key']}-report-v1",
        actor=OPERATOR,
        machine_id=scenario["machine_id"],
        action=Action.REPORT,
        fields=fields,
    )
    ticket_id = response["ticket_id"]
    if scenario["status"] == "open":
        return service.required("tickets", ticket_id)

    _confirm(
        service,
        key=f"seed-auto-{scenario['key']}-start-v1",
        actor=MAINTENANCE,
        machine_id=scenario["machine_id"],
        ticket_id=ticket_id,
        action=Action.START,
        fields={"work_intent": "Perform the documented synthetic demo correction"},
    )
    if scenario["status"] == "in_progress":
        return service.required("tickets", ticket_id)

    _confirm(
        service,
        key=f"seed-auto-{scenario['key']}-work-v1",
        actor=MAINTENANCE,
        machine_id=scenario["machine_id"],
        ticket_id=ticket_id,
        action=Action.WORK,
        fields={
            "work_summary": "Completed the synthetic corrective step",
            "result": "Demo condition ready for independent operator verification",
            "next_action": "Operator performs the approved synthetic demo check",
            "fault_present": False,
            "reported_condition": "restricted",
        },
    )
    _confirm(
        service,
        key=f"seed-auto-{scenario['key']}-review-v1",
        actor=SUPERVISOR,
        machine_id=scenario["machine_id"],
        ticket_id=ticket_id,
        action=Action.REVIEW,
        fields={
            "work_summary": "Synthetic corrective work submitted for operator evidence",
            "work_completed_at": "2026-09-15T10:00:00Z",
            "policy_id": "automotive_demo_verification",
            "policy_version": 1,
            "verification_due_at": "2026-09-15T12:00:00Z",
            "verification_shift": "day",
        },
    )
    if scenario["status"] == "under_review":
        return service.required("tickets", ticket_id)

    ticket = service.required("tickets", ticket_id)
    _confirm(
        service,
        key=f"seed-auto-{scenario['key']}-verify-v1",
        actor=OPERATOR,
        machine_id=scenario["machine_id"],
        ticket_id=ticket_id,
        action=Action.VERIFY,
        fields={
            "repair_cycle": ticket["repair_cycle"],
            "policy_id": "automotive_demo_verification",
            "policy_version": 1,
            "observed_at": "2026-09-15T12:30:00Z",
            "checks": [
                {
                    "check_id": "synthetic_demo_cycle",
                    "result": "pass",
                    "evidence_text": "Operator recorded three synthetic demo cycles",
                    "cycles": 3,
                    "condition": "synthetic_demo_condition",
                    "fault_present": False,
                }
            ],
        },
    )
    return service.required("tickets", ticket_id)


def _seed_machine_observation(service):
    fields = {
        "observation": "Synthetic pretreatment conductivity trend noted for handover",
        "context": "Demo trend card reviewed during the day-shift walk",
        "impact": "No demo units affected; night shift asked to observe the next card",
        "suspected_cause": "A demo sensor drift is suspected and remains unconfirmed",
        "proposed_action": "Compare the next synthetic reading with the demo reference",
        "part_name": "Pretreated body shell",
        "production_stage": "paint",
    }
    _confirm(
        service,
        key="seed-auto-paint-observation-v1",
        actor=OPERATOR,
        machine_id="paint_pretreat_01",
        action=Action.OBSERVATION,
        fields=fields,
        observed_at=datetime(2026, 9, 15, 9, 0, tzinfo=UTC),
    )


def _confirm(
    service,
    *,
    key,
    actor,
    machine_id,
    action,
    fields,
    ticket_id=None,
    observed_at=None,
):
    """Run the same capture, coordinator, and confirmation path as a user action."""
    from .processing import Coordinator

    capture = Capture(
        client_operation_id=key,
        actor=actor,
        shift_id="day",
        machine_id=machine_id,
        ticket_id=ticket_id,
        action=action,
        observed_at=observed_at,
        manual_fields=fields,
        use_ai=False,
    )
    submission = service.capture(capture)
    if submission.get("confirmation"):
        return submission["confirmation"]
    ready = Coordinator(service).process(submission["_id"])
    current_ticket = service.store.get("tickets", ticket_id) if ticket_id else None
    return service.confirm(
        ready["_id"],
        Confirmation(
            operation_id=f"confirm-{key}",
            draft_revision=ready["draft_revision"],
            text_revision=ready["selected_text_revision"],
            expected_processing_version=ready["processing_version"],
            expected_ticket_version=current_ticket["version"] if current_ticket else None,
            reviewed_by=actor,
            fields=fields,
        ),
    )
