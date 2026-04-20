"""/users + /roles + RBAC 测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_users_requires_auth(client: TestClient):
    r = client.get("/users")
    assert r.status_code == 401


def test_admin_can_list_users(client: TestClient, admin_headers):
    r = client.get("/users", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert any(u["email"] == "admin@example.com" for u in data["items"])


def test_admin_can_create_and_update_user(client: TestClient, admin_headers):
    # create
    r = client.post(
        "/users",
        headers=admin_headers,
        json={
            "email": "newbie@example.com",
            "password": "newbie1234",
            "name": "新同事",
            "role_id": 4,  # business
        },
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]

    # fetch single
    r = client.get(f"/users/{uid}", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["email"] == "newbie@example.com"

    # update name + role
    r = client.patch(
        f"/users/{uid}",
        headers=admin_headers,
        json={"name": "新同事改名", "role_id": 3},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "新同事改名"
    assert body["role"]["name"] == "gov"

    # duplicate email -> 409
    dup = client.post(
        "/users",
        headers=admin_headers,
        json={"email": "newbie@example.com", "password": "ignored12345"},
    )
    assert dup.status_code == 409


def test_rbac_auditor_can_read_but_not_write(client: TestClient, admin_headers):
    # admin 创建一个 auditor
    r = client.post(
        "/users",
        headers=admin_headers,
        json={"email": "audit1@example.com", "password": "audit1234", "role_id": 2},
    )
    assert r.status_code == 201

    login = client.post(
        "/auth/login",
        json={"email": "audit1@example.com", "password": "audit1234"},
    )
    token = login.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # auditor 有 user:read
    assert client.get("/users", headers=h).status_code == 200
    # auditor 没 user:write -> 403
    create_resp = client.post(
        "/users",
        headers=h,
        json={"email": "mal@example.com", "password": "malicious1234"},
    )
    assert create_resp.status_code == 403


def test_self_delete_blocked(client: TestClient, admin_headers):
    me = client.get("/auth/me", headers=admin_headers).json()
    r = client.delete(f"/users/{me['id']}", headers=admin_headers)
    assert r.status_code == 400


def test_roles_listing(client: TestClient, admin_headers):
    r = client.get("/roles", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    names = {x["name"] for x in data}
    assert {"admin", "auditor", "gov", "business", "guest"}.issubset(names)
    admin_role = next(x for x in data if x["name"] == "admin")
    assert "user:write" in admin_role["permissions"]


def test_system_health(client: TestClient):
    r = client.get("/system/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["db"] is True
