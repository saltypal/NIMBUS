"""Small commands for each layer. python -m nimbus.cli --help lists them."""

import argparse
import json
import platform
import sys
import time
from pathlib import Path

from .config import Settings
from .database import create_store
from .errors import NimbusError
from .models import list_models
from .service import Service
from .util import json_default


def make_adapter(
    capability, model_id=None, revision=None, device="cpu", llm_backend="transformers", llm_url=None
):
    import os
    import random

    import numpy as np

    seed = int(os.getenv("NIMBUS_RUNTIME_SEED", "42"))
    random.seed(seed)
    np.random.seed(seed)
    if capability != "speech":
        import torch

        torch.manual_seed(seed)
    if capability == "speech":
        from .inference.speech import SpeechAdapter

        index = int(device.split(":")[1]) if ":" in device else 0
        return SpeechAdapter(
            model_id,
            revision,
            device="cuda" if device.startswith("cuda") else "cpu",
            device_index=index,
        )
    if capability == "handwriting":
        from .inference.handwriting import HandwritingAdapter

        return HandwritingAdapter(model_id, revision, device)
    if llm_backend == "vllm":
        from .inference.llm import LLMAdapter

        return LLMAdapter(model_id, revision, url=llm_url or "http://127.0.0.1:9000/v1")
    from .inference.llm import TransformerLLMAdapter

    return TransformerLLMAdapter(model_id, revision, device)


def parser():
    root = argparse.ArgumentParser(
        prog="shiftover", description="Run each ShiftOver module independently."
    )
    root.add_argument("--storage", choices=["mongo", "memory"], default=None)
    root.add_argument("--output", type=Path, help="Also save JSON output to this file.")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("models")
    commands.add_parser("doctor")
    seed = commands.add_parser("seed")
    seed.add_argument(
        "--automotive", action="store_true", help="Load the car production workspace."
    )
    commands.add_parser("demo")
    capture = commands.add_parser(
        "capture", help="Save one source without processing or committing it."
    )
    capture.add_argument(
        "metadata", type=Path, help="Capture schema JSON, including role and action."
    )
    capture.add_argument(
        "--input", required=True, type=Path, help="UTF-8 text, audio, or image source."
    )
    capture.add_argument("--content-type", help="Override the media MIME type when needed.")
    inspect = commands.add_parser("inspect", help="Read one stored record without changing it.")
    inspect.add_argument(
        "collection",
        choices=["submissions", "tickets", "jobs", "observations", "workers", "machines"],
    )
    inspect.add_argument("record_id")
    confirm = commands.add_parser("confirm", help="Commit a manually reviewed Confirmation JSON.")
    confirm.add_argument("submission_id")
    confirm.add_argument("confirmation", type=Path)
    coordinator = commands.add_parser("process")
    coordinator.add_argument("--submission-id")
    coordinator.add_argument("--once", action="store_true")
    coordinator.add_argument("--poll-seconds", type=float, default=1)
    retrieve = commands.add_parser("retrieve")
    retrieve.add_argument("query")
    retrieve.add_argument("--machine-type", default="demo_press")
    retrieve.add_argument("--embedding", action="store_true")
    workflow = commands.add_parser("workflow")
    workflow.add_argument(
        "fixture",
        type=Path,
        help="JSON with ticket, action, actor, fields, optional policy and policy_hash",
    )
    for name in ("infer", "worker"):
        inference = commands.add_parser(name)
        inference.add_argument("capability", choices=["speech", "handwriting", "llm"])
        inference.add_argument("--model-id")
        inference.add_argument("--revision")
        inference.add_argument("--device", default="cpu")
        inference.add_argument(
            "--llm-backend", choices=["transformers", "vllm"], default="transformers"
        )
        inference.add_argument("--llm-url", default="http://127.0.0.1:9000/v1")
        if name == "infer":
            inference.add_argument(
                "--input", type=Path, help="Audio/image file, or LLM payload JSON"
            )
        else:
            inference.add_argument("--bridge-url", required=True)
            inference.add_argument("--results-dir", type=Path, default=Path("artifacts/worker"))
            inference.add_argument("--once", action="store_true")
    runtime = commands.add_parser("runtime")
    runtime.add_argument("--config", required=True, type=Path)
    for name, default_port in (("api", 8000), ("bridge", 8001)):
        server = commands.add_parser(name)
        server.add_argument("--host", default="127.0.0.1")
        server.add_argument("--port", type=int, default=default_port)
    return root


