import json

from fastapi.testclient import TestClient
from test_service import report_capture

from nimbus.api import create_app
from nimbus.bridge import create_app as create_bridge
from nimbus.database import MemoryStore
from nimbus.jobs import JobQueue


def test_form_api_report_and_ambiguous_inspection(settings, operator, supervisor):
    with TestClient(create_app(settings, MemoryStore(), background=False)) as client:
        assert client.post("/api/demo/seed").status_code == 200
        response = client.post(
            "/api/submissions",
            data={
                "capture": report_capture(operator).model_dump_json(),
                "text": "Vibration after tool change",
            },
        )
        assert response.status_code == 201
        draft = response.json()
        confirmation = {
            "operation_id": "confirm",
            "draft_revision": draft["draft_revision"],
            "text_revision": draft["selected_text_revision"],
            "expected_processing_version": draft["processing_version"],
            "reviewed_by": operator.model_dump(mode="json"),
            "fields": draft["draft"]["fields"],
        }
        accepted = client.post(f"/api/submissions/{draft['_id']}/confirm", json=confirmation)
        assert accepted.status_code == 200
        ticket_id = accepted.json()["ticket_id"]
        capture = {
            **report_capture(supervisor, "inspect").model_dump(mode="json"),
            "action": "record_inspection",
            "ticket_id": ticket_id,
            "manual_fields": {"finding": "Checked"},
        }
        response = client.post(
            "/api/submissions", data={"capture": json.dumps(capture), "text": "Checked"}
        )
        assert response.json()["processing_status"] == "needs_clarification"
        assert client.get(f"/api/tickets/{ticket_id}").json()["status"] == "open"
        assert client.get("/api/handover").json()["active_faults"][0]["next_action"]


def test_multipart_source_types_are_enforced(settings, operator):
    with TestClient(create_app(settings, MemoryStore(), background=False)) as client:
        client.post("/api/demo/seed")
        capture = report_capture(operator).model_copy(update={"source_type": "handwriting"})
        response = client.post(
            "/api/submissions",
            data={"capture": capture.model_dump_json()},
            files={"file": ("note.png", b"not an image", "image/png")},
        )
        assert response.status_code == 415


def test_bridge_denies_empty_and_cross_capability_keys(settings):
    settings.bridge_speech_key = "speech-test-key"
    settings.bridge_llm_key = "llm-test-key"
    store = MemoryStore()
    queue = JobQueue(store, settings)
    job = queue.ensure("speech:fixture", "speech", "normalize", {"source_type": "audio"})
    with TestClient(create_bridge(settings, store)) as client:
        assert client.get("/bridge/health").status_code == 401
        headers = {"Authorization": "Bearer speech-test-key"}
        register = {
            "capability": "speech",
            "model_id": "Systran/faster-whisper-large-v3",
            "model_revision": "fixture",
            "ready": True,
        }
        response = client.post("/bridge/workers/register", headers=headers, json=register)
        worker_id = response.json()["_id"]
        assert (
            client.post(
                "/bridge/workers/register", headers=headers, json={**register, "capability": "llm"}
            ).status_code
            == 403
        )
        lease = client.post(
            "/bridge/jobs/claim", headers=headers, json={"worker_id": worker_id}
        ).json()["job"]
        assert lease["job_id"] == job["_id"]
        attempt_headers = {**headers, "X-Attempt-Token": lease["attempt_token"]}
        assert client.get(lease["input_url"], headers=attempt_headers).status_code == 200
        forbidden = {
            "Authorization": "Bearer llm-test-key",
            "X-Attempt-Token": lease["attempt_token"],
        }
        assert client.get(lease["input_url"], headers=forbidden).status_code == 403
        output = {
            "text": "Vibration",
            "model_id": register["model_id"],
            "model_revision": "fixture",
        }
        result = {"worker_id": worker_id, "attempt_id": lease["attempt_id"], "output": output}
        assert (
            client.post(
                f"/bridge/jobs/{job['_id']}/result", headers=attempt_headers, json=result
            ).status_code
            == 200
        )
        assert client.post(
            f"/bridge/jobs/{job['_id']}/result", headers=attempt_headers, json=result
        ).json()["replayed"]
        assert client.get("/api/tickets", headers=headers).status_code == 404
