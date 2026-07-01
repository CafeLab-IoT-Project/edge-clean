from __future__ import annotations

import importlib

import pytest

from iam.application.services import IamApplicationService
from shared.infrastructure.database import db, init_db


@pytest.fixture()
def db_session(tmp_path):
    if not db.is_closed():
        db.close()

    db.init(
        str(tmp_path / "edge-test.db"),
        pragmas={
            "journal_mode": "wal",
            "busy_timeout": 5000,
        },
    )
    init_db()
    IamApplicationService().get_or_create_development_device()

    yield

    if not db.is_closed():
        db.close()


@pytest.fixture()
def app_client(db_session, monkeypatch):
    app_module = importlib.import_module("app")
    app_module.first_request = False
    app_module.app.config.update(TESTING=True)

    monkeypatch.setattr(app_module.sync_worker, "start", lambda: None)
    monkeypatch.setattr(app_module.sync_worker, "notify", lambda: None)

    with app_module.app.test_client() as client:
        yield client
