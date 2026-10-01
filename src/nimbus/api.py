"""Local application API and optional built UI. Run this independently of bridge."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .advice import ticket_advice
from .config import ROOT, Settings
from .database import create_store
from .diagnostics import diagnostics
from .errors import NimbusError
from .http_support import install_handlers
from .inference_tests import InferenceTests
from .models import list_models
from .processing import Coordinator
from .schemas import Actor, Capture, Confirmation, Role, Status, StrictModel
from .service import Service
from .workflow import FORM_FIELDS, allowed_roles

logger = logging.getLogger(__name__)


class TextCorrection(StrictModel):
    text: str
    actor: Actor


def create_app(settings=None, store=None, background=True):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(application):
        application.state.service = Service(store or create_store(settings), settings)
        application.state.coordinator = Coordinator(application.state.service)
        application.state.processing_error = None
        stopped = asyncio.Event()

        async def loop():
            while not stopped.is_set():
                try:
                    await asyncio.to_thread(application.state.coordinator.run_once)
                    application.state.processing_error = None
                except Exception as error:
                    application.state.processing_error = type(error).__name__
                    logger.error("Coordinator step failed: %s", type(error).__name__)
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=1)
                except TimeoutError:
                    pass

        task = asyncio.create_task(loop()) if background else None
        try:
            yield
        finally:
            stopped.set()
            if task:
                await task
            if store is None and hasattr(application.state.service.store, "client"):
                application.state.service.store.client.close()

    app = FastAPI(title="ShiftOver core API", version="0.2.0", lifespan=lifespan)
    install_handlers(app)

    def service():
        return app.state.service

    @app.get("/api/health")
    def health():
        return {
            "ok": service().store.ping(),
            "storage": settings.storage_backend,
            "demo_mode": settings.demo_mode,
            "inference_enabled": settings.inference_enabled,
            "processing_error": app.state.processing_error,
        }

    @app.get("/api/forms")
    def forms():
        return {
            "roles": [role.value for role in Role],
            "statuses": [state.value for state in Status],
            "actions": [
                {
                    "action": action.value,
                    "required": required,
                    "optional": optional,
                    "roles": sorted(role.value for role in allowed_roles(action)),
                }
                for action, (required, optional) in FORM_FIELDS.items()
            ],
            "policies": [
                metadata
                for _, metadata, _ in service().knowledge.sources()
                if metadata.get("document_type") == "verification_policy"
            ],
            "manual_identity": True,
        }

    @app.post("/api/demo/seed")
    def seed():
        return service().seed()

    @app.post("/api/organization/seed")
    def seed_organization():
        return service().seed_automotive()

    @app.get("/api/organization")
    def organization():
        records = service().store.find("organizations", limit=1)
        return records[0] if records else None

    @app.get("/api/vehicles")
    def vehicles():
        return service().store.find("vehicles")

    @app.get("/api/part-checks")
    def part_checks(vehicle_id: str | None = None, machine_id: str | None = None):
        filters = {}
        if vehicle_id:
            filters["vehicle_id"] = vehicle_id
        if machine_id:
            filters["machine_id"] = machine_id
        return service().store.find("part_checks", filters)

    @app.get("/api/diagnostics")
    def integration_diagnostics():
        return diagnostics(service())

    @app.post("/api/inference-tests", status_code=201)
    async def create_inference_test(
        source_type: Annotated[str, Form()],
        text: Annotated[str | None, Form()] = None,
        file: Annotated[UploadFile | None, File()] = None,
        capability: Annotated[str | None, Form()] = None,
    ):
        payload = None
        content_type = None
        if file:
            content_type = file.content_type
            payload = await file.read(settings.max_upload_bytes + 1)
            await file.close()
        return await asyncio.to_thread(
            InferenceTests(service()).create,
            source_type,
            text,
            payload,
            content_type,
            capability,
        )

    @app.get("/api/inference-tests/{test_id}")
    def inference_test(test_id: str):
        return InferenceTests(service()).read(test_id)

    @app.get("/api/machines")
    def machines():
        return service().store.find("machines")

    @app.get("/api/models")
    def models():
        return list_models()

    @app.post("/api/submissions", status_code=201)
    async def capture_submission(
        capture: Annotated[str, Form()],
        text: Annotated[str | None, Form()] = None,
        file: Annotated[UploadFile | None, File()] = None,
    ):
        try:
            contract = Capture.model_validate_json(capture)
        except (ValidationError, ValueError) as error:
            raise NimbusError(
                "invalid_capture", "Capture metadata must match the Capture JSON schema."
            ) from error
        payload = None
        if file:
            payload = await file.read(settings.max_upload_bytes + 1)
            await file.close()
        record = await asyncio.to_thread(
            service().capture, contract, text, payload, file.content_type if file else None
        )
        return await asyncio.to_thread(app.state.coordinator.process, record["_id"])

    @app.get("/api/submissions/{submission_id}")
    def submission(submission_id: str):
        return service().required("submissions", submission_id)

    @app.get("/api/submissions")
    def submissions(processing_status: str | None = None):
        return service().store.find(
            "submissions", {"processing_status": processing_status} if processing_status else {}
        )

    @app.post("/api/submissions/{submission_id}/process")
    def process(submission_id: str):
        return app.state.coordinator.process(submission_id)

    @app.post("/api/submissions/{submission_id}/text-revisions")
    def correct(submission_id: str, correction: TextCorrection):
        service().revise_text(submission_id, correction.text, correction.actor)
        return app.state.coordinator.process(submission_id)

    @app.post("/api/submissions/{submission_id}/confirm")
    def confirm(submission_id: str, confirmation: Confirmation):
        return service().confirm(submission_id, confirmation)

    @app.post("/api/submissions/{submission_id}/manual-form")
    def manual_form(submission_id: str, actor: Actor):
        service().use_manual_form(submission_id, actor)
        return app.state.coordinator.process(submission_id)

    @app.get("/api/submissions/{submission_id}/source")
    def source(submission_id: str):
        record = service().required("submissions", submission_id)
        if record["source_type"] == "text":
            return {"text": record["source"]["original_text"]}
        return FileResponse(
            service().media.resolve(record["source"]["media_key"]),
            media_type=record["source"]["content_type"],
        )

    @app.get("/api/tickets")
    def tickets(
        machine_id: str | None = None,
        status: Status | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ):
        filters = {}
        if machine_id:
            filters["machine_id"] = machine_id
        if status:
            filters["status"] = status.value
        return service().store.find("tickets", filters, limit)

    @app.get("/api/tickets/{ticket_id}")
    def ticket(ticket_id: str):
        return service().required("tickets", ticket_id)

    @app.get("/api/tickets/{ticket_id}/advice")
    def advice(ticket_id: str):
        return ticket_advice(service(), ticket_id)

    @app.get("/api/tickets/{ticket_id}/export")
    def export(ticket_id: str):
        record = service().required("tickets", ticket_id)
        submissions = [
            service().required("submissions", event["submission_id"])
            for event in record["activities"]
        ]
        return {"schema_version": 1, "ticket": record, "submissions": submissions}

    @app.get("/api/observations")
    def observations(machine_id: str | None = None):
        return service().store.find(
            "observations", {"machine_id": machine_id} if machine_id else {}
        )

    @app.get("/api/handover")
    def handover(shift_id: str = "night", person_id: str = "op_night"):
        active = []
        for state in (Status.OPEN, Status.IN_PROGRESS, Status.UNDER_REVIEW):
            for record in service().store.find("tickets", {"status": state.value}):
                acknowledged = any(
                    ack["actor"]["person_id"] == person_id
                    and ack["shift_id"] == shift_id
                    and ack["content_revision"] == record["content_revision"]
                    for ack in record["handover_acknowledgments"]
                )
                active.append(
                    {
                        "ticket_id": record["_id"],
                        "title": record["title"],
                        "machine_id": record["machine_id"],
                        "status": record["status"],
                        "next_action": record["next_action"],
                        "content_revision": record["content_revision"],
                        "acknowledged": acknowledged,
                    }
                )
        return {"shift_id": shift_id, "active_faults": active}

    @app.get("/api/knowledge/search")
    def search(
        q: Annotated[str, Query(min_length=1, max_length=2000)], machine_type: str = "general"
    ):
        retriever = app.state.coordinator.retriever
        if settings.retrieval_backend == "embedding" and retriever.encoder is None:
            from .knowledge import OpenEncoder

            retriever.encoder = OpenEncoder(revision=settings.embedding_revision)
        return {
            "backend": settings.retrieval_backend,
            "matches": service().knowledge.search(q, machine_type, encoder=retriever.encoder),
        }

    @app.get("/api/workers")
    def workers():
        return service().store.find("workers")

    @app.get("/api/jobs")
    def jobs(status: str = "queued"):
        return [
            {key: value for key, value in row.items() if key not in {"lease", "input", "result"}}
            for row in service().store.find("jobs", {"status": status})
        ]

    static = ROOT / "web" / "dist"
    if (static / "assets").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        path = static / "favicon.svg"
        if not path.is_file():
            raise NimbusError("ui_not_built", "Build the web interface first.", 404)
        return FileResponse(path, media_type="image/svg+xml")

    @app.get("/", include_in_schema=False)
    def index():
        if (static / "index.html").exists():
            return FileResponse(static / "index.html")
        return {
            "app": "ShiftOver",
            "ui": "Build web with npm run build or run its Vite development server.",
            "api_docs": "/docs",
        }

    return app


app = create_app()
