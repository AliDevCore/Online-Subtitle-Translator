"""
Pytest configuration, environment isolation, and shared fixtures for Online Subtitle Translator.
"""

import os
import sys
from pathlib import Path
import pytest

# Ensure headless Qt for CI/CD and offscreen testing
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def isolate_environment(tmp_path, monkeypatch):
    """Isolate user data directory and credential cache for each test."""
    test_data_dir = tmp_path / "app_data"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("APPDATA", str(test_data_dir))

    from app.core.credential_manager import CredentialManager
    CredentialManager.clear_cache()
    yield
    CredentialManager.clear_cache()


@pytest.fixture
def sample_srt_text():
    return (
        "1\n"
        "00:00:01,000 --> 00:00:04,500\n"
        "Hello and welcome to the tutorial.\n\n"
        "2\n"
        "00:00:05,000 --> 00:00:08,200\n"
        "Today we are going to learn about subtitle translation.\n\n"
        "3\n"
        "00:00:09,000 --> 00:00:12,000\n"
        "Let's get started right away.\n"
    )


@pytest.fixture
def temp_database(tmp_path):
    from app.core.database import Database
    db_file = tmp_path / "test_onlinesubtitletranslator.db"
    return Database(db_file)
