"""Exercise real normalization jobs without creating operational tickets.

The browser uploads here; existing outbound workers claim the resulting job.
Polling reads the accepted job result, including its worker/model provenance.
This module needs neither a GPU nor a new worker protocol.
"""

from .errors import NimbusError
from .jobs import JobQueue
from .schemas import Draft
from .util import identifier, utcnow


class InferenceTests:
    def __init__(self, service):
        self.service = service
        self.queue = JobQueue(service.store, service.settings)

    def create(self, source_type, text=None, payload=None, content_type=None, capability=None):
        if source_type not in {"text", "audio", "handwriting"}:
            raise NimbusError("invalid_source", "Choose text, audio, or handwriting.")
        expected_capability = {"audio": "speech", "handwriting": "handwriting"}.get(source_type)
        if (
            capability is not None
            and capability != expected_capability
            and not (source_type == "text" and capability == "llm")
        ):
            raise NimbusError("invalid_test_capability", "Capability must match the input type.")
        test_id = identifier("test")
        record = {
            "_id": test_id,
            "source_type": source_type,
            "capability": None
            if source_type == "text"
            else ("speech" if source_type == "audio" else "handwriting"),
            "received_at": utcnow(),
            "job_id": None,
            "source": None,
            "transcript": None,
            "status": "queued",
            "output_kind": "draft" if capability == "llm" else "transcript",
        }
        if source_type == "text":
            if payload is not None or not isinstance(text, str) or not text.strip():
                raise NimbusError("invalid_test_input", "Provide nonempty text without a file.")
            if len(text) > self.service.settings.max_text_characters:
                raise NimbusError("text_limit_exceeded", "Typed input is too long.", 413)
            record.update(source={"original_text": text}, transcript=text, status="succeeded")
            if capability == "llm":
                knowledge = self.service.knowledge.search(text, "general")
                input_data = {
                    "action": "record_observation",
                    "text": text,
                    "request": "Summarize this observation and suggest cited checkpoints. "
                    "Leave fields empty; this is an inference connectivity test.",
                    "form": {"required": [], "optional": []},
                    "context": {"knowledge": knowledge, "verified_history": [], "policies": []},
                    "draft_schema": Draft.model_json_schema(),
                }
                job = self.queue.ensure(f"inference-test:{test_id}", "llm", "draft", input_data)
                record.update(capability="llm", transcript=None, status="queued", job_id=job["_id"])
        else:
            if payload is None or text:
                raise NimbusError("invalid_test_input", "Provide one original audio or image file.")
            record["source"] = self.service.media.save(payload, source_type, content_type or "")
            record["job_id"] = self.queue.ensure(
                f"inference-test:{test_id}",
                record["capability"],
                "normalize",
                {**record["source"], "source_type": source_type},
            )["_id"]
        self.service.store.insert("inference_tests", record)
        return self.read(test_id)

    def read(self, test_id):
        record = self.service.required("inference_tests", test_id)
        result = {name: value for name, value in record.items() if name != "source"}
        result.update(error=None, worker_id=None, model_id=None, model_revision=None)
        if record["job_id"] is None:
            return result
        job = self.service.required("jobs", record["job_id"])
        result["status"] = job["status"]
        lease = job.get("lease") or {}
        result["worker_id"] = lease.get("worker_id")
        result["attempt_count"] = job["attempt_count"]
        if job.get("errors"):
            result["last_attempt_error"] = job["errors"][-1]["code"]
        if job["status"] == "failed":
            result["error"] = result.get("last_attempt_error", "normalization_failed")
        if job["status"] == "succeeded":
            output = job["result"]
            transcript = output.get("text")
            if record["capability"] == "llm":
                from pydantic import ValidationError

                from .processing import Coordinator
                from .schemas import Action

                try:
                    draft = Coordinator.validate_model_draft(
                        output["draft"],
                        Action.OBSERVATION,
                        job["input"]["text"],
                        job["input"]["context"],
                    )
                    if draft.fields:
                        raise NimbusError(
                            "unexpected_test_fields", "This test cannot modify fields."
                        )
                except (NimbusError, ValidationError, KeyError):
                    result.update(status="failed", error="Model draft failed source validation.")
                    return result
                result["draft"] = draft.model_dump()
                transcript = draft.summary
            result.update(
                transcript=transcript,
                model_id=output["model_id"],
                model_revision=output["model_revision"],
                completed_at=job["completed_at"],
            )
        return result