def execute(arguments):
    settings = Settings()
    if arguments.storage:
        settings.storage_backend = arguments.storage
    if arguments.command == "models":
        return list_models()
    if arguments.command in {"api", "bridge"}:
        import uvicorn

        module = "nimbus.api" if arguments.command == "api" else "nimbus.bridge"
        # Factory injection preserves CLI storage selection without env mutation.
        from importlib import import_module

        uvicorn.run(
            import_module(module).create_app(settings), host=arguments.host, port=arguments.port
        )
        return None
    if arguments.command == "workflow":
        from .schemas import Action, Actor, Policy
        from .workflow import transition

        fixture = json.loads(arguments.fixture.read_text(encoding="utf-8-sig"))
        return transition(
            fixture.get("ticket"),
            Action(fixture["action"]),
            Actor.model_validate(fixture["actor"]),
            fixture["fields"],
            policy=Policy.model_validate(fixture["policy"]) if fixture.get("policy") else None,
            policy_hash=fixture.get("policy_hash"),
        )
    if arguments.command == "runtime":
        from .runtime import run_runtime

        return run_runtime(json.loads(arguments.config.read_text(encoding="utf-8-sig")))
    if arguments.command in {"infer", "worker"}:
        adapter = make_adapter(
            arguments.capability,
            arguments.model_id,
            arguments.revision,
            arguments.device,
            arguments.llm_backend,
            arguments.llm_url,
        )
        if arguments.command == "infer":
            smoke = adapter.smoke()
            if arguments.input is None:
                return {
                    "model_id": adapter.model_id,
                    "revision": adapter.model_revision,
                    "smoke": smoke,
                }
            payload = (
                json.loads(arguments.input.read_text(encoding="utf-8-sig"))
                if arguments.capability == "llm"
                else {}
            )
            return adapter.run(payload, arguments.input if arguments.capability != "llm" else None)
        from .runtime import environment_info, source_info
        from .worker import Worker, capability_key

        worker = Worker(
            arguments.capability,
            adapter,
            arguments.bridge_url,
            capability_key(arguments.capability),
            arguments.results_dir,
        )
        worker.register({**environment_info(), **source_info()})
        worker.run(once=arguments.once)
        return None
    if arguments.command == "retrieve":
        from .knowledge import Knowledge, OpenEncoder

        encoder = OpenEncoder(revision=settings.embedding_revision) if arguments.embedding else None
        return {
            "backend": "embedding" if encoder else "lexical",
            "matches": Knowledge(settings.knowledge_dir).search(
                arguments.query, arguments.machine_type, encoder=encoder
            ),
        }
    store = create_store(settings)
    try:
        service = Service(store, settings)
        if arguments.command == "doctor":
            return {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "database_ok": store.ping(),
                "storage": settings.storage_backend,
                "knowledge_sources": len(list(service.knowledge.sources())),
                "configured_capabilities": [
                    name for name, key in settings.worker_keys().items() if key
                ],
                "inference_enabled": settings.inference_enabled,
            }
        if arguments.command == "seed":
            return service.seed_automotive() if arguments.automotive else service.seed()
        if arguments.command == "capture":
            import mimetypes

            from .schemas import Capture

            capture = Capture.model_validate_json(
                arguments.metadata.read_text(encoding="utf-8-sig")
            )
            if capture.source_type == "text":
                return service.capture(capture, text=arguments.input.read_text(encoding="utf-8"))
            mime = arguments.content_type or mimetypes.guess_type(str(arguments.input))[0]
            if not mime:
                raise NimbusError("content_type_required", "Supply a supported media MIME type.")
            with arguments.input.open("rb") as stream:
                payload = stream.read(settings.max_upload_bytes + 1)
            return service.capture(capture, payload=payload, content_type=mime)
        if arguments.command == "inspect":
            return service.required(arguments.collection, arguments.record_id)
        if arguments.command == "confirm":
            from .schemas import Confirmation

            confirmed = Confirmation.model_validate_json(
                arguments.confirmation.read_text(encoding="utf-8-sig")
            )
            return service.confirm(arguments.submission_id, confirmed)
        if arguments.command == "demo":
            from .demo import replay

            return replay(service)
        from .processing import Coordinator

        coordinator = Coordinator(service)
        if arguments.submission_id:
            return coordinator.process(arguments.submission_id)
        while True:
            result = {"changed": coordinator.run_once()}
            if arguments.once:
                return result
            print(json.dumps(result), flush=True)
            time.sleep(arguments.poll_seconds)
    finally:
        if hasattr(store, "client"):
            store.client.close()


def main():
    arguments = parser().parse_args()
    try:
        result = execute(arguments)
        if result is not None:
            output = json.dumps(result, indent=2, ensure_ascii=False, default=json_default)
            print(output)
            if arguments.output:
                arguments.output.parent.mkdir(parents=True, exist_ok=True)
                arguments.output.write_text(output + "\n", encoding="utf-8")
    except NimbusError as error:
        print(
            json.dumps(
                {"error": {"code": error.code, "message": error.message, "details": error.details}}
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
