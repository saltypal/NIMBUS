"""One coordinator step at a time: originals -> text -> reviewed field draft.

No GPU dependency is imported here. Remote results enter through durable jobs.
Call process(submission_id) or run_once() without running the HTTP application.
"""

from pydantic import ValidationError

from .errors import Conflict, NimbusError
from .jobs import JobQueue
from .retrieval import Retriever
from .schemas import Action, Draft
from .util import fingerprint, utcnow
from .workflow import FORM_FIELDS, missing_fields


class Coordinator:
    def __init__(self, service):
        self.service = service
        self.queue = JobQueue(service.store, service.settings)
        self.retriever = Retriever(service)

    def _save(self, submission, version):
        submission["processing_version"] = version + 1
        if not self.service.store.replace(
            "submissions", submission, {"processing_version": version}
        ):
            raise Conflict("submission_revision_conflict")
        return submission

    def process(self, submission_id):
        submission = self.service.required("submissions", submission_id)
        if submission["processing_status"] in {
            "confirmed",
            "committing",
            "canceled",
            "failed",
            "attached",
        }:
            return submission
        version = submission["processing_version"]
        if not submission["selected_text_revision"]:
            if submission["source_type"] == "text":
                text = submission["source"]["original_text"]
                origin = "typed"
                model_metadata = None
            else:
                job = self.queue.ensure(
                    f"normalize:{submission_id}",
                    "speech" if submission["source_type"] == "audio" else "handwriting",
                    "normalize",
                    {
                        "media_key": submission["source"]["media_key"],
                        "content_type": submission["source"]["content_type"],
                        "source_type": submission["source_type"],
                    },
                    submission_id,
                )
                if job["status"] == "failed":
                    submission.update(
                        processing_status="needs_transcription",
                        error={"code": "normalization_failed"},
                    )
                    return self._save(submission, version)
                if job["status"] != "succeeded":
                    if submission["processing_status"] != "awaiting_normalization":
                        submission.update(
                            processing_status="awaiting_normalization",
                            normalization_job_id=job["_id"],
                        )
                        return self._save(submission, version)
                    return submission
                text = job["result"].get("text")
                if (
                    not isinstance(text, str)
                    or not text.strip()
                    or len(text) > self.service.settings.max_text_characters
                ):
                    submission.update(
                        processing_status="needs_transcription",
                        error={"code": "invalid_normalized_text"},
                    )
                    return self._save(submission, version)
                origin = "speech_model" if submission["source_type"] == "audio" else "vision_model"
                model_metadata = {
                    key: job["result"].get(key) for key in ("model_id", "model_revision")
                }
            submission["text_revisions"].append(
                {
                    "revision": 1,
                    "text": text,
                    "origin": origin,
                    "model": model_metadata,
                    "created_at": utcnow(),
                }
            )
            submission.update(selected_text_revision=1, processing_status="saved", error=None)
            self._save(submission, version)
            version = submission["processing_version"]
        if submission["purpose"] == "clarification":
            # The answer never becomes another ticket. Wake the original draft
            # only after its text is available, invalidating an older LLM job.
            parent = self.service.required("submissions", submission["parent_submission_id"])
            if parent["processing_status"] in {"committing", "confirmed", "canceled"}:
                submission.update(processing_status="failed", error={"code": "parent_not_editable"})
            else:
                if submission["_id"] not in parent["clarification_ids"]:
                    self.service._attach_clarification(submission)
                    parent = self.service.required("submissions", parent["_id"])
                parent_version = parent["processing_version"]
                parent.update(processing_status="saved", draft=None)
                self._save(parent, parent_version)
                submission.update(processing_status="attached")
            return self._save(submission, version)
        text = submission["text_revisions"][submission["selected_text_revision"] - 1]["text"]
        clarification_texts = []
        for child_id in submission["clarification_ids"]:
            child = self.service.required("submissions", child_id)
            if not child["selected_text_revision"]:
                submission.update(processing_status="awaiting_clarification")
                return self._save(submission, version)
            clarification_texts.append(
                child["text_revisions"][child["selected_text_revision"] - 1]["text"]
            )
        combined = "\n".join([text, *clarification_texts])
        context = self.retriever.context(submission, combined)
        input_hash = fingerprint(
            {
                "text": combined,
                "text_revision": submission["selected_text_revision"],
                "manual_fields": submission["manual_fields"],
                "context": context,
                "use_ai": submission["use_ai"],
            }
        )
        if submission.get("draft_input_hash") == input_hash and submission.get("draft"):
            return submission
        action = Action(submission["action"])
        draft = Draft(
            fields=submission["manual_fields"], summary="Manual form; AI inference is disabled."
        )
        model_error = None
        if self.service.settings.inference_enabled and submission["use_ai"] is not False:
            job = self.queue.ensure(
                f"draft:{submission_id}:{input_hash}",
                "llm",
                "draft",
                {
                    "action": action.value,
                    "text": combined,
                    "manual_fields": submission["manual_fields"],
                    "form": {
                        "required": FORM_FIELDS[action][0],
                        "optional": FORM_FIELDS[action][1],
                    },
                    "context": context,
                    "draft_schema": Draft.model_json_schema(),
                },
                submission_id,
            )
            if job["status"] in {"queued", "leased"}:
                if (
                    submission.get("draft_job_id") == job["_id"]
                    and submission["processing_status"] == "awaiting_draft"
                ):
                    return submission
                submission.update(processing_status="awaiting_draft", draft_job_id=job["_id"])
                return self._save(submission, version)
            if job["status"] == "succeeded":
                try:
                    draft = self.validate_model_draft(
                        job["result"].get("draft"), action, combined, context
                    )
                    # Explicit manually entered facts take precedence over extraction.
                    draft.fields.update(submission["manual_fields"])
                except (NimbusError, ValidationError) as error:
                    model_error = {"code": "invalid_model_draft", "message": str(error)[:500]}
            else:
                model_error = {"code": "draft_inference_failed"}
            if model_error:
                draft.summary = "Inference failed validation. Complete and review the manual form."
        draft.missing_fields = missing_fields(action, draft.fields)
        draft.questions = [
            f"Please provide {field.replace('_', ' ')}." for field in draft.missing_fields
        ]
        submission.update(
            draft=draft.model_dump(),
            draft_revision=submission["draft_revision"] + 1,
            draft_input_hash=input_hash,
            draft_context=context,
            processing_status="needs_clarification" if draft.missing_fields else "ready_for_review",
            error=model_error,
        )
        return self._save(submission, version)

    @staticmethod
    def validate_model_draft(output, action, text, context):
        draft = Draft.model_validate(output)
        names = set(sum(FORM_FIELDS[action], []))
        if set(draft.fields) - names:
            raise NimbusError(
                "invalid_model_fields", "Model returned fields outside the action's form."
            )
        citations = {(chunk["source_id"], chunk["_id"]) for chunk in context["knowledge"]}
        citations.update(
            (hit["source_id"], hit["_id"]) for hit in context.get("verified_history", [])
        )
        if any(
            (citation.source_id, citation.chunk_id) not in citations for citation in draft.citations
        ):
            raise NimbusError(
                "invalid_model_citation", "Model cited a source outside the retrieved context."
            )
        if draft.suggestions and not draft.citations:
            raise NimbusError("uncited_suggestion", "Suggestions need a retrieved source citation.")
        # Filled observational fields need excerpts, rather than model confidence.
        for name in draft.fields:
            if name in {"policy_id", "policy_version", "repair_cycle"}:
                continue
            excerpt = draft.field_evidence.get(name, "")
            if not excerpt or excerpt not in text:
                raise NimbusError(
                    "unsupported_model_field", f"{name} needs an excerpt from the current input."
                )
        return draft

    def run_once(self):
        self.queue.reap()
        self.service.reconcile()
        changed = 0
        for state in (
            "saved",
            "awaiting_normalization",
            "awaiting_clarification",
            "awaiting_draft",
        ):
            for submission in self.service.store.find("submissions", {"processing_status": state}):
                try:
                    result = self.process(submission["_id"])
                    changed += result["processing_version"] != submission["processing_version"]
                except Conflict:
                    continue  # Another coordinator won the conditional update.
                except NimbusError as error:
                    current = self.service.required("submissions", submission["_id"])
                    if current["processing_status"] not in {"confirmed", "committing", "canceled"}:
                        version = current["processing_version"]
                        current.update(
                            processing_status="needs_attention",
                            error={"code": error.code, "message": error.message},
                        )
                        try:
                            self._save(current, version)
                        except Conflict:
                            pass
        return changed
