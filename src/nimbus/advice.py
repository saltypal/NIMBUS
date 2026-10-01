"""Retrieve cited issue context and optionally request read-only LLM advice."""

from pydantic import ValidationError

from .errors import NimbusError
from .jobs import JobQueue
from .processing import Coordinator
from .retrieval import Retriever
from .schemas import Action, Draft
from .util import fingerprint


def ticket_advice(service, ticket_id):
    ticket = service.required("tickets", ticket_id)
    text = f"{ticket['title']}\n{ticket['symptom']}"
    context = Retriever(service).context(
        {"machine_id": ticket["machine_id"], "ticket_id": ticket_id},
        text,
    )
    references = [*context["knowledge"], *context["verified_history"]]
    response = {
        "enabled": service.settings.inference_enabled,
        "status": "knowledge_only",
        "suggestions": [],
        "citations": [],
        "context_sources": [
            {
                "source_id": item["source_id"],
                "chunk_id": item["_id"],
                "text": item.get("text", item.get("title", "")),
            }
            for item in references
        ],
    }
    if not service.settings.inference_enabled:
        return response
    payload = {
        "action": "record_observation",
        "text": text,
        "request": "Suggest inspection checkpoints from the provided references. "
        "Leave fields empty. A suspected cause is a hypothesis, not an established cause.",
        "form": {"required": [], "optional": []},
        "context": context,
        "draft_schema": Draft.model_json_schema(),
    }
    job = JobQueue(service.store, service.settings).ensure(
        f"advice:{ticket_id}:{fingerprint(payload)}",
        "llm",
        "draft",
        payload,
    )
    response.update(status=job["status"], job_id=job["_id"])
    if job["status"] == "failed":
        response["error"] = "Advice inference failed. Retrieved sources remain available."
    elif job["status"] == "succeeded":
        try:
            draft = Coordinator.validate_model_draft(
                job["result"]["draft"],
                Action.OBSERVATION,
                text,
                context,
            )
            if draft.fields:
                raise NimbusError("unexpected_advice_fields", "Advice cannot modify ticket fields.")
            response.update(
                suggestions=draft.suggestions,
                citations=[citation.model_dump() for citation in draft.citations],
                model_id=job["result"]["model_id"],
                model_revision=job["result"]["model_revision"],
            )
        except (NimbusError, ValidationError, KeyError):
            response.update(status="failed", error="The model advice failed source validation.")
    return response
