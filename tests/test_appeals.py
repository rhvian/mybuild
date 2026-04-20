"""/appeals 企业认证申诉测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _make_business_user(client: TestClient, admin_headers) -> dict[str, str]:
    client.post(
        "/users",
        headers=admin_headers,
        json={"email": "biz1@example.com", "password": "biz12345", "role_id": 4},  # business
    )
    login = client.post("/auth/login", json={"email": "biz1@example.com", "password": "biz12345"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _make_auditor_user(client: TestClient, admin_headers, email="audit_ap@example.com") -> dict[str, str]:
    client.post("/users", headers=admin_headers, json={"email": email, "password": "audit12345", "role_id": 2})
    login = client.post("/auth/login", json={"email": email, "password": "audit12345"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_appeal_submit_review_approve_flow(client: TestClient, admin_headers):
    biz_h = _make_business_user(client, admin_headers)
    r = client.post(
        "/appeals",
        headers=biz_h,
        json={
            "enterprise_key": "91310000TEST",
            "enterprise_name": "测试建工",
            "category": "credit",
            "title": "对 2026-03 信用评分有异议",
            "detail": "附整改证据",
        },
    )
    assert r.status_code == 201
    aid = r.json()["id"]
    assert r.json()["status"] == "submitted"
    assert r.json()["appellant_user_id"] is not None

    # business 用户可以看自己的
    r = client.get(f"/appeals/{aid}", headers=biz_h)
    assert r.status_code == 200

    # business 没 appeal:review 权限，看列表 403
    assert client.get("/appeals", headers=biz_h).status_code == 403

    # auditor start_review
    audit_h = _make_auditor_user(client, admin_headers)
    r = client.get("/appeals", headers=audit_h).json()
    assert r["total"] >= 1
    r = client.post(f"/appeals/{aid}/review", headers=audit_h, json={"decision": "start_review"})
    assert r.status_code == 200 and r.json()["status"] == "under_review"

    # 不允许 submit → approve 直接跳
    client.post(
        "/appeals",
        headers=biz_h,
        json={"enterprise_key": "k2", "enterprise_name": "n2", "title": "t2"},
    )
    r2 = client.get("/appeals?status=submitted", headers=audit_h).json()
    aid2 = r2["items"][0]["id"]
    bad = client.post(f"/appeals/{aid2}/review", headers=audit_h, json={"decision": "approve"})
    assert bad.status_code == 409

    # approve 正路
    r = client.post(f"/appeals/{aid}/review", headers=audit_h, json={"decision": "approve", "note": "审核通过，撤销处罚"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert r.json()["reviewed_at"]
    assert r.json()["review_note"] == "审核通过，撤销处罚"


def test_appeal_need_more_and_resubmit(client: TestClient, admin_headers):
    biz_h = _make_business_user(client, admin_headers)
    r = client.post("/appeals", headers=biz_h, json={
        "enterprise_key": "kNeedMore", "enterprise_name": "nNeed", "title": "要补材料"
    })
    aid = r.json()["id"]

    audit_h = _make_auditor_user(client, admin_headers, "audit_need@example.com")
    client.post(f"/appeals/{aid}/review", headers=audit_h, json={"decision": "start_review"})
    r = client.post(f"/appeals/{aid}/review", headers=audit_h, json={"decision": "need_more", "note": "请补充发票"})
    assert r.json()["status"] == "need_more"

    # business 重新提交
    r = client.post(f"/appeals/{aid}/resubmit", headers=biz_h, json={
        "enterprise_key": "kNeedMore", "enterprise_name": "nNeed", "title": "要补材料",
        "detail": "补充材料：发票 scan",
        "evidence_url": "https://example.com/ev1.pdf",
    })
    assert r.status_code == 200 and r.json()["status"] == "under_review"
    assert "发票 scan" in r.json()["detail"]


def test_appeal_counts(client: TestClient, admin_headers):
    r = client.get("/appeals", headers=admin_headers).json()
    assert set(r["counts_by_status"].keys()) >= {"submitted", "under_review", "need_more", "approved", "rejected"}
