"""/alerts 预警处置业务流测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_requires_permission(client: TestClient):
    assert client.get("/alerts").status_code == 401


def test_admin_can_create_and_list_alert(client: TestClient, admin_headers):
    r = client.post(
        "/alerts",
        headers=admin_headers,
        json={
            "category": "quality",
            "severity": "high",
            "title": "某企业质量抽检不合格",
            "detail": "2026-04-18 抽检批次 B-0318，钢筋强度未达标。",
            "entity_type": "enterprise",
            "entity_key": "91310100MA7EXAMPLE",
            "entity_name": "某某市政工程有限公司",
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "open"
    assert data["severity"] == "high"
    assert data["assignee_id"] is None
    assert len(data["actions"]) == 1
    assert data["actions"][0]["action"] == "create"

    lst = client.get("/alerts", headers=admin_headers).json()
    assert lst["total"] >= 1
    assert lst["counts_by_status"]["open"] >= 1


def test_alert_full_lifecycle(client: TestClient, admin_headers):
    # create
    r = client.post(
        "/alerts",
        headers=admin_headers,
        json={"category": "risk", "severity": "medium", "title": "测试工单"},
    )
    aid = r.json()["id"]

    # ack
    r = client.post(f"/alerts/{aid}/action", headers=admin_headers, json={"action": "ack", "note": "受理中"})
    assert r.status_code == 200
    assert r.json()["status"] == "ack"
    assert r.json()["assignee_id"] is not None

    # invalid: ack again
    r = client.post(f"/alerts/{aid}/action", headers=admin_headers, json={"action": "ack"})
    assert r.status_code == 409

    # comment (不改状态)
    r = client.post(f"/alerts/{aid}/action", headers=admin_headers, json={"action": "comment", "note": "已联系企业"})
    assert r.status_code == 200
    assert r.json()["status"] == "ack"

    # resolve
    r = client.post(f"/alerts/{aid}/action", headers=admin_headers, json={"action": "resolve", "note": "整改完成"})
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"
    assert r.json()["resolved_at"] is not None
    assert r.json()["resolution_note"] == "整改完成"

    # reopen
    r = client.post(f"/alerts/{aid}/action", headers=admin_headers, json={"action": "reopen", "note": "复发"})
    assert r.status_code == 200
    assert r.json()["status"] == "open"

    # 详情含 actions 时间线
    detail = client.get(f"/alerts/{aid}", headers=admin_headers).json()
    # create + ack + comment + resolve + reopen = 5
    assert len(detail["actions"]) == 5


def test_alert_filters(client: TestClient, admin_headers):
    # 创建 3 个不同严重等级
    for sev in ("high", "medium", "low"):
        client.post(
            "/alerts",
            headers=admin_headers,
            json={"category": "quality", "severity": sev, "title": f"严重度 {sev}"},
        )

    high = client.get("/alerts?severity=high", headers=admin_headers).json()
    assert high["total"] >= 1
    assert all(a["severity"] == "high" for a in high["items"])

    # 搜索标题
    matched = client.get("/alerts?q=严重度", headers=admin_headers).json()
    assert matched["total"] >= 3


def test_rbac_guest_cannot_list(client: TestClient, admin_headers):
    # 创建一个 guest 用户
    client.post(
        "/users",
        headers=admin_headers,
        json={"email": "guest1@example.com", "password": "guest1234", "role_id": 5},  # guest
    )
    login = client.post("/auth/login", json={"email": "guest1@example.com", "password": "guest1234"})
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = client.get("/alerts", headers=h)
    assert r.status_code == 403
