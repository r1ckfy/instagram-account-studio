import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.db import Database  # noqa: E402


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    yield d
    d.close()


@pytest.fixture
def profile():
    return {"full_name": "Antonella Virelli", "username": "antovire", "email": "anto@example.com",
            "birthdate": "2003-04-14", "bio": "22y | alagoana 🌴", "profile_type": "Modelo virtual",
            "notes": "", "status": "preparado"}
