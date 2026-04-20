"""/auth 路由测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_login_success(client: TestClient):
    r = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "test_admin_pw"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["expires_in"] > 0


def test_login_wrong_password(client: TestClient):
    r = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "wrong_pw"},
    )
    assert r.status_code == 401


def test_login_unknown_user(client: TestClient):
    r = client.post(
        "/auth/login",
        json={"email": "ghost@example.com", "password": "pw"},
    )
    assert r.status_code == 401


def test_me_requires_token(client: TestClient):
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_me_returns_user(client: TestClient, admin_headers: dict[str, str]):
    r = client.get("/auth/me", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == "admin@example.com"
    assert data["role"]["name"] == "admin"


def test_refresh_issues_new_token(client: TestClient):
    login = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "test_admin_pw"},
    )
    refresh_tok = login.json()["refresh_token"]
    r = client.post("/auth/refresh", json={"refresh_token": refresh_tok})
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_refresh_rejects_access_token(client: TestClient, admin_token: str):
    r = client.post("/auth/refresh", json={"refresh_token": admin_token})
    assert r.status_code == 401


def test_logout(client: TestClient, admin_headers: dict[str, str]):
    r = client.post("/auth/logout", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True
