"""pytest 共享 fixtures — 每个 test 独立 SQLite 内存 DB + fresh TestClient。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 确保 backend 包可 import
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 用临时文件 SQLite（:memory: 在多线程下每个连接各自独立，无法共享表）
_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP_DB.close()
os.environ["MYBUILD_DATABASE_URL"] = f"sqlite:///{_TMP_DB.name}"
os.environ["MYBUILD_JWT_SECRET"] = "test_secret_do_not_use_in_prod"
os.environ["MYBUILD_BOOTSTRAP_ADMIN_EMAIL"] = "admin@example.com"
os.environ["MYBUILD_BOOTSTRAP_ADMIN_PASSWORD"] = "test_admin_pw"

import pytest
from fastapi.testclient import TestClient

from backend.bootstrap import bootstrap  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    """session-scope：建表 + bootstrap 默认角色 + admin 用户。"""
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        bootstrap(db)
    yield
    Base.metadata.drop_all(bind=engine)
    try:
        os.unlink(_TMP_DB.name)
    except Exception:
        pass


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def admin_token(client: TestClient) -> str:
    r = client.post("/auth/login", json={"email": "admin@example.com", "password": "test_admin_pw"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture()
def admin_headers(admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}
