"""Outbound-only consumer. It needs a capability key, never MongoDB credentials."""

import json
import os
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urljoin, urlparse

import httpx

from .errors import NimbusError
from .util import json_default, utcnow


class Worker:
    def __init__(self, capability, adapter, bridge_url, key, results_dir, client=None):
        parsed = urlparse(bridge_url)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            raise NimbusError(
                "invalid_bridge_url", "Use an HTTPS bridge URL without embedded credentials."
            )
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise NimbusError("insecure_bridge_url", "Remote bridges require HTTPS.")
        if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise NimbusError(
                "invalid_bridge_url", "Use the bridge origin without path, query, or fragment."
            )
        if not key:
            raise NimbusError("worker_key_required", "Configure this capability's worker key.")
        self.capability = capability
        self.adapter = adapter
        self.base = bridge_url.rstrip("/")
        self.key = key
        self.results_dir = Path(results_dir)
        self.client = client or httpx.Client(timeout=30, follow_redirects=False)
        self.worker_id = None

    def url(self, path):
        # Even a job response cannot redirect a credential to a different host.
        candidate = urljoin(self.base + "/", path)
        if (
            urlparse(candidate).netloc != urlparse(self.base).netloc
            or urlparse(candidate).scheme != urlparse(self.base).scheme
        ):
            raise NimbusError("foreign_job_url", "Bridge job URLs must retain the bridge origin.")
        return candidate

    def request(self, method, path, *, token=None, payload=None):
        headers = {"Authorization": f"Bearer {self.key}"}
        if token:
            headers["X-Attempt-Token"] = token
        response = self.client.request(method, self.url(path), headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

    def register(self, runtime=None):
        smoke = self.adapter.smoke()
        worker = self.request(
            "POST",
            "/bridge/workers/register",
            payload={
                "capability": self.capability,
                "model_id": self.adapter.model_id,
                "model_revision": self.adapter.model_revision,
                "ready": True,
                "runtime": {"smoke": smoke, **(runtime or {})},
            },
        )
        self.worker_id = worker["_id"]
        return worker

    def _download(self, path, token, target):
        headers = {"Authorization": f"Bearer {self.key}", "X-Attempt-Token": token}
        size = 0
        with (
            self.client.stream("GET", self.url(path), headers=headers) as response,
            target.open("xb") as stream,
        ):
            response.raise_for_status()
            for block in response.iter_bytes():
                size += len(block)
                if size > 20 * 1024 * 1024:
                    raise NimbusError("remote_media_limit", "Downloaded source exceeds 20 MiB.")
                stream.write(block)

    def step(self):
        if self.worker_id is None:
            raise NimbusError(
                "worker_not_registered", "Load, smoke-test, and register before claiming."
            )
        self.request("POST", f"/bridge/workers/{self.worker_id}/heartbeat")
        claim = self.request("POST", "/bridge/jobs/claim", payload={"worker_id": self.worker_id})[
            "job"
        ]
        if claim is None:
            return False
        job_id, token = claim["job_id"], claim["attempt_token"]
        stopped = threading.Event()
        lease_lost = threading.Event()
        heartbeat_interval = claim.get("heartbeat_interval_seconds", 15)

        def heartbeat():
            while not stopped.wait(heartbeat_interval):
                try:
                    self.request(
                        "POST",
                        f"/bridge/jobs/{job_id}/heartbeat",
                        token=token,
                        payload={"worker_id": self.worker_id},
                    )
                except httpx.HTTPError:
                    lease_lost.set()
                    return

        thread = threading.Thread(target=heartbeat, daemon=True, name="lease-heartbeat")
        thread.start()
        try:
            payload = self.request("GET", claim["input_url"], token=token)
            with TemporaryDirectory(prefix="nimbus-job-") as temporary:
                media = None
                if payload.get("media_url"):
                    media = Path(temporary) / "source"
                    self._download(payload["media_url"], token, media)
                output = self.adapter.run(payload, media)
            if lease_lost.is_set():
                raise NimbusError(
                    "job_lease_lost", "Discarded inference output after losing attempt ownership."
                )
            receipt = None
            # Lost network response is retried with identical attempt and output.
            for retry in range(3):
                try:
                    receipt = self.request(
                        "POST",
                        f"/bridge/jobs/{job_id}/result",
                        token=token,
                        payload={
                            "worker_id": self.worker_id,
                            "attempt_id": claim["attempt_id"],
                            "output": output,
                        },
                    )
                    break
                except httpx.TransportError:
                    if retry == 2:
                        raise
                    time.sleep(1)
            self.results_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "job_id": job_id,
                "attempt_id": claim["attempt_id"],
                "receipt": receipt,
                "completed_at": utcnow(),
                "model_id": self.adapter.model_id,
                "model_revision": self.adapter.model_revision,
            }
            with (self.results_dir / "receipts.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, default=json_default) + "\n")
            return True
        except Exception as error:
            if not lease_lost.is_set():
                try:
                    self.request(
                        "POST",
                        f"/bridge/jobs/{job_id}/fail",
                        token=token,
                        payload={
                            "worker_id": self.worker_id,
                            "code": getattr(error, "code", type(error).__name__),
                            "retryable": not isinstance(error, NimbusError),
                        },
                    )
                except httpx.HTTPError:
                    pass
            raise
        finally:
            stopped.set()
            thread.join(timeout=2)

    def run(self, once=False, poll_seconds=2):
        while True:
            try:
                processed = self.step()
                print(
                    json.dumps(
                        {
                            "event": "job_completed" if processed else "idle",
                            "capability": self.capability,
                        }
                    ),
                    flush=True,
                )
            except httpx.HTTPError as error:
                # Do not print response bodies or headers containing credentials.
                print(
                    json.dumps({"event": "bridge_error", "type": type(error).__name__}), flush=True
                )
                if once:
                    raise
            except NimbusError as error:
                print(json.dumps({"event": "job_failed", "code": error.code}), flush=True)
                if once:
                    raise
            if once:
                return
            time.sleep(poll_seconds)


def capability_key(capability):
    return os.getenv(f"NIMBUS_BRIDGE_{capability.upper()}_KEY", "")
