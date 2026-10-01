"""RAG context assembly. Exact state and policies are separate from similarity search."""

import re

from .knowledge import OpenEncoder


class Retriever:
    def __init__(self, service):
        self.service = service
        self.encoder = None

    def context(self, submission, text):
        service = self.service
        machine = service.required("machines", submission["machine_id"])
        ticket = (
            service.store.get("tickets", submission["ticket_id"])
            if submission["ticket_id"]
            else None
        )
        if ticket:
            # The UI fetches complete history separately. The model gets a
            # bounded exact snapshot instead of every embedded activity.
            names = (
                "_id",
                "machine_id",
                "version",
                "content_revision",
                "repair_cycle",
                "cycle_requires_new_work",
                "status",
                "reported_condition",
                "next_action",
                "verification_plan",
                "unresolved_contradiction",
                "title",
                "symptom",
            )
            ticket = {name: ticket[name] for name in names}
            original = service.store.get("tickets", submission["ticket_id"])
            for name in ("vehicle_id", "part_name", "production_stage"):
                if original.get(name):
                    ticket[name] = original[name]
            ticket["recent_activity"] = [
                {
                    "action": event["action"],
                    "recorded_at": event["recorded_at"],
                    "payload": event["payload"],
                }
                for event in original.get("activities", [])
                if event["action"] != "acknowledge_handover"
            ][-4:]
        if service.settings.retrieval_backend == "embedding" and self.encoder is None:
            self.encoder = OpenEncoder(revision=service.settings.embedding_revision)
        if service.settings.retrieval_backend not in {"lexical", "embedding"}:
            raise ValueError("retrieval_backend must be lexical or embedding")
        chunks = service.knowledge.search(text, machine["machine_type"], encoder=self.encoder)
        policies = []
        for _, metadata, _ in service.knowledge.sources():
            if (
                metadata.get("document_type") == "verification_policy"
                and metadata.get("approval_status") in {"approved", "approved_demo"}
                and machine["machine_type"] in metadata.get("machine_types", [])
            ):
                policy, content_hash = service.knowledge.policy(metadata["source_id"])
                policies.append({**policy.model_dump(), "content_hash": content_hash})
        # History is evidence, never an approved rule. Only verified closed fixes
        # are offered as fix examples, and every hit retains its ticket ID.
        terms = set(re.findall(r"\w+", text.casefold()))
        history = []
        for previous in service.store.find(
            "tickets", {"machine_id": machine["_id"], "status": "closed"}
        ):
            if previous["_id"] == submission["ticket_id"] or not previous.get("closure"):
                continue
            words = set(
                re.findall(r"\w+", (previous["title"] + " " + previous["symptom"]).casefold())
            )
            score = len(terms & words) / max(1, len(terms))
            if score:
                history.append(
                    {
                        "source_id": f"ticket:{previous['_id']}",
                        "_id": f"closure:{previous['repair_cycle']}",
                        "ticket_id": previous["_id"],
                        "title": previous["title"],
                        "symptom": previous["symptom"],
                        "closure": previous["closure"],
                        "work": [
                            event["payload"]
                            for event in previous["activities"]
                            if event["action"] in {"record_work", "submit_for_review"}
                        ][-3:],
                        "score": score,
                    }
                )
        # Store the cited knowledge snapshot for inspection, without making it
        # the source of truth for policy authorization.
        for chunk in chunks:
            if service.store.get("knowledge_chunks", chunk["_id"]):
                service.store.replace("knowledge_chunks", chunk, {})
            else:
                from .errors import Conflict

                try:
                    service.store.insert("knowledge_chunks", chunk)
                except Conflict:
                    pass
        return {
            "retrieval_backend": service.settings.retrieval_backend,
            "embedding_model": {
                "model_id": self.encoder.model_id,
                "model_revision": self.encoder.model_revision,
            }
            if self.encoder
            else None,
            "machine": machine,
            "ticket": ticket,
            "policies": policies,
            "knowledge": chunks,
            "verified_history": sorted(history, key=lambda row: row["score"], reverse=True)[:3],
        }
