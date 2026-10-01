import pytest
from fastapi.testclient import TestClient

from nimbus.bridge import create_app
from nimbus.database import MemoryStore
from nimbus.errors import NimbusError
from nimbus.jobs import JobQueue
from nimbus.worker import Worker


class FixtureAdapter:
    """Transport fixture; never presented as real speech/model evaluation."""

    model_id = "Systran/faster-whisper-large-v3"
    model_revision = "fixture-not-a-model-revision"

    def smoke(self):
        return {"ok": True, "fixture": True}

    def run(self, payload, media_path=None):
        return {
            "text": "Transport fixture only",
            "model_id": self.model_id,
            "model_revision": self.model_revision,
        }


def test_worker_runs_outbound_transport_and_saves_receipt(settings, tmp_path):
    settings.bridge_speech_key = "fixture-key"
    store = MemoryStore()
    queue = JobQueue(store, settings)
    job = queue.ensure("fixture", "speech", "normalize", {"source_type": "audio"})
    with TestClient(create_app(settings, store), base_url="http://localhost") as client:
        worker = Worker(
            "speech",
            FixtureAdapter(),
            "http://localhost",
            "fixture-key",
            tmp_path / "receipts",
            client,
        )
        worker.register({"fixture": True})
        assert worker.step()
        assert queue.store.get("jobs", job["_id"])["status"] == "succeeded"
        assert (tmp_path / "receipts/receipts.jsonl").exists()
        assert not worker.step()


def test_worker_refuses_credential_redirect_and_remote_http(tmp_path):
    with pytest.raises(NimbusError):
        Worker("speech", FixtureAdapter(), "http://example.test", "key", tmp_path)
    worker = Worker("speech", FixtureAdapter(), "https://bridge.example.test", "key", tmp_path)
    try:
        with pytest.raises(NimbusError):
            worker.url("https://different.example.test/job")
    finally:
        worker.client.close()
