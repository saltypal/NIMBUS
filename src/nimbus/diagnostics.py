"""Read-only runtime facts for the browser's integration Test view."""

from datetime import timedelta

from .config import ROOT
from .util import utcnow

COLLECTIONS = (
    "organizations",
    "machines",
    "vehicles",
    "part_checks",
    "submissions",
    "observations",
    "tickets",
    "jobs",
    "workers",
    "knowledge_chunks",
    "inference_tests",
)


def diagnostics(service):
    store = service.store
    settings = service.settings
    connected = store.ping()
    mongo = hasattr(store, "database") and hasattr(store, "client")
    counts = {
        name: store.database[name].count_documents({}) if mongo else len(store.find(name))
        for name in COLLECTIONS
    }
    jobs = {
        status: store.database.jobs.count_documents({"status": status})
        if mongo
        else len(store.find("jobs", {"status": status}))
        for status in ("queued", "leased", "succeeded", "failed")
    }
    workers = store.find("workers")
    leased = store.find("jobs", {"status": "leased"})
    now = utcnow()
    active_workers = {
        job["lease"]["worker_id"]
        for job in leased
        if job.get("lease")
        and job["lease"]["expires_at"] > now
        and job["lease"]["started_at"] + timedelta(seconds=settings.job_max_runtime_seconds) > now
    }
    capabilities = {}
    for capability, key in settings.worker_keys().items():
        ready = 0
        for worker in workers:
            online = (
                worker["last_heartbeat_at"] >= now - timedelta(seconds=90)
                or worker["_id"] in active_workers
            )
            worker["online"] = online
            if worker["capability"] == capability and worker["ready"] and online:
                ready += 1
        capabilities[capability] = {"configured": bool(key), "ready_workers": ready}
    binary = ROOT / ".tools" / "mongodb" / "bin" / "mongod.exe"
    return {
        "database": {
            "connected": connected,
            "backend": settings.storage_backend,
            "name": store.database.name if mongo else "isolated-memory",
            "server_version": store.client.server_info()["version"] if mongo else None,
            "collections": counts,
            "counts_bounded": not mongo,
            "mongodb_binary": str(binary) if binary.exists() else None,
            "data_path": str(settings.data_dir / "mongodb") if binary.exists() else None,
        },
        "retrieval": {
            "backend": settings.retrieval_backend,
            "vector_index_enabled": False,
            "embedding_model": "Qwen/Qwen3-Embedding-0.6B"
            if settings.retrieval_backend == "embedding"
            else None,
            "description": "Keyword retrieval"
            if settings.retrieval_backend == "lexical"
            else "Embedding cosine similarity computed in Python; no MongoDB vector index",
        },
        "inference_enabled": settings.inference_enabled,
        "capabilities": capabilities,
        "workers": workers,
        "jobs": jobs,
        "result_path": "Worker → HTTPS bridge → MongoDB → local API → browser polling",
    }
