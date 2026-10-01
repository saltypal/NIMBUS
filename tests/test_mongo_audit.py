"""Opt-in real-server audit for persistence and worker/workflow boundaries."""

import json
import os
import re
import wave
from datetime import timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from nimbus.api import create_app
from nimbus.bridge import create_app as create_bridge
from nimbus.database import MongoStore
from nimbus.errors import NimbusError
from nimbus.jobs import JobQueue
from nimbus.knowledge import Knowledge
from nimbus.models import MODELS
from nimbus.processing import Coordinator
from nimbus.schemas import Action, Capture, Confirmation
from nimbus.service import Service
from nimbus.util import utcnow


pytestmark = pytest.mark.skipif(
    os.getenv("NIMBUS_TEST_MONGO") != "1",
    reason="Set NIMBUS_TEST_MONGO=1 with local MongoDB running",
)


@pytest.fixture
def audit_store(settings, tmp_path):
    """Own and drop exactly one UUID-named database; never touch settings.database."""
    database_name = f"shiftover_audit_{uuid4().hex}"
    assert re.fullmatch(r"shiftover_audit_[0-9a-f]{32}", database_name)
    store = MongoStore(settings.mongo_uri, database_name)
    store.initialize()
    settings.data_dir = tmp_path / "nimbus-data"
    try:
        yield store, database_name
    finally:
        # Guard cleanup against a future fixture edit accidentally targeting app data.
        assert store.database.name == database_name
        assert re.fullmatch(r"shiftover_audit_[0-9a-f]{32}", store.database.name)
        store.client.drop_database(database_name)
        store.client.close()


def capture(
    actor,
    operation_id,
    action=Action.REPORT,
    *,
    ticket_id=None,
    fields=None,
    source_type="text",
):
    return Capture(
        client_operation_id=operation_id,
        actor=actor,
        shift_id="audit-shift",
        machine_id="machine_a",
        action=action,
        source_type=source_type,
        ticket_id=ticket_id,
        manual_fields=fields or {},
    )


def reviewed(service, actor, operation_id, action, fields, *, ticket_id=None, ticket_version=None):
    record = service.capture(
        capture(actor, operation_id, action, ticket_id=ticket_id, fields=fields),
        text=f"Audit fixture for {action.value}",
    )
    draft = Coordinator(service).process(record["_id"])
    form = Confirmation(
        operation_id=f"confirm-{operation_id}",
        draft_revision=draft["draft_revision"],
        text_revision=draft["selected_text_revision"],
        expected_processing_version=draft["processing_version"],
        expected_ticket_version=ticket_version,
        reviewed_by=actor,
        fields=draft["draft"]["fields"],
    )
    return service.confirm(draft["_id"], form)


