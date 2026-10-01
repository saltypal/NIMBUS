"""The Test tab uses production transport contracts; output fixtures are not model evaluations."""

from datetime import timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from nimbus.api import create_app
from nimbus.bridge import create_app as create_bridge
from nimbus.database import MemoryStore
from nimbus.diagnostics import diagnostics
from nimbus.jobs import JobQueue
from nimbus.models import MODELS
from nimbus.service import Service
from nimbus.util import utcnow


@pytest.mark.parametrize(
    "source_type,capability", [("audio", "speech"), ("handwriting", "handwriting")]
)
def test_upload_bridge_receipt_transcript_and_provenance(settings, source_type, capability):
    setattr(settings, f"bridge_{capability}_key", "fixture-key")
    store = MemoryStore()
    if source_type == "handwriting":
        buffer = BytesIO()
        Image.new("RGB", (80, 30), "white").save(buffer, format="PNG")
        payload, filename, content_type = buffer.getvalue(), "note.png", "image/png"
    else:
        # Valid audio container metadata transport fixture; no claim of ASR quality.
        import wave

        buffer = BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(bytes(3200))
        payload, filename, content_type = buffer.getvalue(), "note.wav", "audio/wav"
    with (
        TestClient(create_app(settings, store, background=False)) as core,
        TestClient(create_bridge(settings, store)) as bridge,
    ):
        response = core.post(
            "/api/inference-tests",
            data={"source_type": source_type},
            files={"file": (filename, payload, content_type)},
        )
        assert response.status_code == 201
        receipt = response.json()
        assert receipt["status"] == "queued" and receipt["received_at"]
        assert receipt["transcript"] is None
        assert not store.find("tickets") and not store.find("submissions")
        headers = {"Authorization": "Bearer fixture-key"}
        spec = MODELS[capability]
        registration = bridge.post(
            "/bridge/workers/register",
            headers=headers,
            json={
                "capability": capability,
                "model_id": spec.model_id,
                "model_revision": "fixture-revision",
                "ready": True,
            },
        ).json()
        lease = bridge.post(
            "/bridge/jobs/claim", headers=headers, json={"worker_id": registration["_id"]}
        ).json()["job"]
        headers["X-Attempt-Token"] = lease["attempt_token"]
        data = bridge.get(lease["input_url"], headers=headers).json()
        assert "media_key" not in data
        assert bridge.get(data["media_url"], headers=headers).content == payload
        progress = core.get(f"/api/inference-tests/{receipt['_id']}").json()
        assert progress["status"] == "leased"
        assert progress["worker_id"] == registration["_id"]
        result = bridge.post(
            f"/bridge/jobs/{lease['job_id']}/result",
            headers=headers,
            json={
                "worker_id": registration["_id"],
                "attempt_id": lease["attempt_id"],
                "output": {
                    "text": "Car C-102: door gap needs checking.",
                    "model_id": spec.model_id,
                    "model_revision": "fixture-revision",
                },
            },
        )
        assert result.status_code == 200
        completed = core.get(f"/api/inference-tests/{receipt['_id']}").json()
        assert completed["status"] == "succeeded"
        assert completed["transcript"] == "Car C-102: door gap needs checking."
        assert completed["model_id"] == spec.model_id
        assert "source" not in completed and "lease" not in completed
        info = core.get("/api/diagnostics").json()
        assert info["capabilities"][capability]["ready_workers"] == 1
        assert info["jobs"]["succeeded"] == 1


def test_text_test_bypasses_model_and_invalid_input_is_rejected(settings):
    store = MemoryStore()
    with TestClient(create_app(settings, store, background=False)) as core:
        result = core.post(
            "/api/inference-tests", data={"source_type": "text", "text": "Trim check"}
        )
        assert result.status_code == 201
        assert result.json()["transcript"] == "Trim check"
        assert result.json()["job_id"] is None
        assert not store.find("jobs")
        assert core.post("/api/inference-tests", data={"source_type": "image"}).status_code == 422
        assert core.post("/api/inference-tests", data={"source_type": "audio"}).status_code == 422
        assert core.post("/api/inference-tests", data={"source_type": "text"}).status_code == 422
        assert core.get("/api/inference-tests/missing").status_code == 404


def test_diagnostics_do_not_report_stale_worker_as_online(settings):
    store = MemoryStore()
    queue = JobQueue(store, settings)
    worker = queue.register("speech", {"ready": True})
    worker["last_heartbeat_at"] = utcnow() - timedelta(minutes=10)
    store.replace("workers", worker, {"version": 1})
    report = diagnostics(Service(store, settings))
    assert report["capabilities"]["speech"]["ready_workers"] == 0
    assert report["workers"][0]["online"] is False
    assert report["retrieval"]["vector_index_enabled"] is False
    assert "bridge_speech_key" not in str(report)


def test_ticket_advice_keeps_knowledge_separate_and_rejects_unknown_citation(service, operator):
    from test_service import confirmation, report_capture

    from nimbus.advice import ticket_advice
    from nimbus.processing import Coordinator

    draft = Coordinator(service).process(service.capture(report_capture(operator))["_id"])
    ticket_id = service.confirm(draft["_id"], confirmation(draft, operator))["ticket_id"]
    knowledge = ticket_advice(service, ticket_id)
    assert knowledge["status"] == "knowledge_only" and not knowledge["suggestions"]
    assert knowledge["context_sources"]
    service.settings.inference_enabled = True
    pending = ticket_advice(service, ticket_id)
    queue = JobQueue(service.store, service.settings)
    worker = queue.register("llm", {"ready": True})
    lease = queue.claim(worker["_id"], "llm")
    assert lease["job_id"] == pending["job_id"]
    queue.result(
        lease["job_id"],
        "llm",
        lease["attempt_token"],
        worker["_id"],
        lease["attempt_id"],
        {
            "draft": {
                "suggestions": ["Unsupported suggestion"],
                "citations": [{"source_id": "invented", "chunk_id": "unknown"}],
            },
            "model_id": MODELS["llm"].model_id,
            "model_revision": "fixture",
        },
    )
    failed = ticket_advice(service, ticket_id)
    assert failed["status"] == "failed" and not failed["suggestions"]
    assert service.required("tickets", ticket_id)["status"] == "open"
