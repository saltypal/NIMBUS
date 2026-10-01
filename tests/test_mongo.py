"""Opt-in integration against real MongoDB; each run owns a disposable database."""

import os
from uuid import uuid4

import pytest
from test_service import confirmation, report_capture

from nimbus.database import MongoStore
from nimbus.processing import Coordinator
from nimbus.service import Service


@pytest.mark.skipif(
    os.getenv("NIMBUS_TEST_MONGO") != "1", reason="Set NIMBUS_TEST_MONGO=1 with MongoDB running"
)
def test_real_mongo_persistence_indexes_and_replay(settings, operator):
    database = "nimbus_test_" + uuid4().hex
    store = MongoStore(settings.mongo_uri, database)
    try:
        store.initialize()
        service = Service(store, settings)
        service.seed()
        draft = Coordinator(service).process(service.capture(report_capture(operator))["_id"])
        form = confirmation(draft, operator)
        accepted = service.confirm(draft["_id"], form)
        second = MongoStore(settings.mongo_uri, database)
        try:
            fresh = Service(second, settings)
            assert fresh.confirm(draft["_id"], form) == accepted
            assert fresh.required("tickets", accepted["ticket_id"])["version"] == 1
            assert "client_operation_id_1" in store.database.submissions.index_information()
        finally:
            second.client.close()
    finally:
        store.client.drop_database(database)
        store.client.close()
