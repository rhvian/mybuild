"""
A1 增量采集 — cursor 传递与过滤的实证测试。

核心验证：
1. `_parse_enterprise_cursor_id` 各种格式解析正确
2. `_load_company_names_from_db(since_enterprise_id=N)` 只返回 id > N 的企业名
3. 传 None / 0 / 非法值时退化为全量（取最新 limit 条）

这些测试确保 A1 代码路径真实生效，不只是"代码里写了"。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from collector.connectors import (
    _load_company_names_from_db,
    _parse_enterprise_cursor_id,
)


# ---------- _parse_enterprise_cursor_id 单测 ----------

@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("0", None),                       # 0 视为无效
        ("-1", None),                      # 负数视为无效
        ("not_a_number", None),            # 非数字
        ("other_kind:999", None),          # 非 enterprise_id 前缀一律视为无效
        ("123", 123),                      # 纯数字
        ("  456  ", 456),                  # 前后空格
        ("enterprise_id:789", 789),        # 生产格式
        ("enterprise_id:0", None),         # 生产格式但 0
        ("enterprise_id:1024", 1024),
    ],
)
def test_parse_cursor_formats(raw, expected):
    assert _parse_enterprise_cursor_id(raw) == expected


# ---------- _load_company_names_from_db cursor 过滤测试 ----------

@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """构造含 5 个 enterprise 记录的临时 collector.db schema。"""
    db = tmp_path / "collector.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE normalized_entity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            entity_key TEXT,
            entity_type TEXT NOT NULL,
            name TEXT NOT NULL,
            uscc TEXT,
            project_code TEXT,
            city_code TEXT,
            city_name TEXT,
            province_code TEXT,
            score INTEGER,
            risk_level TEXT,
            status TEXT,
            event_date TEXT,
            source_id TEXT,
            source_url TEXT,
            source_level TEXT,
            evidence_hash TEXT,
            raw_payload_json TEXT
        )
        """
    )
    # 插入 5 个企业（id 1-5）+ 2 个 staff 干扰项（应被过滤掉）
    rows = [
        ("enterprise", "阿尔法建设有限公司"),
        ("enterprise", "贝塔工程股份公司"),
        ("enterprise", "伽马市政集团"),
        ("staff", "张三"),                         # 非 enterprise，应忽略
        ("enterprise", "德尔塔建筑"),
        ("enterprise", ""),                         # 空名，应过滤
        ("enterprise", "艾普西隆建工"),
        ("staff", "李四"),
    ]
    for entity_type, name in rows:
        conn.execute(
            "INSERT INTO normalized_entity (entity_type, name) VALUES (?, ?)",
            (entity_type, name),
        )
    conn.commit()
    conn.close()
    return db


def test_load_returns_all_enterprises_when_no_cursor(tmp_db: Path):
    """无 cursor：全量（按 max_id DESC）返回最新的企业名，跳过 staff 和空名。"""
    names = _load_company_names_from_db(limit=100, db_path=tmp_db)
    # 5 个 enterprise（阿尔法/贝塔/伽马/德尔塔/艾普西隆），空名和 staff 被过滤掉
    assert len(names) == 5
    assert set(names) == {"阿尔法建设有限公司", "贝塔工程股份公司", "伽马市政集团", "德尔塔建筑", "艾普西隆建工"}
    assert "张三" not in names
    assert "李四" not in names
    assert "" not in names


def test_load_with_cursor_filters_to_new_only(tmp_db: Path):
    """传 since=3：只返回 id>3 的 enterprise（即 id=5 德尔塔 + id=7 艾普西隆）。"""
    names = _load_company_names_from_db(limit=100, since_enterprise_id=3, db_path=tmp_db)
    assert set(names) == {"德尔塔建筑", "艾普西隆建工"}
    assert "阿尔法建设有限公司" not in names  # id=1 < 3
    assert "贝塔工程股份公司" not in names    # id=2 < 3
    assert "伽马市政集团" not in names         # id=3 == 3 不满足 >


def test_load_with_future_cursor_returns_empty(tmp_db: Path):
    """cursor 超过所有 id：应返回空列表（增量无新企业时的正确行为）。"""
    names = _load_company_names_from_db(limit=100, since_enterprise_id=9999, db_path=tmp_db)
    assert names == []


def test_load_with_zero_cursor_behaves_like_full(tmp_db: Path):
    """since=0：SQL 里 `id > 0` 等价于全表，但走的是 cursor 分支（ORDER BY ASC）。"""
    names = _load_company_names_from_db(limit=100, since_enterprise_id=0, db_path=tmp_db)
    assert len(names) == 5  # 同无 cursor 的结果条数


def test_load_respects_limit(tmp_db: Path):
    """limit=2 只应返回 2 条。"""
    names = _load_company_names_from_db(limit=2, db_path=tmp_db)
    assert len(names) == 2


def test_load_returns_empty_when_db_missing(tmp_path: Path):
    """DB 文件不存在时应返回空列表，不抛异常。"""
    missing = tmp_path / "nonexistent.db"
    assert _load_company_names_from_db(limit=10, db_path=missing) == []


def test_incremental_path_e2e(tmp_db: Path):
    """
    端到端演示 A1 增量语义：
    1. 首次调用（无 cursor）拿到全部 5 个企业
    2. 记录当前 max_id
    3. 第二次调用传该 max_id，应返回空（无新增）
    4. 插入 1 条新 enterprise → 第三次传原 max_id 应只返回这 1 个
    """
    # Step 1: 首次全量
    first = _load_company_names_from_db(limit=100, db_path=tmp_db)
    assert len(first) == 5

    # Step 2: 取当前 max_id
    conn = sqlite3.connect(tmp_db)
    max_id = conn.execute(
        "SELECT MAX(id) FROM normalized_entity WHERE entity_type='enterprise'"
    ).fetchone()[0]
    assert max_id == 7

    # Step 3: 第二次用该 cursor，应无新增
    second = _load_company_names_from_db(limit=100, since_enterprise_id=max_id, db_path=tmp_db)
    assert second == []

    # Step 4: 插入 1 条新企业
    conn.execute(
        "INSERT INTO normalized_entity (entity_type, name) VALUES ('enterprise', '泽塔科技')"
    )
    conn.commit()
    conn.close()

    # Step 5: 第三次仍传旧 cursor，应只返回新增的泽塔科技
    third = _load_company_names_from_db(limit=100, since_enterprise_id=max_id, db_path=tmp_db)
    assert third == ["泽塔科技"]
