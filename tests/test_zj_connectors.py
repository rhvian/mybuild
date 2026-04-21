"""ZJ (浙江省住建厅公开平台) connector 单元测试 — 不依赖真实 HTTP。"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from collector.connectors import (
    ZjJzscEnterpriseConnector,
    ZjJzscPersonnelConnector,
)
from collector.models import SourceDefinition


@pytest.fixture
def zj_source_enterprise() -> SourceDefinition:
    return SourceDefinition(
        source_id="zj_jzsc_enterprise_live",
        name="浙江住建公开平台-企业列表",
        source_type="zj_jzsc_enterprise_live",
        source_level="A",
        base_url="https://jzsc.jst.zj.gov.cn",
        province_code="330000",
        city_code="330100",
        enabled=True,
    )


@pytest.fixture
def zj_source_personnel() -> SourceDefinition:
    return SourceDefinition(
        source_id="zj_jzsc_personnel_live",
        name="浙江住建公开平台-人员列表",
        source_type="zj_jzsc_personnel_live",
        source_level="B",
        base_url="https://jzsc.jst.zj.gov.cn",
        province_code="330000",
        city_code="330100",
        enabled=True,
    )


# ---------- _map_rows：核心字段抽取（纯函数测试）----------

def test_enterprise_map_rows_extracts_core_fields(zj_source_enterprise):
    c = ZjJzscEnterpriseConnector(zj_source_enterprise)
    rows = [
        {
            "corpname": "杭州红润物流有限公司",
            "corpcode1": "91330110MA2HYEAK7K",
            "scucode1": "91330110MA2HYEAK7K",
            "legalmanname": "张三",
            "city": "杭州市",
            "county": "余杭区",
            "opiniondatetime1": 1776060000000,
            "opiniondatetime": "2026-04-13",
            "corpcode": "ENCRYPTED_TOKEN_1",
            "scucode": "ENCRYPTED_TOKEN_1",
        }
    ]
    records = c._map_rows(rows, source_url="https://x/EnterpriseInfo/enterpriseInfo")
    assert len(records) == 1
    r = records[0]
    assert r.record_type == "enterprise"
    assert r.source_id == "zj_jzsc_enterprise_live"
    assert r.province_code == "330000"
    p = r.payload
    assert p["name"] == "杭州红润物流有限公司"
    assert p["uscc"] == "91330110MA2HYEAK7K"
    assert p["legal_person"] == "张三"
    assert p["corpcode_encrypted"] == "ENCRYPTED_TOKEN_1"
    assert p["source_business_type"] == "zj_jzsc_enterprise_list"
    # city_name 应包含省和区县
    assert "杭州市" in r.city_name and "余杭区" in r.city_name


def test_enterprise_map_rows_handles_missing_fields(zj_source_enterprise):
    """部分字段缺失（null/empty）时不应抛异常，project_code 有兜底。"""
    c = ZjJzscEnterpriseConnector(zj_source_enterprise)
    rows = [
        {"corpname": "", "scucode1": "", "corpcode1": "", "legalmanname": ""},
    ]
    records = c._map_rows(rows, source_url="u")
    assert len(records) == 1
    # project_code 应 fallback 到 ZJ-CORP-{idx}
    assert records[0].payload["project_code"] == "ZJ-CORP-1"


def test_personnel_map_rows_extracts_core_fields(zj_source_personnel):
    c = ZjJzscPersonnelConnector(zj_source_personnel)
    rows = [
        {
            "personname": "麻钰锋",
            "scucode1": "91331122692389829N",
            "corpname": "浙江磊众工程管理有限公司",
            "certnum": "浙2332008202310695",
            "idcard1": "3325************17",
            "specialtytypename": "注册建造师（二级）",
            "zhuanye": "市政公用工程",
            "edulevelname": "本科",
            "awarddate": 1262880000000,
            "corpcode": "ENC_CORP_KEY",
        }
    ]
    records = c._map_rows(rows, source_url="u")
    assert len(records) == 1
    p = records[0].payload
    assert p["name"] == "麻钰锋"
    assert p["register_no"] == "浙2332008202310695"
    assert p["register_type"] == "注册建造师（二级）"
    assert p["major"] == "市政公用工程"
    assert p["edu_level"] == "本科"
    assert p["person_id_no_masked"] == "3325************17"
    assert p["register_corp_name"] == "浙江磊众工程管理有限公司"
    assert p["source_business_type"] == "zj_jzsc_personnel_list"


# ---------- fetch：用 mock httpx.Client 验分页停机逻辑 ----------

class _FakeResponse:
    def __init__(self, status_code: int, json_data: Dict[str, Any]):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """模拟 httpx.Client；按预置队列返回 response。"""

    def __init__(self, responses: List[_FakeResponse]):
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def post(self, url, json=None, **kw):
        self.calls.append({"url": url, "body": json})
        if not self._responses:
            raise RuntimeError("no more fake responses")
        return self._responses.pop(0)


def _patch_httpx_client_with(fake: _FakeClient):
    """patch collector.connectors 模块里的 httpx.Client。"""
    import collector.connectors as mod
    return patch.object(mod.httpx, "Client", return_value=fake)


def test_fetch_stops_when_server_pageCount_reached(zj_source_enterprise, monkeypatch):
    """响应里有 pager.pageCount，应以此为主止停条件。"""
    monkeypatch.delenv("MYBUILD_ZJ_CITY_SHARD", raising=False)
    monkeypatch.setenv("MYBUILD_ZJ_PAGE_SIZE", "10")
    monkeypatch.setenv("MYBUILD_ZJ_MAX_PAGES", "999")
    monkeypatch.setenv("MYBUILD_ZJ_API_ROOT", "https://h/pub")

    page_rows = [{"corpname": f"c{i}", "corpcode1": f"u{i}"} for i in range(10)]
    responses = [
        _FakeResponse(200, {"code": 0, "data": {"list": page_rows, "pager": {"pageCount": 2}}}),
        _FakeResponse(200, {"code": 0, "data": {"list": page_rows, "pager": {"pageCount": 2}}}),
    ]
    fake = _FakeClient(responses)
    with _patch_httpx_client_with(fake):
        c = ZjJzscEnterpriseConnector(zj_source_enterprise)
        records = c.fetch()
    # 应恰好拉 2 页（20 条），第 3 页不应发起
    assert len(records) == 20
    assert len(fake.calls) == 2


def test_fetch_stops_on_short_page(zj_source_enterprise, monkeypatch):
    """无 pageCount 时，短页（len(list) < page_size）应止停。"""
    monkeypatch.delenv("MYBUILD_ZJ_CITY_SHARD", raising=False)
    monkeypatch.setenv("MYBUILD_ZJ_PAGE_SIZE", "10")
    monkeypatch.setenv("MYBUILD_ZJ_MAX_PAGES", "999")
    monkeypatch.setenv("MYBUILD_ZJ_API_ROOT", "https://h/pub")

    page1 = [{"corpname": f"c{i}", "corpcode1": f"u{i}"} for i in range(10)]
    page2_short = [{"corpname": "last", "corpcode1": "u_last"}]
    responses = [
        _FakeResponse(200, {"code": 0, "data": {"list": page1}}),
        _FakeResponse(200, {"code": 0, "data": {"list": page2_short}}),
    ]
    fake = _FakeClient(responses)
    with _patch_httpx_client_with(fake):
        c = ZjJzscEnterpriseConnector(zj_source_enterprise)
        records = c.fetch()
    assert len(records) == 11
    assert len(fake.calls) == 2


def test_fetch_code_204_treated_as_empty(zj_source_enterprise, monkeypatch):
    """服务端返 code=204（该地市无数据）应视为空页退出，不抛异常。"""
    monkeypatch.delenv("MYBUILD_ZJ_CITY_SHARD", raising=False)
    monkeypatch.setenv("MYBUILD_ZJ_PAGE_SIZE", "10")
    monkeypatch.setenv("MYBUILD_ZJ_MAX_PAGES", "3")
    monkeypatch.setenv("MYBUILD_ZJ_API_ROOT", "https://h/pub")

    fake = _FakeClient([_FakeResponse(200, {"code": 204, "msg": "no data"})])
    with _patch_httpx_client_with(fake):
        c = ZjJzscEnterpriseConnector(zj_source_enterprise)
        records = c.fetch()
    assert records == []
    assert len(fake.calls) == 1


def test_fetch_nonzero_code_raises(zj_source_enterprise, monkeypatch):
    """除 0/204 外的 code 视为故障，应抛 RuntimeError。"""
    monkeypatch.delenv("MYBUILD_ZJ_CITY_SHARD", raising=False)
    monkeypatch.setenv("MYBUILD_ZJ_API_ROOT", "https://h/pub")

    fake = _FakeClient([_FakeResponse(200, {"code": 500, "msg": "server_error"})])
    with _patch_httpx_client_with(fake):
        c = ZjJzscEnterpriseConnector(zj_source_enterprise)
        with pytest.raises(RuntimeError, match="zj api failed"):
            c.fetch()
