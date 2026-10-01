"""Application operations: source capture and reviewed, replay-safe actions."""

import hashlib
import json
from copy import deepcopy

from bson import BSON

from .errors import Conflict, NimbusError
from .knowledge import Knowledge
from .media import MediaStore
from .schemas import Action, Capture, Confirmation
from .util import fingerprint, identifier, parse_time, utcnow
from .workflow import transition, validate_fields, validate_role


class Service:
    def __init__(self, store, settings, clock=utcnow):
        self.store = store
        self.settings = settings
        self.clock = clock
        self.knowledge = Knowledge(settings.knowledge_dir)
        self.media = MediaStore(
            settings.data_dir / "media", settings.max_upload_bytes, settings.max_image_pixels
        )

    def required(self, collection, record_id):
        record = self.store.get(collection, record_id)
        if record is None:
            raise NimbusError(f"{collection}_not_found", "Requested record not found.", 404)
        return record

    def seed(self):
        if not self.settings.demo_mode:
            raise NimbusError("demo_disabled", "Synthetic seeding requires demo mode.", 403)
        machine = {
            "_id": "machine_a",
            "name": "Machine A",
            "machine_type": "demo_press",
            "aliases": ["Press A"],
            "reported_condition": "unknown",
            "demo_asset": True,
            "legacy": True,
            "primary_product": False,
        }
        if self.store.get("machines", "machine_a") is None:
            self.store.insert("machines", machine)
        return self.store.get("machines", "machine_a")

    def seed_automotive(self):
        """Create the synthetic ShiftOver organization through normal reviewed actions."""
        if not self.settings.demo_mode:
            raise NimbusError("demo_disabled", "Synthetic seeding requires demo mode.", 403)
        from .automotive import seed_automotive

        legacy_machine = self.seed()
        return seed_automotive(self, legacy_machine)

    def capture(self, capture: Capture, text=None, payload=None, content_type=None):
        if capture.observed_at is not None and parse_time(capture.observed_at) > parse_time(
            self.clock()
        ):
            raise NimbusError(
                "observation_in_future",
                "Observed time cannot be later than the service clock.",
            )
        if (
            len(json.dumps(capture.manual_fields, ensure_ascii=False))
            > self.settings.max_text_characters
        ):
            raise NimbusError("form_limit_exceeded", "The structured form is too large.", 413)
        validate_role(capture.action, capture.actor)
        self.required("machines", capture.machine_id)
        if capture.ticket_id:
            ticket = self.required("tickets", capture.ticket_id)
            if ticket["machine_id"] != capture.machine_id:
                raise NimbusError(
                    "machine_ticket_mismatch", "Ticket belongs to a different machine."
                )
        elif capture.action not in {Action.REPORT, Action.OBSERVATION}:
            raise NimbusError("ticket_required", "Select a ticket for this action.")
        if capture.source_type == "text":
            if payload is not None:
                raise NimbusError(
                    "invalid_source_combination", "Typed input cannot also upload a file."
                )
            text = text or json.dumps(capture.manual_fields, ensure_ascii=False)
            if len(text) > self.settings.max_text_characters:
                raise NimbusError("text_limit_exceeded", "Typed input is too long.", 413)
        elif payload is None or text:
            raise NimbusError(
                "invalid_source_combination", "Audio and handwriting require one original file."
            )
        request_hash = fingerprint(
            {
                "capture": capture.model_dump(mode="json"),
                "text": text,
                "file_hash": hashlib.sha256(payload).hexdigest() if payload is not None else None,
            }
        )
        previous = self.store.find(
            "submissions", {"client_operation_id": capture.client_operation_id}, limit=1
        )
        if previous:
            if previous[0]["request_fingerprint"] != request_hash:
                raise Conflict(
                    "idempotency_key_reused", "Capture key was reused with different input."
                )
            if capture.purpose == "clarification":
                self._attach_clarification(previous[0])
            return previous[0]
        source = {
            "type": capture.source_type,
            "original_text": text,
            "original_fields": capture.manual_fields,
        }
        if payload is not None:
            source.update(self.media.save(payload, capture.source_type, content_type or ""))
        submission = {
            "_id": identifier("sub"),
            **capture.model_dump(mode="json"),
            "request_fingerprint": request_hash,
            "source": source,
            "received_at": self.clock(),
            "processing_status": "saved",
            "processing_version": 1,
            "text_revisions": [],
            "selected_text_revision": 0,
            "draft": None,
            "draft_revision": 0,
            "confirmation": None,
            "commit_intent": None,
            "clarification_ids": [],
            "error": None,
        }
        try:
            self.store.insert("submissions", submission)
        except Conflict:
            previous = self.store.find(
                "submissions", {"client_operation_id": capture.client_operation_id}, limit=1
            )
            if previous and previous[0]["request_fingerprint"] == request_hash:
                return previous[0]
            raise
        if capture.purpose == "clarification":
            try:
                self._attach_clarification(submission)
            except NimbusError:
                version = submission["processing_version"]
                submission.update(
                    processing_status="failed",
                    processing_version=version + 1,
                    error={"code": "clarification_parent_unavailable"},
                )
                self.store.replace("submissions", submission, {"processing_version": version})
                raise
        return submission

    def _attach_clarification(self, child):
        if not child["parent_submission_id"]:
            raise NimbusError("clarification_parent_required", "Select the draft being clarified.")
        parent = self.required("submissions", child["parent_submission_id"])
        if parent["purpose"] == "clarification":
            raise NimbusError("nested_clarification", "Answers must attach to the original draft.")
        if child["_id"] in parent["clarification_ids"]:
            return
        if parent["processing_status"] in {"committing", "confirmed", "canceled"}:
            raise Conflict("parent_not_editable", "This draft can no longer accept answers.")
        for key in ("actor", "machine_id", "action"):
            if child[key] != parent[key]:
                raise NimbusError(
                    "clarification_context_mismatch",
                    "Answers must retain the parent's author, machine, and action.",
                )
        version = parent["processing_version"]
        parent["clarification_ids"].append(child["_id"])
        parent.update(processing_version=version + 1, processing_status="saved", draft=None)
        if not self.store.replace("submissions", parent, {"processing_version": version}):
            raise Conflict("parent_not_editable", "The parent changed while attaching this answer.")

    def revise_text(self, submission_id, text, actor):
        submission = self.required("submissions", submission_id)
        if submission["actor"] != actor.model_dump(mode="json"):
            raise NimbusError(
                "reporter_mismatch", "Only the selected reporter can correct this draft.", 403
            )
        if submission["processing_status"] in {"committing", "confirmed", "canceled"}:
            raise Conflict(
                "submission_not_editable", "A committed or reserved source cannot be rewritten."
            )
        if not text.strip() or len(text) > self.settings.max_text_characters:
            raise NimbusError("invalid_text", "Provide bounded nonempty text.")
        version = submission["processing_version"]
        revision = len(submission["text_revisions"]) + 1
        submission["text_revisions"].append(
            {
                "revision": revision,
                "origin": "human_correction",
                "text": text,
                "created_at": self.clock(),
            }
        )
        submission.update(
            selected_text_revision=revision,
            processing_version=version + 1,
            processing_status="saved",
            draft=None,
        )
        if not self.store.replace("submissions", submission, {"processing_version": version}):
            raise Conflict("submission_revision_conflict")
        return submission

    def use_manual_form(self, submission_id, actor):
        submission = self.required("submissions", submission_id)
        if submission["actor"] != actor.model_dump(mode="json"):
            raise NimbusError(
                "reporter_mismatch", "Only the selected reporter can choose this form.", 403
            )
        if submission["processing_status"] in {"committing", "confirmed", "canceled"}:
            raise Conflict("submission_not_editable")
        version = submission["processing_version"]
        submission.update(
            use_ai=False, draft=None, processing_status="saved", processing_version=version + 1
        )
        if not self.store.replace("submissions", submission, {"processing_version": version}):
            raise Conflict("submission_revision_conflict")
        return submission

    def confirm(self, submission_id, confirmation: Confirmation):
        if len(confirmation.model_dump_json()) > 100_000:
            raise NimbusError(
                "form_limit_exceeded", "The reviewed form exceeds its size bound.", 413
            )
        submission = self.required("submissions", submission_id)
        if submission["purpose"] == "clarification":
            raise NimbusError(
                "confirm_parent_required",
                "Confirm the parent's reviewed draft, not the answer separately.",
            )
        if submission["actor"] != confirmation.reviewed_by.model_dump(mode="json"):
            raise NimbusError(
                "reporter_mismatch", "Confirmation must retain the selected reporter.", 403
            )
        payload = confirmation.model_dump(mode="json")
        intent_hash = fingerprint(payload)
        if submission["confirmation"]:
            accepted = submission["confirmation"]
            if (
                accepted["operation_id"] != confirmation.operation_id
                or accepted["payload_hash"] != intent_hash
            ):
                raise Conflict(
                    "idempotency_key_reused", "Submission already accepted a different form."
                )
            return accepted
        if submission["commit_intent"]:
            if submission["commit_intent"]["payload_hash"] != intent_hash:
                raise Conflict(
                    "submission_reserved", "Another confirmation has reserved this draft."
                )
            return self._commit(submission)
        if (
            submission["processing_status"] not in {"ready_for_review", "needs_clarification"}
            or submission["processing_version"] != confirmation.expected_processing_version
            or submission["draft_revision"] != confirmation.draft_revision
            or submission["selected_text_revision"] != confirmation.text_revision
        ):
            raise Conflict(
                "submission_revision_conflict", "Review the current source and draft revision."
            )
        validate_fields(Action(submission["action"]), confirmation.fields)
        version = submission["processing_version"]
        submission.update(
            processing_status="committing",
            processing_version=version + 1,
            commit_intent={"payload": payload, "payload_hash": intent_hash},
        )
        if not self.store.replace("submissions", submission, {"processing_version": version}):
            raise Conflict("submission_revision_conflict")
        return self._commit(submission)

    def _commit(self, submission):
        intent = submission["commit_intent"]
        confirmed = Confirmation.model_validate(intent["payload"])
        action = Action(submission["action"])
        if action == Action.OBSERVATION and not submission["ticket_id"]:
            return self._commit_machine_observation(submission, confirmed)
        ticket = (
            self.store.get("tickets", submission["ticket_id"]) if submission["ticket_id"] else None
        )
        if ticket is None and action == Action.REPORT:
            previous = self.store.find(
                "tickets", {"origin_submission_id": submission["_id"]}, limit=1
            )
            ticket = previous[0] if previous else None
        if ticket:
            for activity in ticket["activities"]:
                if activity["submission_id"] == submission["_id"]:
                    if (
                        activity["operation_id"] != confirmed.operation_id
                        or activity["payload_hash"] != intent["payload_hash"]
                    ):
                        raise Conflict("idempotency_key_reused")
                    return self._finalize(submission, ticket, activity)
        try:
            if ticket and ticket["version"] != confirmed.expected_ticket_version:
                raise Conflict("ticket_version_conflict")
            policy = policy_hash = None
            if action in {Action.REVIEW, Action.VERIFY}:
                policy, policy_hash = self.knowledge.policy(confirmed.fields["policy_id"])
                machine = self.required("machines", submission["machine_id"])
                if machine["machine_type"] not in policy.machine_types:
                    raise NimbusError(
                        "policy_machine_mismatch", "That procedure does not apply to this machine."
                    )
                if policy.approval_status == "approved_demo" and not machine.get("demo_asset"):
                    raise NimbusError(
                        "demo_policy_not_allowed", "Demo criteria only apply to demo assets."
                    )
            if action == Action.VERIFY and parse_time(confirmed.fields["observed_at"]) > parse_time(
                self.clock()
            ):
                raise NimbusError(
                    "observation_in_future",
                    "Verification evidence cannot be later than the service clock.",
                )
            result = transition(
                ticket,
                action,
                confirmed.reviewed_by,
                confirmed.fields,
                policy=policy,
                policy_hash=policy_hash,
                demo_mode=self.settings.demo_mode,
            )
            now = self.clock()
            if ticket is None:
                result.update(
                    _id="ticket_" + fingerprint(submission["_id"])[:32],
                    machine_id=submission["machine_id"],
                    origin_submission_id=submission["_id"],
                    created_at=now,
                )
            result["updated_at"] = now
            activity = {
                "event_id": identifier("event"),
                "operation_id": confirmed.operation_id,
                "payload_hash": intent["payload_hash"],
                "submission_id": submission["_id"],
                "action": action.value,
                "actor": submission["actor"],
                "recorded_at": now,
                "payload": confirmed.fields,
                "version_after": result["version"],
                "status_after": result["status"],
                "repair_cycle": result["repair_cycle"],
                "previous_closure": ticket.get("closure")
                if ticket and action == Action.REOPEN
                else None,
            }
            if action == Action.VERIFY and result["closure"]:
                result["closure"].update(
                    closed_at=now,
                    verified_by=submission["actor"],
                    verification_submission_id=submission["_id"],
                )
                activity["closure_after"] = deepcopy(result["closure"])
            if action == Action.ACKNOWLEDGE:
                result["handover_acknowledgments"].append(
                    {
                        "actor": submission["actor"],
                        "shift_id": submission["shift_id"],
                        "content_revision": ticket["content_revision"],
                        "at": now,
                    }
                )
            result["activities"].append(activity)
            if len(BSON.encode(result)) > self.settings.ticket_size_guard_bytes:
                raise NimbusError(
                    "ticket_archival_required", "Ticket history reached the configured size bound."
                )
            if ticket is None:
                try:
                    self.store.insert("tickets", result)
                except Conflict:
                    return self._commit(submission)
            elif not self.store.replace("tickets", result, {"version": ticket["version"]}):
                current = self.required("tickets", ticket["_id"])
                if any(
                    event["submission_id"] == submission["_id"] for event in current["activities"]
                ):
                    return self._commit(submission)
                raise Conflict("ticket_version_conflict")
            return self._finalize(submission, result, activity)
        except NimbusError as error:
            version = submission["processing_version"]
            submission.update(
                processing_status="needs_clarification",
                processing_version=version + 1,
                commit_intent=None,
                error={"code": error.code, "message": error.message},
            )
            self.store.replace("submissions", submission, {"processing_version": version})
            raise

    def _finalize(self, submission, ticket, event):
        response = {
            "submission_id": submission["_id"],
            "ticket_id": ticket["_id"],
            "ticket_version": event["version_after"],
            "status": event["status_after"],
            "action_recorded": event["action"],
            "operation_id": event["operation_id"],
            "payload_hash": event["payload_hash"],
        }
        version = submission["processing_version"]
        submission.update(
            confirmation=response,
            processing_status="confirmed",
            processing_version=version + 1,
            commit_intent=None,
        )
        self.store.replace("submissions", submission, {"processing_version": version})
        return response

    def reconcile(self):
        repaired = 0
        for submission in self.store.find("submissions", {"processing_status": "committing"}):
            try:
                self._commit(submission)
                repaired += 1
            except NimbusError:
                continue
        return repaired

    def _commit_machine_observation(self, submission, confirmed):
        """Machine notes share source review, but do not create fault tickets."""
        intent = submission["commit_intent"]
        note_id = "note_" + fingerprint(submission["_id"])[:32]
        existing = self.store.get("observations", note_id)
        if existing is None:
            note = {
                "_id": note_id,
                "machine_id": submission["machine_id"],
                "submission_id": submission["_id"],
                "actor": submission["actor"],
                "observed_at": submission["observed_at"],
                "received_at": submission["received_at"],
                "fields": confirmed.fields,
                "payload_hash": intent["payload_hash"],
            }
            try:
                self.store.insert("observations", note)
            except Conflict:
                existing = self.required("observations", note_id)
        if existing and existing["payload_hash"] != intent["payload_hash"]:
            raise Conflict("idempotency_key_reused")
        response = {
            "submission_id": submission["_id"],
            "observation_id": note_id,
            "ticket_id": None,
            "ticket_version": None,
            "status": "recorded",
            "action_recorded": Action.OBSERVATION.value,
            "operation_id": confirmed.operation_id,
            "payload_hash": intent["payload_hash"],
        }
        version = submission["processing_version"]
        submission.update(
            confirmation=response,
            processing_status="confirmed",
            processing_version=version + 1,
            commit_intent=None,
        )
        self.store.replace("submissions", submission, {"processing_version": version})
        return response
