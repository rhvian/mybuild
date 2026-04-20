"""/projects 项目监管测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_project_create_and_list(client: TestClient, admin_headers):
    r = client.post(
        "/projects",
        headers=admin_headers,
        json={
            "tender_key": "PRJ-2026-0001",
            "tender_name": "某某枢纽工程",
            "builder_name": "中建示例",
            "risk_level": "high",
            "supervision_level": "priority",
        },
    )
    assert r.status_code == 201
    pid = r.json()["id"]
    assert r.json()["inspection_count"] == 0

    # 重复创建 409
    dup = client.post("/projects", headers=admin_headers, json={
        "tender_key": "PRJ-2026-0001", "tender_name": "x"
    })
    assert dup.status_code == 409

    # 列表 + counts_by_risk
    lst = client.get("/projects?risk=high", headers=admin_headers).json()
    assert lst["total"] >= 1
    assert lst["counts_by_risk"]["high"] >= 1


def test_project_update_and_inspection(client: TestClient, admin_headers):
    r = client.post("/projects", headers=admin_headers, json={
        "tender_key": "PRJ-INSP-01", "tender_name": "巡检测试项目"
    })
    pid = r.json()["id"]

    r = client.patch(f"/projects/{pid}", headers=admin_headers, json={"risk_level": "medium", "status": "suspended"})
    assert r.status_code == 200
    assert r.json()["risk_level"] == "medium"
    assert r.json()["status"] == "suspended"

    r = client.post(f"/projects/{pid}/inspection", headers=admin_headers, json={"note": "首次巡检：材料合格"})
    assert r.status_code == 200
    assert r.json()["inspection_count"] == 1
    assert r.json()["last_inspection_note"] == "首次巡检：材料合格"
    assert r.json()["last_inspection_at"]

    r = client.post(f"/projects/{pid}/inspection", headers=admin_headers, json={"note": "复检：通过"})
    assert r.json()["inspection_count"] == 2


def test_project_permission(client: TestClient, admin_headers):
    # guest 无 project:read
    client.post("/users", headers=admin_headers, json={"email": "g@example.com", "password": "guest1234", "role_id": 5})
    login = client.post("/auth/login", json={"email": "g@example.com", "password": "guest1234"})
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/projects", headers=h).status_code == 403