def test_real_mongo_crud_cas_and_operator_supervisor_operator_history(
    audit_store, settings, operator, supervisor
):
    store, database_name = audit_store
    service = Service(store, settings)
    service.seed()

    # Store contract: create, read, filtered read, compare-and-swap update, stale write reject.
    record = {"_id": "audit-crud", "state": "created", "version": 1}
    assert store.insert("audit_records", record) == record
    assert store.get("audit_records", record["_id"]) == record
    assert store.find("audit_records", {"state": "created"}) == [record]
    changed = {**record, "state": "updated", "version": 2}
    assert store.replace("audit_records", changed, {"version": 1})
    assert not store.replace("audit_records", {**record, "state": "stale"}, {"version": 1})
    assert store.get("audit_records", record["_id"]) == changed

    accepted = reviewed(
        service,
        operator,
        "audit-report",
        Action.REPORT,
        {
            "title": "Audit fixture vibration",
            "symptom": "Simulated vibration report",
            "reported_condition": "running",
        },
    )
    ticket = service.required("tickets", accepted["ticket_id"])
    assert ticket["status"] == "open"
    assert len(ticket["activities"]) == 1

    # Stale ticket versions cannot append an activity over a newer state.
    stale_record = service.capture(
        capture(operator, "audit-stale-ack", Action.ACKNOWLEDGE, ticket_id=ticket["_id"]),
        text="Stale version fixture",
    )
    stale_draft = Coordinator(service).process(stale_record["_id"])
    stale_form = Confirmation(
        operation_id="confirm-audit-stale-ack",
        draft_revision=stale_draft["draft_revision"],
        text_revision=stale_draft["selected_text_revision"],
        expected_processing_version=stale_draft["processing_version"],
        expected_ticket_version=ticket["version"] - 1,
        reviewed_by=operator,
        fields={},
    )
    with pytest.raises(NimbusError) as stale_version:
        service.confirm(stale_draft["_id"], stale_form)
    assert stale_version.value.code == "ticket_version_conflict"
    assert len(service.required("tickets", ticket["_id"])["activities"]) == 1

    # An acknowledgment is a persisted activity but leaves the open fault open.
    reviewed(
        service,
        operator,
        "audit-ack",
        Action.ACKNOWLEDGE,
        {},
        ticket_id=ticket["_id"],
        ticket_version=ticket["version"],
    )
    ticket = service.required("tickets", ticket["_id"])
    assert ticket["status"] == "open"
    assert ticket["closure"] is None
    assert ticket["activities"][-1]["action"] == Action.ACKNOWLEDGE.value

    reviewed(
        service,
        supervisor,
        "audit-start",
        Action.START,
        {"work_intent": "Inspect audit fixture"},
        ticket_id=ticket["_id"],
        ticket_version=ticket["version"],
    )
    ticket = service.required("tickets", ticket["_id"])
    assert ticket["status"] == "in_progress"
    policy, policy_hash = Knowledge(settings.knowledge_dir).policy("demo_vibration_verification")
    reviewed(
        service,
        supervisor,
        "audit-review",
        Action.REVIEW,
        {
            "work_summary": "Fixture work complete",
            "work_completed_at": "2026-10-01T20:00:00Z",
            "policy_id": policy.source_id,
            "policy_version": policy.policy_version,
        },
        ticket_id=ticket["_id"],
        ticket_version=ticket["version"],
    )
    ticket = service.required("tickets", ticket["_id"])
    assert ticket["status"] == "under_review"
    assert ticket["verification_plan"]["policy_content_hash"] == policy_hash

    verified = reviewed(
        service,
        operator,
        "audit-verify",
        Action.VERIFY,
        {
            "repair_cycle": ticket["repair_cycle"],
            "policy_id": policy.source_id,
            "policy_version": policy.policy_version,
            "observed_at": "2026-10-01T22:00:00Z",
            "checks": [
                {
                    "check_id": "demo_cycle_test",
                    "result": "pass",
                    "evidence_text": "Synthetic audit fixture; not a real maintenance measurement.",
                    "cycles": 5,
                    "condition": "demo_test_condition",
                    "fault_present": False,
                }
            ],
        },
        ticket_id=ticket["_id"],
        ticket_version=ticket["version"],
    )
    assert verified["status"] == "closed"
    ticket = service.required("tickets", ticket["_id"])
    assert ticket["status"] == "closed"
    assert len(ticket["activities"]) == 5
    assert ticket["closure"]["decision"]["engine"] == "backend_policy"

    reopened = reviewed(
        service,
        operator,
        "audit-reopen",
        Action.REOPEN,
        {"reason": "Fixture recurrence", "observation": "Simulated recurrence"},
        ticket_id=ticket["_id"],
        ticket_version=ticket["version"],
    )
    assert reopened["status"] == "open"
    ticket = service.required("tickets", ticket["_id"])
    assert ticket["closure"] is None
    assert ticket["activities"][-1]["previous_closure"]["decision"]["engine"] == "backend_policy"

    # A separate client sees the persisted activity stream and indexes.
    observer = MongoStore(settings.mongo_uri, database_name)
    try:
        persisted = observer.get("tickets", ticket["_id"])
        assert [event["action"] for event in persisted["activities"]] == [
            Action.REPORT.value,
            Action.ACKNOWLEDGE.value,
            Action.START.value,
            Action.REVIEW.value,
            Action.VERIFY.value,
            Action.REOPEN.value,
        ]
        assert "client_operation_id_1" in observer.database.submissions.index_information()
        assert any(
            list(index["key"].items()) == [("machine_id", 1), ("status", 1)]
            for index in observer.database.tickets.list_indexes()
        )
        assert store.ping()
    finally:
        observer.client.close()


