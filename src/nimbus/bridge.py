"""Restricted outbound worker bridge. Expose only this port through a tunnel."""

import hmac
import json
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header
from fastapi.responses import FileResponse
from pydantic import Field, ValidationError

from .config import Settings
from .database import create_store
from .errors import NimbusError
from .http_support import install_handlers
from .jobs import JobQueue
from .models import resolve_model
from .schemas import Draft, StrictModel
from .service import Service


class Register(StrictModel):
    capability: Literal["speech", "handwriting", "llm"]
    model_id: str
    model_revision: str = Field(min_length=1, max_length=100)
    ready: bool = False
    runtime: dict = Field(default_factory=dict)


class WorkerRequest(StrictModel):
    worker_id: str


class Result(WorkerRequest):
    attempt_id: str
    output: dict


class Failure(WorkerRequest):
    code: str = Field(max_length=160)
    retryable: bool = True


def create_app(settings=None, store=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(application):
        application.state.service = Service(store or create_store(settings), settings)
        application.state.queue = JobQueue(application.state.service.store, settings)
        try:
            yield
        finally:
            if store is None and hasattr(application.state.service.store, "client"):
                application.state.service.store.client.close()

    app = FastAPI(
        title="ShiftOver worker bridge",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    install_handlers(app)

    def capability(authorization: Annotated[str | None, Header()] = None):
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        for name, key in settings.worker_keys().items():
            if key and token and hmac.compare_digest(token, key):
                return name
        raise NimbusError(
            "invalid_worker_key", "A configured capability credential is required.", 401
        )

    def queue():
        return app.state.queue

    def attempt(x_attempt_token: Annotated[str, Header()]):
        return x_attempt_token

    @app.get("/bridge/health")
    def health(scope: Annotated[str, Depends(capability)]):
        return {"ok": app.state.service.store.ping(), "capability": scope}

    @app.post("/bridge/workers/register")
    def register(request: Register, scope: Annotated[str, Depends(capability)]):
        if request.capability != scope:
            raise NimbusError(
                "worker_scope_mismatch", "Credential cannot register that capability.", 403
            )
        resolve_model(request.model_id, scope)
        return queue().register(scope, request.model_dump())

    @app.post("/bridge/workers/{worker_id}/heartbeat")
    def worker_heartbeat(worker_id: str, scope: Annotated[str, Depends(capability)]):
        return queue().worker_heartbeat(worker_id, scope)

    @app.post("/bridge/jobs/claim")
    def claim(request: WorkerRequest, scope: Annotated[str, Depends(capability)]):
        return {"job": queue().claim(request.worker_id, scope)}

    @app.get("/bridge/jobs/{job_id}/input")
    def input(
        job_id: str,
        scope: Annotated[str, Depends(capability)],
        token: Annotated[str, Depends(attempt)],
    ):
        payload = queue().input(job_id, scope, token)
        if "media_key" in payload:
            payload = {key: value for key, value in payload.items() if key != "media_key"}
            payload["media_url"] = f"/bridge/jobs/{job_id}/media"
        return payload

    @app.get("/bridge/jobs/{job_id}/media")
    def media(
        job_id: str,
        scope: Annotated[str, Depends(capability)],
        token: Annotated[str, Depends(attempt)],
    ):
        payload = queue().input(job_id, scope, token)
        if scope == "llm" or "media_key" not in payload:
            raise NimbusError("media_scope_mismatch", "This job has no permitted media input.", 403)
        return FileResponse(
            app.state.service.media.resolve(payload["media_key"]),
            media_type=payload["content_type"],
        )

    @app.post("/bridge/jobs/{job_id}/heartbeat")
    def heartbeat(
        job_id: str,
        request: WorkerRequest,
        scope: Annotated[str, Depends(capability)],
        token: Annotated[str, Depends(attempt)],
    ):
        return queue().heartbeat(job_id, scope, token, request.worker_id)

    @app.post("/bridge/jobs/{job_id}/result")
    def result(
        job_id: str,
        request: Result,
        scope: Annotated[str, Depends(capability)],
        token: Annotated[str, Depends(attempt)],
    ):
        output = request.output
        if len(json.dumps(output, ensure_ascii=False)) > 100_000:
            raise NimbusError(
                "result_limit_exceeded", "Worker output exceeds the result size bound.", 413
            )
        allowed = (
            {"draft", "model_id", "model_revision"}
            if scope == "llm"
            else {"text", "model_id", "model_revision"}
        )
        if set(output) != allowed:
            raise NimbusError("invalid_result", "Return the exact capability result fields.")
        resolve_model(output["model_id"], scope)
        worker = queue().worker(request.worker_id, scope)
        if (
            output["model_id"] != worker["runtime"]["model_id"]
            or output["model_revision"] != worker["runtime"]["model_revision"]
        ):
            raise NimbusError(
                "model_identity_mismatch", "Result must match the registered model and revision."
            )
        if scope == "llm":
            try:
                Draft.model_validate(output["draft"])
            except ValidationError as error:
                raise NimbusError(
                    "invalid_result_draft", "Draft does not match the declared schema."
                ) from error
        elif (
            not isinstance(output["text"], str)
            or len(output["text"]) > settings.max_text_characters
        ):
            raise NimbusError("invalid_result_text", "Normalized text exceeds its contract.")
        return queue().result(job_id, scope, token, request.worker_id, request.attempt_id, output)

    @app.post("/bridge/jobs/{job_id}/fail")
    def fail(
        job_id: str,
        request: Failure,
        scope: Annotated[str, Depends(capability)],
        token: Annotated[str, Depends(attempt)],
    ):
        return queue().fail(
            job_id, scope, token, request.worker_id, request.code, request.retryable
        )

    return app


app = create_app()
