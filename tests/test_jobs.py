from datetime import timedelta

import pytest

from nimbus.database import MemoryStore
from nimbus.errors import NimbusError
from nimbus.jobs import JobQueue
from nimbus.util import utcnow


def setup_queue(settings):
    now = [utcnow()]
    queue = JobQueue(MemoryStore(), settings, clock=lambda: now[0])
    job = queue.ensure("text:first", "speech", "transcribe", {"media_key": "fixture"})
    worker = queue.register("speech", {"ready": True})
    return queue, job, worker, now


def test_claim_exclusive_and_scope_restricted(settings):
    queue, job, worker, _ = setup_queue(settings)
    lease = queue.claim(worker["_id"], "speech")
    assert queue.claim(worker["_id"], "speech") is None
    with pytest.raises(NimbusError) as captured:
        queue.input(job["_id"], "handwriting", lease["attempt_token"])
    assert captured.value.status == 403


def test_result_replay_cannot_change_output(settings):
    queue, job, worker, _ = setup_queue(settings)
    lease = queue.claim(worker["_id"], "speech")
    arguments = (job["_id"], "speech", lease["attempt_token"], worker["_id"], lease["attempt_id"])
    assert not queue.result(*arguments, {"text": "Vibration"})["replayed"]
    assert queue.result(*arguments, {"text": "Vibration"})["replayed"]
    with pytest.raises(NimbusError):
        queue.result(*arguments, {"text": "Resolved"})


def test_expired_attempt_cannot_commit_after_reassignment(settings):
    queue, job, worker, now = setup_queue(settings)
    first = queue.claim(worker["_id"], "speech")
    now[0] += timedelta(seconds=settings.job_lease_seconds + 1)
    second = queue.claim(worker["_id"], "speech")
    assert second["attempt_id"] != first["attempt_id"]
    with pytest.raises(NimbusError):
        queue.result(
            job["_id"],
            "speech",
            first["attempt_token"],
            worker["_id"],
            first["attempt_id"],
            {"text": "Late"},
        )


def test_heartbeat_cannot_extend_absolute_deadline(settings):
    queue, job, worker, now = setup_queue(settings)
    lease = queue.claim(worker["_id"], "speech")
    started = now[0]
    for _ in range(settings.job_max_runtime_seconds // 30):
        now[0] += timedelta(seconds=30)
        if now[0] >= started + timedelta(seconds=settings.job_max_runtime_seconds):
            break
        queue.heartbeat(job["_id"], "speech", lease["attempt_token"], worker["_id"])
    with pytest.raises(NimbusError):
        queue.heartbeat(job["_id"], "speech", lease["attempt_token"], worker["_id"])


def test_not_ready_worker_cannot_claim(settings):
    queue, _, _, _ = setup_queue(settings)
    cold = queue.register("speech", {"ready": False})
    with pytest.raises(NimbusError) as captured:
        queue.claim(cold["_id"], "speech")
    assert captured.value.code == "worker_not_ready"


def test_result_retries_a_concurrent_heartbeat_version_change(settings):
    class HeartbeatRaceStore(MemoryStore):
        injected = False

        def replace(self, collection, document, expected):
            if collection == "jobs" and document["status"] == "succeeded" and not self.injected:
                self.injected = True
                current = self.get(collection, document["_id"])
                current["version"] += 1
                super().replace(collection, current, expected)
                return False
            return super().replace(collection, document, expected)

    queue = JobQueue(HeartbeatRaceStore(), settings)
    job = queue.ensure("race", "speech", "normalize", {"source_type": "audio"})
    worker = queue.register("speech", {"ready": True})
    claim = queue.claim(worker["_id"], "speech")
    result = queue.result(
        job["_id"],
        "speech",
        claim["attempt_token"],
        worker["_id"],
        claim["attempt_id"],
        {"text": "Fixture output"},
    )
    assert result["status"] == "succeeded"
