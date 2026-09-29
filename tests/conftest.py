"""
The env var must be set *before* app.database (and anything importing it)
is first imported, since DB_PATH is read at module load time. Conftest
files are imported by pytest before sibling test modules, so setting it
here at module scope - rather than inside a fixture - guarantees the app
never touches the developer's real data/incidents.db during tests.
"""
import os
import tempfile

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["INCIDENT_AGENT_DB_PATH"] = _TEST_DB_PATH

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def pytest_sessionfinish(session, exitstatus):
    try:
        os.remove(_TEST_DB_PATH)
    except OSError:
        pass
