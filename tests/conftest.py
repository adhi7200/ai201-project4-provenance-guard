"""Shared pytest fixtures.

Tests get an isolated SQLite database (a temp file, one per test) so they never
touch the app's real provenance.db. store.DB_PATH is repointed for the duration
of each test that requests the `db` fixture.
"""

import os
import sys

import pytest

# Make the project modules importable when running pytest from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import store  # noqa: E402


@pytest.fixture
def db(tmp_path):
    original = store.DB_PATH
    store.DB_PATH = str(tmp_path / "test_provenance.db")
    store.init_db()
    yield store
    store.DB_PATH = original