def test_real_mongo_job_scope_retry_stale_attempt_and_worker_heartbeat(
    audit_store, settings
):
    store, _ = audit_store
    now = [utcnow()]
    settings.job_lease_seconds = 10
    settings.job_max_runtime_seconds = 40
    queue = JobQueue(store, settings, clock=lambda: now[0])
    job = queue.ensure("audit-job", "speech", "normalize", {"fixture": True})
    assert queue.ensure("audit-job", "speech", "normalize", {"fixture": True})["_id"] == job["_id"]
    worker = queue.register("speech", {"ready": True, "fixture": True})
    before = worker["last_heartbeat_at"]
    worker = queue.worker_heartbeat(worker["_id"], "speech")
    assert worker["version"] == 2
    assert worker["last_heartbeat_at"] >= before
    with pytest.raises(NimbusError) as wrong_worker_scope:
        queue.claim(worker["_id"], "handwriting")
    assert wrong_worker_scope.value.status == 403

    first = queue.claim(worker["_id"], "speech")
    assert store.get("jobs", job["_id"])["status"] == "leased"
    with pytest.raises(NimbusError) as wrong_input_scope:
        queue.input(job["_id"], "handwriting", first["attempt_token"])
    assert wrong_input_scope.value.status == 403

    # Retryable failure returns the job to queued; previous attempt credentials go stale.
    failed = queue.fail(
        job["_id"], "speech", first["attempt_token"], worker["_id"], "fixture_retry"
    )
    assert failed["status"] == "queued"
    second = queue.claim(worker["_id"], "speech")
    assert second["attempt_id"] != first["attempt_id"]
    with pytest.raises(NimbusError):
        queue.result(
            job["_id"],
            "speech",
            first["attempt_token"],
            worker["_id"],
            first["attempt_id"],
            {"text": "stale fixture"},
        )

    now[0] += timedelta(seconds=settings.job_lease_seconds + 1)
    assert queue.reap() == 1
    assert store.get("jobs", job["_id"])["status"] == "queued"
    third = queue.claim(worker["_id"], "speech")
    assert third["attempt_id"] not in {first["attempt_id"], second["attempt_id"]}
    accepted = queue.result(
        job["_id"],
        "speech",
        third["attempt_token"],
        worker["_id"],
        third["attempt_id"],
        {"text": "Fixture output; simulated inference only"},
    )
    assert accepted["status"] == "succeeded"
    assert store.get("jobs", job["_id"])["result"]["text"].startswith("Fixture output")


