from pathlib import Path

import pytest

from nimbus.config import ROOT, Settings
from nimbus.database import MemoryStore
from nimbus.schemas import Actor, Role
from nimbus.service import Service


@pytest.fixture
def operator():
    return Actor(person_id="op_day", display_name="Day operator", role=Role.OPERATOR)


@pytest.fixture
def supervisor():
    return Actor(person_id="supervisor", display_name="Supervisor", role=Role.SUPERVISOR)


@pytest.fixture
def settings(tmp_path: Path):
    return Settings(storage_backend="memory", data_dir=tmp_path, knowledge_dir=ROOT / "knowledge")


@pytest.fixture
def service(settings):
    result = Service(MemoryStore(), settings)
    result.seed()
    return result
