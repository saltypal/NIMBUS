"""Durable job ownership, deadlines, and attempt-scoped result replay."""

import secrets
from copy import deepcopy
from datetime import timedelta

from .errors import Conflict, NimbusError
from .util import fingerprint, identifier, utcnow


class JobQueue:
    def __init__(self, store, settings, clock=utcnow):
        self.store = store
        self.settings = settings
        self.clock = clock

    def ensure(self, logical_key, capability, task, payload, submission_id=None):
        job = {
            "_id": "job_" + fingerprint(logical_key)[:32],
            "logical_key": logical_key,
            "capability": capability,
            "task": task,
            "input": payload,
            "submission_id": submission_id,
            "status": "queued",
            "version": 1,
            "attempt_count": 0,
            "lease": None,
            "result": None,
            "errors": [],
            "created_at": self.clock(),
        }
        try:
            return self.store.insert("jobs", job)
        except Conflict as error:
            existing = self.store.get("jobs", job["_id"])
            if (
                existing is None
                or existing["input"] != payload
                or existing["capability"] != capability
                or existing["task"] != task
            ):
                raise Conflict(
                    "logical_job_changed", "A logical job cannot change its input."
                ) from error
            return existing

    def register(self, capability, metadata):
        if capability not in {"speech", "handwriting", "llm"}:
            raise NimbusError("invalid_capability", "Unknown worker capability.")
        worker = {
            "_id": identifier("worker"),
            "capability": capability,
            "ready": bool(metadata.get("ready", False)),
            "runtime": metadata,
            "last_heartbeat_at": self.clock(),
            "version": 1,
        }
        return self.store.insert("workers", worker)

    def worker(self, worker_id, capability):
        worker = self.store.get("workers", worker_id)
        if worker is None or worker["capability"] != capability:
            raise NimbusError(
                "worker_scope_mismatch", "This worker session has a different capability.", 403
            )
        return worker

    def worker_heartbeat(self, worker_id, capability):
        worker = self.worker(worker_id, capability)
        version = worker["version"]
        worker.update(last_heartbeat_at=self.clock(), version=version + 1)
        if not self.store.replace("workers", worker, {"version": version}):
            raise Conflict()
        return worker

    def claim(self, worker_id, capability):
        worker = self.worker(worker_id, capability)
        if not worker["ready"]:
            raise NimbusError(
                "worker_not_ready", "Load and smoke-test the model before claiming work.", 409
            )
        self.reap()
        jobs = self.store.find("jobs", {"status": "queued", "capability": capability})
        for job in sorted(jobs, key=lambda row: row["created_at"]):
            version = job["version"]
            token = secrets.token_urlsafe(32)
            now = self.clock()
            job.update(status="leased", version=version + 1, attempt_count=job["attempt_count"] + 1)
            job["lease"] = {
                "worker_id": worker_id,
                "attempt_id": identifier("attempt"),
                "token_hash": fingerprint(token),
                "started_at": now,
                "expires_at": now + timedelta(seconds=self.settings.job_lease_seconds),
            }
            if self.store.replace("jobs", job, {"version": version, "status": "queued"}):
                return {
                    "job_id": job["_id"],
                    "capability": capability,
                    "task": job["task"],
                    "attempt_id": job["lease"]["attempt_id"],
                    "attempt_token": token,
                    "lease_expires_at": job["lease"]["expires_at"],
                    "heartbeat_interval_seconds": max(
                        0.5, min(15, self.settings.job_lease_seconds / 3)
                    ),
                    "input_url": f"/bridge/jobs/{job['_id']}/input",
                }
        return None

    def _owned(self, job_id, capability, token, worker_id=None, allow_completed=False):
        job = self.store.get("jobs", job_id)
        if job is None:
            raise NimbusError("job_not_found", "Job not found.", 404)
        lease = job.get("lease") or {}
        if job["capability"] != capability or lease.get("token_hash") != fingerprint(token):
            raise NimbusError(
                "job_scope_mismatch", "This credential does not own that attempt.", 403
            )
        if worker_id and lease.get("worker_id") != worker_id:
            raise NimbusError("job_scope_mismatch", "Worker does not own that attempt.", 403)
        if allow_completed and job["status"] == "succeeded":
            return job
        if job["status"] != "leased" or lease["expires_at"] <= self.clock():
            raise Conflict("job_lease_expired", "The attempt is expired or no longer current.")
        deadline = lease["started_at"] + timedelta(seconds=self.settings.job_max_runtime_seconds)
        if self.clock() >= deadline:
            raise Conflict("job_deadline_exceeded", "This attempt exceeded its maximum runtime.")
        return job

    def input(self, job_id, capability, token):
        return deepcopy(self._owned(job_id, capability, token)["input"])

    def heartbeat(self, job_id, capability, token, worker_id):
        job = self._owned(job_id, capability, token, worker_id)
        version = job["version"]
        deadline = job["lease"]["started_at"] + timedelta(
            seconds=self.settings.job_max_runtime_seconds
        )
        job["lease"]["expires_at"] = min(
            self.clock() + timedelta(seconds=self.settings.job_lease_seconds), deadline
        )
        job["version"] += 1
        if not self.store.replace("jobs", job, {"version": version, "status": "leased"}):
            raise Conflict()
        return {"lease_expires_at": job["lease"]["expires_at"]}

    def result(
        self, job_id, capability, token, worker_id, attempt_id, output, *, _remaining_retries=3
    ):
        job = self._owned(job_id, capability, token, worker_id, allow_completed=True)
        if job["lease"]["attempt_id"] != attempt_id:
            raise Conflict("job_attempt_changed", "The result belongs to another attempt.")
        result_hash = fingerprint(output)
        if job["status"] == "succeeded":
            if job["result_hash"] != result_hash:
                raise Conflict(
                    "idempotency_key_reused", "The accepted attempt result cannot change."
                )
            return {"job_id": job_id, "status": "succeeded", "replayed": True}
        version = job["version"]
        job.update(
            status="succeeded",
            version=version + 1,
            result=output,
            result_hash=result_hash,
            completed_at=self.clock(),
        )
        if not self.store.replace("jobs", job, {"version": version, "status": "leased"}):
            current = self.store.get("jobs", job_id)
            if (
                current
                and (current.get("lease") or {}).get("attempt_id") == attempt_id
                and (current.get("lease") or {}).get("token_hash") == fingerprint(token)
                and current.get("status") == "succeeded"
                and current.get("result_hash") == result_hash
            ):
                return {"job_id": job_id, "status": "succeeded", "replayed": True}
            if (
                current
                and current["status"] == "leased"
                and _remaining_retries > 0
                and (current.get("lease") or {}).get("attempt_id") == attempt_id
            ):
                # A heartbeat may legitimately increment the job version while
                # inference finishes. Recheck ownership before retrying the CAS.
                return self.result(
                    job_id,
                    capability,
                    token,
                    worker_id,
                    attempt_id,
                    output,
                    _remaining_retries=_remaining_retries - 1,
                )
            raise Conflict()
        return {"job_id": job_id, "status": "succeeded", "replayed": False}

    def fail(self, job_id, capability, token, worker_id, code, retryable=True):
        job = self._owned(job_id, capability, token, worker_id)
        version = job["version"]
        retry = retryable and job["attempt_count"] < self.settings.job_max_attempts
        job.update(status="queued" if retry else "failed", version=version + 1)
        job["errors"].append(
            {"attempt_id": job["lease"]["attempt_id"], "code": str(code)[:160], "at": self.clock()}
        )
        job["lease"] = None
        if not self.store.replace("jobs", job, {"version": version}):
            raise Conflict()
        return {"job_id": job_id, "status": job["status"]}

    def reap(self):
        count = 0
        for job in self.store.find("jobs", {"status": "leased"}):
            lease = job["lease"]
            deadline = lease["started_at"] + timedelta(
                seconds=self.settings.job_max_runtime_seconds
            )
            if lease["expires_at"] > self.clock() and deadline > self.clock():
                continue
            version = job["version"]
            job["errors"].append(
                {"code": "lease_expired", "attempt_id": lease["attempt_id"], "at": self.clock()}
            )
            job.update(
                status="queued"
                if job["attempt_count"] < self.settings.job_max_attempts
                else "failed",
                version=version + 1,
                lease=None,
            )
            if self.store.replace("jobs", job, {"version": version, "status": "leased"}):
                count += 1
        return count