def test_real_mongo_bridge_fixture_receipt_reaches_coordinator_and_core_api(
    audit_store, settings, operator
):
    store, _ = audit_store
    settings.bridge_speech_key = "audit-speech-key"
    service = Service(store, settings)
    service.seed()
    receipt = b"synthetic-audio-fixture"
    submission = service.capture(
        capture(
            operator,
            "audit-audio-capture",
            fields={
                "title": "Audio fixture report",
                "symptom": "Simulated transcript mentions vibration",
                "reported_condition": "running",
            },
            source_type="audio",
        ),
        payload=receipt,
        content_type="audio/wav",
    )
    pending = Coordinator(service).process(submission["_id"])
    assert pending["processing_status"] == "awaiting_normalization"
    job_id = pending["normalization_job_id"]

    # Registry identity is a supported model plus a fake immutable revision. This tests
    # transport and persistence only; no model weights or transcription accuracy are tested.
    model_id = "Systran/faster-whisper-large-v3"
    fake_sha = "sha256:" + ("a" * 64)
    with TestClient(create_bridge(settings, store)) as bridge:
        headers = {"Authorization": "Bearer audit-speech-key"}
        registration = bridge.post(
            "/bridge/workers/register",
            headers=headers,
            json={
                "capability": "speech",
                "model_id": model_id,
                "model_revision": fake_sha,
                "ready": True,
                "runtime": {"test_fixture": True},
            },
        )
        assert registration.status_code == 200, registration.text
        worker_id = registration.json()["_id"]
        worker_heartbeat = bridge.post(
            f"/bridge/workers/{worker_id}/heartbeat", headers=headers
        )
        assert worker_heartbeat.status_code == 200
        claim_response = bridge.post(
            "/bridge/jobs/claim", headers=headers, json={"worker_id": worker_id}
        )
        lease = claim_response.json()["job"]
        assert lease["job_id"] == job_id
        attempt_headers = {
            **headers,
            "X-Attempt-Token": lease["attempt_token"],
        }
        input_data = bridge.get(lease["input_url"], headers=attempt_headers).json()
        assert input_data["source_type"] == "audio"
        assert "media_key" not in input_data
        media = bridge.get(input_data["media_url"], headers=attempt_headers)
        assert media.content == receipt
        output = {
            "text": "Fixture transcript: vibration after tool change (simulated inference).",
            "model_id": model_id,
            "model_revision": fake_sha,
        }
        result_response = bridge.post(
            f"/bridge/jobs/{job_id}/result",
            headers=attempt_headers,
            json={
                "worker_id": worker_id,
                "attempt_id": lease["attempt_id"],
                "output": output,
            },
        )
        assert result_response.status_code == 200, result_response.text

    ready = Coordinator(service).process(submission["_id"])
    assert ready["processing_status"] == "ready_for_review"
    assert ready["text_revisions"][0]["origin"] == "speech_model"
    assert ready["text_revisions"][0]["model"]["model_revision"] == fake_sha
    assert "Fixture transcript" in ready["text_revisions"][0]["text"]
    assert ready["draft_context"]["retrieval_backend"] == "lexical"
    assert ready["draft_context"]["knowledge"]

    with TestClient(create_app(settings, store, background=False)) as core:
        fetched = core.get(f"/api/submissions/{submission['_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["_id"] == submission["_id"]
        assert fetched.json()["draft_context"]["retrieval_backend"] == "lexical"
        form = {
            "operation_id": "audit-audio-confirm",
            "draft_revision": ready["draft_revision"],
            "text_revision": ready["selected_text_revision"],
            "expected_processing_version": ready["processing_version"],
            "reviewed_by": operator.model_dump(mode="json"),
            "fields": ready["draft"]["fields"],
        }
        accepted = core.post(f"/api/submissions/{submission['_id']}/confirm", json=form)
        assert accepted.status_code == 200, accepted.text
        fetched_ticket = core.get(f"/api/tickets/{accepted.json()['ticket_id']}")
        assert fetched_ticket.status_code == 200
        assert fetched_ticket.json()["activities"][0]["submission_id"] == submission["_id"]

    counts = {
        name: store.database[name].count_documents({})
        for name in sorted(store.database.list_collection_names())
    }
    print(
        json.dumps(
            {
                "database": store.database.name,
                "collections_and_counts": counts,
                "retrieval_backend": ready["draft_context"]["retrieval_backend"],
                "embedding_vectors_in_mongo": False,
            },
            sort_keys=True,
        )
    )


def test_real_mongo_inference_test_api_audio_and_handwriting_provenance(
    audit_store, settings
):
    store, _ = audit_store
    settings.bridge_speech_key = "audit-speech-key"
    settings.bridge_handwriting_key = "audit-handwriting-key"
    fixtures = {}
    audio_buffer = BytesIO()
    with wave.open(audio_buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(bytes(3200))
    fixtures["audio"] = (
        "speech",
        audio_buffer.getvalue(),
        "audio.wav",
        "audio/wav",
        "Fixture transcript for transport only.",
    )
    image_buffer = BytesIO()
    Image.new("RGB", (80, 30), "white").save(image_buffer, format="PNG")
    fixtures["handwriting"] = (
        "handwriting",
        image_buffer.getvalue(),
        "note.png",
        "image/png",
        "Fixture handwriting transcription for transport only.",
    )

    with (
        TestClient(create_app(settings, store, background=False)) as core,
        TestClient(create_bridge(settings, store)) as bridge,
    ):
        for source_type, fixture in fixtures.items():
            capability, payload, filename, content_type, transcript = fixture
            create = core.post(
                "/api/inference-tests",
                data={"source_type": source_type},
                files={"file": (filename, payload, content_type)},
            )
            assert create.status_code == 201, create.text
            receipt = create.json()
            assert receipt["status"] == "queued"
            assert receipt["transcript"] is None
            assert not store.find("tickets")
            assert not store.find("submissions")

            key = f"audit-{capability}-key"
            model = MODELS[capability]
            fake_sha = "sha256:" + ("b" if capability == "speech" else "c") * 64
            headers = {"Authorization": f"Bearer {key}"}
            registration = bridge.post(
                "/bridge/workers/register",
                headers=headers,
                json={
                    "capability": capability,
                    "model_id": model.model_id,
                    "model_revision": fake_sha,
                    "ready": True,
                    "runtime": {"test_fixture": True},
                },
            )
            assert registration.status_code == 200, registration.text
            worker_id = registration.json()["_id"]
            lease_response = bridge.post(
                "/bridge/jobs/claim", headers=headers, json={"worker_id": worker_id}
            )
            lease = lease_response.json()["job"]
            assert lease["capability"] == capability
            attempt_headers = {
                **headers,
                "X-Attempt-Token": lease["attempt_token"],
            }
            input_data = bridge.get(lease["input_url"], headers=attempt_headers).json()
            assert "media_key" not in input_data
            downloaded = bridge.get(input_data["media_url"], headers=attempt_headers)
            assert downloaded.content == payload
            assert core.get(f"/api/inference-tests/{receipt['_id']}").json()["status"] == "leased"

            result_response = bridge.post(
                f"/bridge/jobs/{lease['job_id']}/result",
                headers=attempt_headers,
                json={
                    "worker_id": worker_id,
                    "attempt_id": lease["attempt_id"],
                    "output": {
                        "text": transcript,
                        "model_id": model.model_id,
                        "model_revision": fake_sha,
                    },
                },
            )
            assert result_response.status_code == 200, result_response.text
            completed = core.get(f"/api/inference-tests/{receipt['_id']}").json()
            assert completed["status"] == "succeeded"
            assert completed["transcript"] == transcript
            assert completed["worker_id"] == worker_id
            assert completed["model_id"] == model.model_id
            assert completed["model_revision"] == fake_sha
            assert "source" not in completed and "lease" not in completed

        persisted = store.find("inference_tests")
        assert {item["source_type"] for item in persisted} == {"audio", "handwriting"}
        assert len(store.find("tickets")) == 0
        assert len(store.find("submissions")) == 0


def test_real_mongo_automotive_seed_is_idempotent_and_keeps_activity_statuses(
    audit_store, settings
):
    store, _ = audit_store
    service = Service(store, settings)
    first = service.seed_automotive()
    collection_names = ("organizations", "machines", "submissions", "tickets", "observations")
    before = {name: store.database[name].count_documents({}) for name in collection_names}
    second = service.seed_automotive()

    assert first["_id"] == "machine_a"
    assert first["organization"]["_id"] == "shift_over_motors"
    assert len(first["tickets"]) == 7
    assert [ticket["_id"] for ticket in second["tickets"]] == [
        ticket["_id"] for ticket in first["tickets"]
    ]
    assert {ticket["status"] for ticket in first["tickets"]} == {
        "open",
        "in_progress",
        "under_review",
        "closed",
    }
    assert all(ticket["activities"] for ticket in first["tickets"])
    assert all(
        store.get("tickets", ticket["_id"])["status"] == ticket["status"]
        for ticket in first["tickets"]
    )
    assert {
        name: store.database[name].count_documents({}) for name in collection_names
    } == before
