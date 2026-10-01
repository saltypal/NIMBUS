"""A small document-store port with real MongoDB and isolated memory adapters."""

from copy import deepcopy
from threading import RLock
from typing import Protocol

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from .errors import Conflict, NimbusError

UNIQUE = {
    "submissions": ["client_operation_id"],
    "tickets": ["origin_submission_id"],
    "jobs": ["logical_key"],
}


class Store(Protocol):
    def insert(self, collection: str, document: dict) -> dict: ...
    def get(self, collection: str, record_id: str) -> dict | None: ...
    def find(
        self, collection: str, filters: dict | None = None, limit: int = 200
    ) -> list[dict]: ...
    def replace(self, collection: str, document: dict, expected: dict) -> bool: ...
    def ping(self) -> bool: ...


class MemoryStore:
    """Explicitly nonpersistent test adapter. Each instance owns its own data."""

    def __init__(self):
        self._collections = {}
        self._lock = RLock()

    def insert(self, collection, document):
        with self._lock:
            rows = self._collections.setdefault(collection, {})
            if document["_id"] in rows:
                raise Conflict("duplicate_record", "Record already exists.")
            for field in UNIQUE.get(collection, []):
                if any(row.get(field) == document.get(field) for row in rows.values()):
                    raise Conflict("duplicate_record", f"Duplicate {field}.")
            rows[document["_id"]] = deepcopy(document)
            return deepcopy(document)

    def get(self, collection, record_id):
        with self._lock:
            return deepcopy(self._collections.get(collection, {}).get(record_id))

    def find(self, collection, filters=None, limit=200):
        with self._lock:
            rows = self._collections.get(collection, {}).values()
            matches = [
                row
                for row in rows
                if all(row.get(key) == value for key, value in (filters or {}).items())
            ]
            return deepcopy(matches[:limit])

    def replace(self, collection, document, expected):
        with self._lock:
            current = self._collections.get(collection, {}).get(document["_id"])
            if current is None or any(current.get(key) != value for key, value in expected.items()):
                return False
            self._collections[collection][document["_id"]] = deepcopy(document)
            return True

    def ping(self):
        return True


class MongoStore:
    def __init__(self, uri, database):
        self.client = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=3000)
        self.database = self.client[database]

    def initialize(self):
        self.ping()
        for collection, fields in UNIQUE.items():
            for field in fields:
                self.database[collection].create_index(field, unique=True)
        self.database.tickets.create_index([("machine_id", 1), ("status", 1)])
        self.database.jobs.create_index([("capability", 1), ("status", 1)])

    def insert(self, collection, document):
        try:
            self.database[collection].insert_one(deepcopy(document))
        except DuplicateKeyError as error:
            raise Conflict(
                "duplicate_record", "This record or logical operation already exists."
            ) from error
        return deepcopy(document)

    def get(self, collection, record_id):
        return self.database[collection].find_one({"_id": record_id})

    def find(self, collection, filters=None, limit=200):
        return list(self.database[collection].find(filters or {}).limit(limit))

    def replace(self, collection, document, expected):
        query = {"_id": document["_id"], **expected}
        result = self.database[collection].replace_one(query, deepcopy(document))
        return result.matched_count == 1

    def ping(self):
        self.client.admin.command("ping")
        return True


def create_store(settings):
    if settings.storage_backend == "memory":
        return MemoryStore()
    if settings.storage_backend != "mongo":
        raise NimbusError("invalid_storage_backend", "Choose mongo or memory.")
    store = MongoStore(settings.mongo_uri, settings.database)
    store.initialize()
    return store
