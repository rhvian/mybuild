from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from typing import Callable, Dict, Iterable, List, Sequence, Type

import httpx
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from playwright.async_api import async_playwright

from .models import RawRecord, SourceDefinition, SourceFailure


PROVINCE_CODE_BY_SOURCE_PREFIX: Dict[str, str] = {
    "prov_01": "120000",  # 天津
    "prov_02": "130000",  # 河北
    "prov_03": "140000",  # 山西
    "prov_04": "150000",  # 内蒙古
    "prov_05": "210000",  # 辽宁
    "prov_06": "220000",  # 吉林
    "prov_07": "230000",  # 黑龙江
    "prov_08": "310000",  # 上海
    "prov_09": "320000",  # 江苏
    "prov_10": "330000",  # 浙江
    "prov_11": "340000",  # 安徽
    "prov_12": "350000",  # 福建
    "prov_13": "360000",  # 江西
    "prov_14": "370000",  # 山东
    "prov_15": "410000",  # 河南
    "prov_16": "420000",  # 湖北
    "prov_17": "430000",  # 湖南
    "prov_18": "440000",  # 广东
    "prov_19": "450000",  # 广西
    "prov_20": "460000",  # 海南
    "prov_21": "500000",  # 重庆
    "prov_22": "510000",  # 四川
    "prov_23": "520000",  # 贵州
    "prov_24": "530000",  # 云南
    "prov_25": "540000",  # 西藏
    "prov_26": "610000",  # 陕西
    "prov_27": "620000",  # 甘肃
    "prov_28": "630000",  # 青海
    "prov_29": "640000",  # 宁夏
    "prov_30": "650000",  # 新疆
}


class BaseConnector(ABC):
    source_type: str

    def __init__(self, source: SourceDefinition, cursor_value: str | None = None):
        self.source = source
        self.cursor_value = cursor_value

    @abstractmethod
    def fetch(self) -> Sequence[RawRecord]:
        raise NotImplementedError


class JzscLiveConnectorBase(BaseConnector):
    page_path: str
    api_path: str
    record_type: str
    entity_type: str

    decrypt_key = b"Dt8j9wGw%6HbxfFn"
    decrypt_iv = b"0123456789ABCDEF"
    page_size = 15
    # JZSC 反爬机制：无筛选时 API 在第 31 页后返回 "服务器繁忙" (code 401)。
    # 单次查询硬上限约 465 条；突破方法是按地区/资质等维度分批查询。
    max_pages = 35
    # 地区筛选参数名（None 表示不按地区拆分）
    region_param: str | None = None
    # 要遍历的地区代码列表（None 表示不拆分）
    region_codes: List[str] | None = None
    # 连续两批 API 失败时退出循环，避免持续 401 浪费
    max_consecutive_failures = 2
    # 去重 key 字段名（同一实体多批查询可能重复）
    dedup_field: str | None = None
    # 每 N 批主动刷 browser session（默认 8，对 ry_qymc 细粒度查询可调大）
    browser_refresh_every: int = 8
    # 仅允许 batch 模式；当 batch 为空时直接返回空，不回退到“无筛选全量抓取”。
    use_batched_only: bool = False

    def fetch(self) -> Sequence[RawRecord]:
        # 按地区筛选批量采集（在一个浏览器会话内遍历所有 region），避免每省重启 playwright 的高开销。
        batches = self._prepare_batches()
        if batches:
            rows = _collect_batched_sync(
                base_url=self.source.base_url,
                page_path=self.page_path,
                api_path=self.api_path,
                page_size=self.page_size,
                max_pages_per_batch=self.max_pages,
                decrypt_key=self.decrypt_key,
                decrypt_iv=self.decrypt_iv,
                batches=batches,
                dedup_field=self.dedup_field,
                max_consecutive_empty_batches=self.max_consecutive_failures,
                progress_tag=self.source.source_id,
            )
            return self._map_rows(rows)
        if self.use_batched_only:
            return []
        rows = _collect_pages_sync(
            base_url=self.source.base_url,
            page_path=self.page_path,
            api_path=self.api_path,
            page_size=self.page_size,
            max_pages=self.max_pages,
            decrypt_key=self.decrypt_key,
            decrypt_iv=self.decrypt_iv,
        )
        return self._map_rows(rows)

    def iter_fetch_batches(
        self,
        on_batch: "Callable[[str, List[RawRecord]], None]",
    ) -> None:
        """
        流式采集：每完成一个 batch 就调用 on_batch(batch_label, records)。
        调用方（pipeline）可在 callback 中立即 insert+commit，实现 per-batch 持久化。
        对于不支持 region 拆分的连接器，整个结果作为单个 batch 'all' 调用一次 on_batch。
        """
        batches = self._prepare_batches()
        if batches:
            def _raw_batch_cb(batch_label: str, raw_rows: List[Dict]) -> None:
                records = self._map_rows(raw_rows)
                if records:
                    on_batch(batch_label, list(records))

            _collect_batched_sync(
                base_url=self.source.base_url,
                page_path=self.page_path,
                api_path=self.api_path,
                page_size=self.page_size,
                max_pages_per_batch=self.max_pages,
                decrypt_key=self.decrypt_key,
                decrypt_iv=self.decrypt_iv,
                batches=batches,
                dedup_field=self.dedup_field,
                max_consecutive_empty_batches=self.max_consecutive_failures,
                progress_tag=self.source.source_id,
                on_batch=_raw_batch_cb,
            )
            return
        if self.use_batched_only:
            return
        # 无 batch 拆分 —— 整包返回作为单 batch
        rows = _collect_pages_sync(
            base_url=self.source.base_url,
            page_path=self.page_path,
            api_path=self.api_path,
            page_size=self.page_size,
            max_pages=self.max_pages,
            decrypt_key=self.decrypt_key,
            decrypt_iv=self.decrypt_iv,
        )
        records = self._map_rows(rows)
        if records:
            on_batch("all", list(records))

    def _prepare_batches(self) -> List[Dict[str, str]]:
        """
        生成本次采集的筛选批次列表，每个元素是一组 query 参数。
        默认基于 region_param / region_codes（即静态的地区循环）。
        子类可 override 以动态生成（例如从 DB 读企业名清单）。
        """
        if self.region_param and self.region_codes:
            return [{self.region_param: code} for code in self.region_codes]
        return []

    def _map_rows(self, rows: List[Dict]) -> List[RawRecord]:
        raise NotImplementedError


class JzscCompanyLiveConnector(JzscLiveConnectorBase):
    source_type = "jzsc_company_live"
    page_path = "/data/company"
    api_path = "/APi/webApi/dataservice/query/comp/list"
    record_type = "enterprise"
    entity_type = "enterprise"
    # 按省份筛选突破 500 条硬上限。全国 31 省 × 465 ≈ 14,415 条/次。
    region_param = "qy_region"
    region_codes = [
        "110000", "120000", "130000", "140000", "150000",  # 京津冀晋蒙
        "210000", "220000", "230000",                       # 辽吉黑
        "310000", "320000", "330000", "340000", "350000",   # 沪苏浙皖闽
        "360000", "370000",                                 # 赣鲁
        "410000", "420000", "430000",                       # 豫鄂湘
        "440000", "450000", "460000",                       # 粤桂琼
        "500000", "510000", "520000", "530000",             # 渝川黔滇
        "540000",                                           # 藏
        "610000", "620000", "630000", "640000", "650000",   # 陕甘青宁新
    ]
    dedup_field = "QY_ID"

    def _map_rows(self, rows: List[Dict]) -> List[RawRecord]:
        records: List[RawRecord] = []
        for idx, row in enumerate(rows, start=1):
            uscc = str(row.get("QY_ORG_CODE", "")).strip()
            name = str(row.get("QY_NAME", "")).strip()
            legal = str(row.get("QY_FR_NAME", "")).strip()
            region_name = str(row.get("QY_REGION_NAME", "")).strip()
            region_code = str(row.get("QY_REGION", "")).strip()
            qy_id = str(row.get("QY_ID", "")).strip()
            collect_time = row.get("COLLECT_TIME")
            old_code = str(row.get("OLD_CODE", "")).strip()

            city_code = _to_city_code(region_code, fallback=self.source.city_code or "110000")
            province_code = _to_province_code(city_code)
            event_date = _epoch_ms_to_date(collect_time)

            records.append(
                RawRecord(
                    source_id=self.source.source_id,
                    source_name=self.source.name,
                    source_level=self.source.source_level,
                    source_url=f"{self.source.base_url}{self.api_path}",
                    record_type=self.record_type,
                    province_code=province_code,
                    city_code=city_code,
                    city_name=region_name or "未知地区",
                    payload={
                        "entity_type": self.entity_type,
                        "name": name,
                        "uscc": uscc,
                        "project_code": qy_id or f"QY-{idx}",
                        "score": 80,
                        "status": "ACTIVE",
                        "event_date": event_date,
                        "legal_person": legal,
                        "old_code": old_code,
                        "source_business_type": "jzsc_company_list",
                    },
                )
            )
        return records


class JzscStaffLiveConnector(JzscLiveConnectorBase):
    source_type = "jzsc_staff_live"
    page_path = "/data/person"
    api_path = "/APi/webApi/dataservice/query/staff/list"
    record_type = "staff"
    entity_type = "staff"

    def _map_rows(self, rows: List[Dict]) -> List[RawRecord]:
        records: List[RawRecord] = []
        for idx, row in enumerate(rows, start=1):
            name = str(row.get("RY_NAME", "")).strip()
            masked_id = str(row.get("RY_CARDNO", "")).strip()
            reg_type = str(row.get("REG_TYPE_NAME", "")).strip()
            reg_no = str(row.get("REG_SEAL_CODE", "")).strip()
            reg_qy_name = str(row.get("REG_QYMC", "")).strip()
            reg_qy_id = str(row.get("REG_QYID", "")).strip()
            reg_type_code = str(row.get("REG_TYPE", "")).strip()
            reg_sdate = row.get("REG_SDATE")
            staff_id = str(row.get("RY_ID", "")).strip()

            records.append(
                RawRecord(
                    source_id=self.source.source_id,
                    source_name=self.source.name,
                    source_level=self.source.source_level,
                    source_url=f"{self.source.base_url}{self.api_path}",
                    record_type=self.record_type,
                    province_code=self.source.province_code or "000000",
                    city_code=self.source.city_code or "110000",
                    city_name="全国",
                    payload={
                        "entity_type": self.entity_type,
                        "name": name,
                        "uscc": "",
                        "project_code": staff_id or reg_no or f"STAFF-{idx}",
                        "score": 80,
                        "status": "ACTIVE",
                        "event_date": _epoch_ms_to_date(reg_sdate),
                        "person_id_no_masked": masked_id,
                        "register_type": reg_type,
                        "register_no": reg_no,
                        "register_corp_name": reg_qy_name,
                        "register_corp_id": reg_qy_id,
                        "register_type_code": reg_type_code,
                        "source_business_type": "jzsc_staff_list",
                    },
                )
            )
        return records


class JzscProjectLiveConnector(JzscLiveConnectorBase):
    source_type = "jzsc_project_live"
    page_path = "/data/project"
    api_path = "/APi/webApi/dataservice/query/project/list"
    record_type = "tender"
    entity_type = "tender"

    def _map_rows(self, rows: List[Dict]) -> List[RawRecord]:
        records: List[RawRecord] = []
        for idx, row in enumerate(rows, start=1):
            project_name = str(row.get("PRJNAME", "")).strip()
            project_code = str(row.get("PRJNUM", "")).strip()
            project_id = str(row.get("ID", "")).strip()
            project_type = str(row.get("PRJTYPENUM", "")).strip()
            builder = str(row.get("BUILDCORPNAME", "")).strip()
            data_level = str(row.get("DATALEVEL", "")).strip()
            is_fake = row.get("IS_FAKE")
            collect_time = row.get("LASTUPDATEDATE")

            city_code = self.source.city_code or "110000"
            province_code = _to_province_code(city_code)
            event_date = _epoch_ms_to_date(collect_time)

            records.append(
                RawRecord(
                    source_id=self.source.source_id,
                    source_name=self.source.name,
                    source_level=self.source.source_level,
                    source_url=f"{self.source.base_url}{self.api_path}",
                    record_type=self.record_type,
                    province_code=province_code,
                    city_code=city_code,
                    city_name="全国",
                    payload={
                        "entity_type": self.entity_type,
                        "name": project_name,
                        "uscc": "",
                        "project_code": project_code or project_id or f"PRJ-{idx}",
                        "score": 80,
                        "status": "OPEN",
                        "event_date": event_date,
                        "project_type": project_type,
                        "builder_name": builder,
                        "data_level": data_level,
                        "is_fake": is_fake,
                        "source_business_type": "jzsc_project_list",
                    },
                )
            )
        return records


def _parse_enterprise_cursor_id(cursor_value: str | None) -> int | None:
    if not cursor_value:
        return None
    raw = str(cursor_value).strip()
    if not raw:
        return None
    if raw.startswith("enterprise_id:"):
        raw = raw.split(":", 1)[1]
    try:
        val = int(raw)
        return val if val > 0 else None
    except Exception:  # noqa: BLE001
        return None


def _load_company_names_from_db(
    limit: int = 20000,
    since_enterprise_id: int | None = None,
) -> List[str]:
    """
    从 collector.db 读取已采集企业的 QY_NAME，用于后续按企业反查人员 / 项目。
    只返回最新一次 enterprise run 的企业名，避免重复。
    """
    import sqlite3
    from pathlib import Path

    db_path = Path(__file__).resolve().parent / "data" / "collector.db"
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        if since_enterprise_id is not None:
            rows = conn.execute(
                """
                SELECT name, MAX(id) AS max_id
                FROM normalized_entity
                WHERE entity_type='enterprise'
                  AND name != ''
                  AND id > ?
                GROUP BY name
                ORDER BY max_id ASC
                LIMIT ?
                """,
                (since_enterprise_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT name, MAX(id) AS max_id
                FROM normalized_entity
                WHERE entity_type='enterprise'
                  AND name != ''
                GROUP BY name
                ORDER BY max_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows if r[0]]


class JzscStaffByCompanyConnector(JzscLiveConnectorBase):
    """
    按企业名反查人员：staff/list?ry_qymc=<企业全名>
    绕过 staff API 500 条累计硬限。每家企业拿到 0-465 条注册人员。
    """
    source_type = "jzsc_staff_by_company_live"
    page_path = "/data/person"
    api_path = "/APi/webApi/dataservice/query/staff/list"
    record_type = "staff"
    entity_type = "staff"
    max_pages = 35  # 每家企业几乎没到 31 页（大企业才几十上百人），留够余量
    dedup_field = "RY_ID"
    max_consecutive_failures = 10  # 大量企业查不到人员是正常的，不能过早中止
    use_batched_only = True
    # 每家企业独立查询（不共用 session，但同一 browser）
    # browser_refresh_every 由 _collect_batched 的默认 8 控制

    def _prepare_batches(self) -> List[Dict[str, str]]:
        # 从 DB 拿已采企业名，每家企业一次查询
        cursor_id = _parse_enterprise_cursor_id(self.cursor_value)
        names = _load_company_names_from_db(
            limit=50000,
            since_enterprise_id=cursor_id,
        )
        return [{"ry_qymc": name} for name in names]

    def _map_rows(self, rows: List[Dict]) -> List[RawRecord]:
        records: List[RawRecord] = []
        for idx, row in enumerate(rows, start=1):
            name = str(row.get("RY_NAME", "")).strip()
            masked_id = str(row.get("RY_CARDNO", "")).strip()
            reg_type = str(row.get("REG_TYPE_NAME", "")).strip()
            reg_no = str(row.get("REG_SEAL_CODE", "")).strip()
            reg_qy_name = str(row.get("REG_QYMC", "")).strip()
            reg_qy_id = str(row.get("REG_QYID", "")).strip()
            reg_type_code = str(row.get("REG_TYPE", "")).strip()
            reg_sdate = row.get("REG_SDATE")
            staff_id = str(row.get("RY_ID", "")).strip()

            records.append(
                RawRecord(
                    source_id=self.source.source_id,
                    source_name=self.source.name,
                    source_level=self.source.source_level,
                    source_url=f"{self.source.base_url}{self.api_path}",
                    record_type=self.record_type,
                    province_code=self.source.province_code or "000000",
                    city_code=self.source.city_code or "110000",
                    city_name="全国",
                    payload={
                        "entity_type": self.entity_type,
                        "name": name,
                        "uscc": "",
                        "project_code": staff_id or reg_no or f"STAFF-{idx}",
                        "score": 80,
                        "status": "ACTIVE",
                        "event_date": _epoch_ms_to_date(reg_sdate),
                        "person_id_no_masked": masked_id,
                        "register_type": reg_type,
                        "register_no": reg_no,
                        "register_corp_name": reg_qy_name,
                        "register_corp_id": reg_qy_id,
                        "register_type_code": reg_type_code,
                        "source_business_type": "jzsc_staff_by_company",
                    },
                )
            )
        return records


class JzscProjectByCompanyConnector(JzscLiveConnectorBase):
    """
    按承建单位反查项目：project/list?buildCorpName=<企业全名>
    绕过 project API 500 条累计硬限。每家企业拿到其作为建设单位的所有项目。
    """
    source_type = "jzsc_project_by_company_live"
    page_path = "/data/project"
    api_path = "/APi/webApi/dataservice/query/project/list"
    record_type = "tender"
    entity_type = "tender"
    max_pages = 35
    dedup_field = "ID"
    max_consecutive_failures = 10
    use_batched_only = True

    def _prepare_batches(self) -> List[Dict[str, str]]:
        cursor_id = _parse_enterprise_cursor_id(self.cursor_value)
        names = _load_company_names_from_db(
            limit=50000,
            since_enterprise_id=cursor_id,
        )
        return [{"buildCorpName": name} for name in names]

    def _map_rows(self, rows: List[Dict]) -> List[RawRecord]:
        records: List[RawRecord] = []
        for idx, row in enumerate(rows, start=1):
            project_name = str(row.get("PRJNAME", "")).strip()
            project_code = str(row.get("PRJNUM", "")).strip()
            project_id = str(row.get("ID", "")).strip()
            project_type = str(row.get("PRJTYPENUM", "")).strip()
            builder = str(row.get("BUILDCORPNAME", "")).strip()
            data_level = str(row.get("DATALEVEL", "")).strip()
            is_fake = row.get("IS_FAKE")
            collect_time = row.get("LASTUPDATEDATE")

            city_code = self.source.city_code or "110000"
            province_code = _to_province_code(city_code)
            event_date = _epoch_ms_to_date(collect_time)

            records.append(
                RawRecord(
                    source_id=self.source.source_id,
                    source_name=self.source.name,
                    source_level=self.source.source_level,
                    source_url=f"{self.source.base_url}{self.api_path}",
                    record_type=self.record_type,
                    province_code=province_code,
                    city_code=city_code,
                    city_name="全国",
                    payload={
                        "entity_type": self.entity_type,
                        "name": project_name,
                        "uscc": "",
                        "project_code": project_code or project_id or f"PRJ-{idx}",
                        "score": 80,
                        "status": "OPEN",
                        "event_date": event_date,
                        "project_type": project_type,
                        "builder_name": builder,
                        "data_level": data_level,
                        "is_fake": is_fake,
                        "source_business_type": "jzsc_project_by_company",
                    },
                )
            )
        return records


class ZjJzscOpenApiConnectorBase(BaseConnector):
    """
    浙江省住建厅公开平台（jzsc.jst.zj.gov.cn）明文接口连接器基类。

    接口特征（来自 HAR）：
    - POST /publishserver/<token1>/<token2>/<Module>/<Action>
    - 响应结构：{code: 0, data: {list: [...]}, ...}
    """

    api_module: str
    api_action: str
    record_type: str
    entity_type: str
    query_template: Dict[str, str]

    page_size = 100
    # Safety cap only. Real stop condition uses response data.pager.pageCount.
    max_pages = 5000
    timeout_seconds = 25
    # 支持两种配置方式：
    # 1) base_url = "https://jzsc.jst.zj.gov.cn"（自动补全默认 publishserver 前缀）
    # 2) base_url = "https://jzsc.jst.zj.gov.cn/publishserver/.../..."
    default_publish_prefix = "/publishserver/OTMjYOMMIukelnoVsiEji/OTMpyrr"

    def _build_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://jzsc.jst.zj.gov.cn",
            "Referer": "https://jzsc.jst.zj.gov.cn/PublicWeb/index.html",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }

    def fetch(self) -> Sequence[RawRecord]:
        page_size = int(os.getenv("MYBUILD_ZJ_PAGE_SIZE", str(self.page_size)))
        max_pages = int(os.getenv("MYBUILD_ZJ_MAX_PAGES", str(self.max_pages)))

        forced_api_root = os.getenv("MYBUILD_ZJ_API_ROOT", "").strip()
        base = self.source.base_url.rstrip("/")
        if forced_api_root:
            api_root = forced_api_root.rstrip("/")
        elif "/publishserver/" in base:
            api_root = base
        else:
            api_root = _discover_zj_api_root(base_url=base) or f"{base}{self.default_publish_prefix}"
        headers = self._build_headers()

        city_batches = self._build_city_batches(api_root=api_root, headers=headers)
        if city_batches:
            # 按地市分片抓取，降低单路限流风险
            all_rows: List[Dict] = []
            total_batches = len(city_batches)
            for i, batch in enumerate(city_batches, start=1):
                batch_query = dict(self.query_template)
                batch_query.update(batch)
                batch_rows, api_root = self._fetch_rows_for_query(
                    api_root=api_root,
                    headers=headers,
                    page_size=page_size,
                    max_pages=max_pages,
                    query=batch_query,
                )
                if batch_rows:
                    all_rows.extend(batch_rows)
                print(
                    f"[zj {self.source.source_id}] city batch {i}/{total_batches} "
                    f"{batch.get('City', '-')}: rows={len(batch_rows)}"
                )
            final_source_url = f"{api_root}/{self.api_module}/{self.api_action}"
            return self._map_rows(all_rows, source_url=final_source_url)

        rows, api_root = self._fetch_rows_for_query(
            api_root=api_root,
            headers=headers,
            page_size=page_size,
            max_pages=max_pages,
            query=dict(self.query_template),
        )
        final_source_url = f"{api_root}/{self.api_module}/{self.api_action}"
        return self._map_rows(rows, source_url=final_source_url)

    def _fetch_rows_for_query(
        self,
        api_root: str,
        headers: Dict[str, str],
        page_size: int,
        max_pages: int,
        query: Dict[str, str],
    ) -> tuple[List[Dict], str]:
        rows: List[Dict] = []
        with httpx.Client(timeout=self.timeout_seconds, headers=headers, follow_redirects=True) as client:
            page_count_from_server: int | None = None
            for page in range(1, max_pages + 1):
                payload = dict(query)
                payload["pageIndex"] = page
                payload["pageSize"] = page_size
                # 浙江站 publishserver 前缀会变化；遇到 404/405 时动态重探测并重试当前页。
                resp = None
                current_api_root = api_root
                for attempt in range(1, 4):
                    url = f"{current_api_root}/{self.api_module}/{self.api_action}"
                    resp = client.post(url, json=payload)
                    if resp.status_code not in (404, 405):
                        break
                    discovered = _discover_zj_api_root(base_url=self.source.base_url.rstrip("/"))
                    if not discovered:
                        break
                    current_api_root = discovered
                    api_root = discovered
                assert resp is not None
                resp.raise_for_status()
                body = resp.json()
                code = int(body.get("code", -1))
                if code == 204:
                    # 分片查询时常见“该地市暂无数据”，视为空页而非失败。
                    break
                if code != 0:
                    msg = body.get("msg") or body.get("exceptionMsg") or "unknown_error"
                    raise RuntimeError(
                        f"zj api failed module={self.api_module} action={self.api_action} "
                        f"code={code} msg={msg}"
                    )
                data = body.get("data") or {}
                page_rows = data.get("list") or []
                if not isinstance(page_rows, list):
                    raise RuntimeError(f"zj api malformed list type: {type(page_rows).__name__}")
                pager = data.get("pager") or {}
                try:
                    page_count_from_server = int(pager.get("pageCount")) if pager.get("pageCount") is not None else page_count_from_server
                except Exception:  # noqa: BLE001
                    pass
                if not page_rows:
                    break

                rows.extend(page_rows)
                # Primary stop condition: server declared total pages.
                if page_count_from_server is not None and page >= page_count_from_server:
                    break
                # Fallback stop condition: short page.
                if len(page_rows) < page_size:
                    break
                time.sleep(0.04)
        return rows, api_root

    def _build_city_batches(self, api_root: str, headers: Dict[str, str]) -> List[Dict[str, str]]:
        """
        可选地市分片：
        - 仅在设置 MYBUILD_ZJ_CITY_SHARD=1 时启用。
        - 通过 EnterpriseInfo/getCity 拉取地市代码，返回 [{"City":"330100","COUNTY":""}, ...]
        """
        if os.getenv("MYBUILD_ZJ_CITY_SHARD", "0").strip() != "1":
            return []
        cities = _fetch_zj_city_codes(api_root=api_root, headers=headers, timeout=self.timeout_seconds)
        if not cities:
            return []
        # 注意：业务接口 `City` 参数需传中文地市名（如“杭州市”），传 code 会返回 code=204。
        return [{"City": name, "COUNTY": ""} for _code, name in cities if name]

    def _map_rows(self, rows: List[Dict], source_url: str) -> List[RawRecord]:
        raise NotImplementedError


class ZjJzscEnterpriseConnector(ZjJzscOpenApiConnectorBase):
    source_type = "zj_jzsc_enterprise_live"
    api_module = "EnterpriseInfo"
    api_action = "enterpriseInfo"
    record_type = "enterprise"
    entity_type = "enterprise"
    query_template = {
        "CertID": "",
        "EndDate": "",
        "Zzmark": "",
        "City": "",
        "COUNTY": "",
    }

    def _map_rows(self, rows: List[Dict], source_url: str) -> List[RawRecord]:
        records: List[RawRecord] = []
        province_code = self.source.province_code or "330000"
        city_code = self.source.city_code or "330100"
        for idx, row in enumerate(rows, start=1):
            city = str(row.get("city", "")).strip()
            county = str(row.get("county", "")).strip()
            city_name = f"{city} {county}".strip() or "浙江省"
            name = str(row.get("corpname", "")).strip()
            uscc = str(row.get("scucode1", "")).strip()
            corp_code = str(row.get("corpcode1", "")).strip()
            legal_person = str(row.get("legalmanname", "")).strip()
            event_date = _epoch_ms_to_date(row.get("opiniondatetime1"))
            if event_date == time.strftime("%Y-%m-%d"):
                event_date = str(row.get("opiniondatetime", "")).strip() or event_date

            records.append(
                RawRecord(
                    source_id=self.source.source_id,
                    source_name=self.source.name,
                    source_level=self.source.source_level,
                    source_url=source_url,
                    record_type=self.record_type,
                    province_code=province_code,
                    city_code=city_code,
                    city_name=city_name,
                    payload={
                        "entity_type": self.entity_type,
                        "name": name,
                        "uscc": uscc,
                        "project_code": corp_code or uscc or f"ZJ-CORP-{idx}",
                        "score": 80,
                        "status": "ACTIVE",
                        "event_date": event_date,
                        "legal_person": legal_person,
                        "corpcode_encrypted": str(row.get("corpcode", "")).strip(),
                        "source_business_type": "zj_jzsc_enterprise_list",
                    },
                )
            )
        return records


class ZjJzscPersonnelConnector(ZjJzscOpenApiConnectorBase):
    source_type = "zj_jzsc_personnel_live"
    api_module = "PersonnelInfo"
    api_action = "personnelWithin"
    record_type = "staff"
    entity_type = "staff"
    query_template = {
        "IdCard": "",
        "SpecialtyTypeName": "",
        "CorpName": "",
        "EffectDate": "",
        "City": "",
        "COUNTY": "",
    }

    def _map_rows(self, rows: List[Dict], source_url: str) -> List[RawRecord]:
        records: List[RawRecord] = []
        province_code = self.source.province_code or "330000"
        city_code = self.source.city_code or "330100"
        for idx, row in enumerate(rows, start=1):
            name = str(row.get("personname", "")).strip()
            cert_num = str(row.get("certnum", "")).strip()
            idcard_masked = str(row.get("idcard1", "")).strip()
            corp_name = str(row.get("corpname", "")).strip()
            uscc = str(row.get("scucode1", "")).strip()
            specialty = str(row.get("specialtytypename", "")).strip()
            major = str(row.get("zhuanye", "")).strip()
            edu_level = str(row.get("edulevelname", "")).strip()
            event_date = _epoch_ms_to_date(row.get("awarddate"))

            records.append(
                RawRecord(
                    source_id=self.source.source_id,
                    source_name=self.source.name,
                    source_level=self.source.source_level,
                    source_url=source_url,
                    record_type=self.record_type,
                    province_code=province_code,
                    city_code=city_code,
                    city_name="浙江省",
                    payload={
                        "entity_type": self.entity_type,
                        "name": name,
                        "uscc": uscc,
                        "project_code": cert_num or idcard_masked or f"ZJ-STAFF-{idx}",
                        "score": 80,
                        "status": "ACTIVE",
                        "event_date": event_date,
                        "person_id_no_masked": idcard_masked,
                        "register_type": specialty,
                        "register_no": cert_num,
                        "register_corp_name": corp_name,
                        "major": major,
                        "edu_level": edu_level,
                        "corpcode_encrypted": str(row.get("corpcode", "")).strip(),
                        "source_business_type": "zj_jzsc_personnel_list",
                    },
                )
            )
        return records


class ProvincePortalIndexConnector(BaseConnector):
    """
    Collect real hyperlink entries from province-level platform index pages.
    This is the first onboarding stage for multi-province source integration.
    """

    source_type = "province_portal_index_live"

    def fetch(self) -> Sequence[RawRecord]:
        html, final_url = _fetch_html_with_fallback(self.source.base_url)
        title = _extract_title(html) or self.source.name
        anchors = _extract_anchors(html, final_url)
        rows: List[RawRecord] = []

        province_code, city_code = _resolve_admin_codes(self.source)
        city_name = self.source.name

        # Add one root row
        rows.append(
            RawRecord(
                source_id=self.source.source_id,
                source_name=self.source.name,
                source_level=self.source.source_level,
                source_url=final_url,
                record_type="portal_index",
                province_code=province_code,
                city_code=city_code,
                city_name=city_name,
                payload={
                    "entity_type": "portal_index",
                    "name": title,
                    "uscc": "",
                    "project_code": f"PORTAL-ROOT-{province_code}",
                    "score": 100,
                    "status": "ACTIVE",
                    "event_date": time.strftime("%Y-%m-%d"),
                    "platform_url": final_url,
                    "source_business_type": "province_portal_index",
                },
            )
        )

        for idx, a in enumerate(anchors[:500], start=1):
            rows.append(
                RawRecord(
                    source_id=self.source.source_id,
                    source_name=self.source.name,
                    source_level=self.source.source_level,
                    source_url=a["href"],
                    record_type="portal_entry",
                    province_code=province_code,
                    city_code=city_code,
                    city_name=city_name,
                    payload={
                        "entity_type": "portal_entry",
                        "name": a["text"] or f"入口{idx}",
                        "uscc": "",
                        "project_code": f"PORTAL-{province_code}-{idx}",
                        "score": 100,
                        "status": "ACTIVE",
                        "event_date": time.strftime("%Y-%m-%d"),
                        "entry_url": a["href"],
                        "entry_category": _classify_entry(a["text"], a["href"]),
                        "source_business_type": "province_portal_entry",
                    },
                )
            )

        return rows


class ProvinceEntryProbeConnector(BaseConnector):
    """
    Probe second-level province entry pages and extract structural signals
    for future business-data connector generation.
    """

    source_type = "province_entry_probe_live"

    def fetch(self) -> Sequence[RawRecord]:
        html, final_url = _fetch_html_with_fallback(self.source.base_url)
        title = _extract_title(html) or self.source.name
        forms = len(re.findall(r"<form\\b", html, re.I))
        tables = len(re.findall(r"<table\\b", html, re.I))
        scripts = len(re.findall(r"<script\\b", html, re.I))
        anchors = _extract_anchors(html, final_url)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\\s+", " ", text).strip()[:4000]
        province_code, city_code = _resolve_admin_codes(self.source)

        category = "other"
        lowered = f"{title} {self.source.base_url}".lower()
        if any(k in lowered for k in ["企业", "enterprise", "company", "comp"]):
            category = "enterprise"
        elif any(k in lowered for k in ["人员", "staff", "person", "ry"]):
            category = "staff"
        elif any(k in lowered for k in ["项目", "project", "prj"]):
            category = "project"
        elif any(k in lowered for k in ["招标", "投标", "tender", "bid"]):
            category = "tender"
        elif any(k in lowered for k in ["信用", "诚信", "credit"]):
            category = "credit"

        rows: List[RawRecord] = [
            RawRecord(
                source_id=self.source.source_id,
                source_name=self.source.name,
                source_level=self.source.source_level,
                source_url=final_url,
                record_type="entry_probe",
                province_code=province_code,
                city_code=city_code,
                city_name=self.source.name,
                payload={
                    "entity_type": "entry_probe",
                    "name": title,
                    "uscc": "",
                    "project_code": f"PROBE-{self.source.source_id}",
                    "score": 100,
                    "status": "ACTIVE",
                    "event_date": time.strftime("%Y-%m-%d"),
                    "probe_url": final_url,
                    "probe_category": category,
                    "forms": forms,
                    "tables": tables,
                    "scripts": scripts,
                    "anchor_count": len(anchors),
                    "text_sample": text,
                    "source_business_type": "province_entry_probe",
                },
            )
        ]

        # keep top candidate links from probed page for next round generation
        for idx, a in enumerate(anchors[:80], start=1):
            rows.append(
                RawRecord(
                    source_id=self.source.source_id,
                    source_name=self.source.name,
                    source_level=self.source.source_level,
                    source_url=a["href"],
                    record_type="entry_probe_link",
                    province_code=province_code,
                    city_code=city_code,
                    city_name=self.source.name,
                    payload={
                        "entity_type": "entry_probe_link",
                        "name": a["text"] or f"探测链接{idx}",
                        "uscc": "",
                        "project_code": f"PROBE-LINK-{self.source.source_id}-{idx}",
                        "score": 100,
                        "status": "ACTIVE",
                        "event_date": time.strftime("%Y-%m-%d"),
                        "entry_url": a["href"],
                        "entry_category": _classify_entry(a["text"], a["href"]),
                        "source_business_type": "province_entry_probe_link",
                    },
                )
            )

        return rows


async def _collect_pages_async(
    base_url: str,
    page_path: str,
    api_path: str,
    page_size: int,
    max_pages: int,
    decrypt_key: bytes,
    decrypt_iv: bytes,
    extra_query: Dict[str, str] | None = None,
) -> List[Dict]:
    all_rows: List[Dict] = []
    extra_qs = ""
    if extra_query:
        parts = [f"{k}={urllib.parse.quote(str(v))}" for k, v in extra_query.items() if v is not None]
        if parts:
            extra_qs = "&" + "&".join(parts)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--ignore-certificate-errors",
                "--ignore-certificate-errors-spki-list",
                "--allow-insecure-localhost",
                "--allow-running-insecure-content",
                "--disable-features=BlockInsecurePrivateNetworkRequests",
            ],
        )
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()
        await page.goto(f"{base_url}{page_path}", wait_until="domcontentloaded", timeout=120000)
        await page.wait_for_timeout(1200)

        for pg in range(max_pages):
            cipher = await page.evaluate(
                """
                async ({apiPath, pg, pgsz, extraQs}) => {
                  const url = `${apiPath}?pg=${pg}&pgsz=${pgsz}&total=0${extraQs}`;
                  const resp = await fetch(url, {
                    credentials: 'include',
                    headers: { v: '231012', accessToken: '' }
                  });
                  return await resp.text();
                }
                """,
                {"apiPath": api_path, "pg": pg, "pgsz": page_size, "extraQs": extra_qs},
            )
            if not cipher:
                break

            payload = _try_decode_payload(cipher, decrypt_key, decrypt_iv)
            if not payload:
                break

            rows = payload.get("data", {}).get("list", [])
            if not isinstance(rows, list) or not rows:
                break

            all_rows.extend(rows)
            if len(rows) < page_size:
                break

            # Mild pacing to avoid triggering busy/anti-bot responses.
            await page.wait_for_timeout(220)

        await context.close()
        await browser.close()

    return all_rows


def _collect_pages_sync(
    base_url: str,
    page_path: str,
    api_path: str,
    page_size: int,
    max_pages: int,
    decrypt_key: bytes,
    decrypt_iv: bytes,
    extra_query: Dict[str, str] | None = None,
) -> List[Dict]:
    return asyncio.run(
        _collect_pages_async(
            base_url=base_url,
            page_path=page_path,
            api_path=api_path,
            page_size=page_size,
            max_pages=max_pages,
            decrypt_key=decrypt_key,
            decrypt_iv=decrypt_iv,
            extra_query=extra_query,
        )
    )


async def _collect_batched_async(
    base_url: str,
    page_path: str,
    api_path: str,
    page_size: int,
    max_pages_per_batch: int,
    decrypt_key: bytes,
    decrypt_iv: bytes,
    batches: List[Dict[str, str]],
    dedup_field: str | None = None,
    max_consecutive_empty_batches: int = 3,
    per_call_timeout_sec: float = 25.0,
    progress_tag: str = "",
    on_batch: "Callable[[str, List[Dict]], None] | None" = None,
    browser_refresh_every: int = 8,
    max_refreshes_on_empty: int = 4,
) -> List[Dict]:
    """
    在浏览器会话内顺序处理多个 extra_query 批次（例如 31 省份）。

    - 每 `browser_refresh_every` 批主动重启 browser/context/page，清除 cookie 和
      session-level 反爬计数（JZSC 每个 session 累计 API 调用到阈值会 401）。
    - 触发连续空批后，会额外尝试刷新 browser 最多 `max_refreshes_on_empty` 次。
    - 任何成功批次都重置 refresh_on_empty 计数。
    - on_batch：每批完成时同步回调，pipeline 层可 insert+commit 实现流式持久化。
    """
    import sys as _sys

    all_rows: List[Dict] = []
    seen: set[str] = set()
    consecutive_empty = 0
    batches_since_refresh = 0
    refreshes_on_empty = 0
    refresh_count = 0

    def _log(msg: str) -> None:
        print(f"[batched {progress_tag}] {msg}", file=_sys.stderr, flush=True)

    async with async_playwright() as p:
        browser = None
        context = None
        page = None

        async def _open_session() -> bool:
            """(Re)create browser + context + page and navigate to list page."""
            nonlocal browser, context, page, refresh_count
            if context is not None:
                try:
                    await context.close()
                except Exception:  # noqa: BLE001
                    pass
            if browser is not None:
                try:
                    await browser.close()
                except Exception:  # noqa: BLE001
                    pass
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--ignore-certificate-errors",
                    "--ignore-certificate-errors-spki-list",
                    "--allow-insecure-localhost",
                    "--allow-running-insecure-content",
                    "--disable-features=BlockInsecurePrivateNetworkRequests",
                ],
            )
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            page.set_default_timeout(int(per_call_timeout_sec * 1000))
            for attempt in range(2):
                try:
                    await page.goto(f"{base_url}{page_path}", wait_until="domcontentloaded", timeout=60000)
                    break
                except Exception as e:  # noqa: BLE001
                    _log(f"session goto failed (attempt {attempt+1}): {e!r}")
            else:
                return False
            await page.wait_for_timeout(1200)
            refresh_count += 1
            return True

        if not await _open_session():
            _log("initial session open failed; abort")
            return all_rows
        _log(f"page loaded (session #{refresh_count}), starting {len(batches)} batches")

        bi = 0
        while bi < len(batches):
            batch = batches[bi]
            # 主动轮换：每 N 批刷 session，防止累计反爬
            if batches_since_refresh >= browser_refresh_every:
                _log(f"proactive browser refresh after {batches_since_refresh} batches (session #{refresh_count+1})")
                ok = await _open_session()
                if not ok:
                    _log("refresh failed; abort")
                    break
                batches_since_refresh = 0
                consecutive_empty = 0

            extra_qs = ""
            parts = [f"{k}={urllib.parse.quote(str(v))}" for k, v in batch.items() if v is not None]
            if parts:
                extra_qs = "&" + "&".join(parts)
            batch_label = ",".join(f"{k}={v}" for k, v in batch.items())

            batch_rows: List[Dict] = []
            stopped_at_page = -1
            for pg in range(max_pages_per_batch):
                try:
                    cipher = await asyncio.wait_for(
                        page.evaluate(
                            """
                            async ({apiPath, pg, pgsz, extraQs}) => {
                              const url = `${apiPath}?pg=${pg}&pgsz=${pgsz}&total=0${extraQs}`;
                              const resp = await fetch(url, {
                                credentials: 'include',
                                headers: { v: '231012', accessToken: '' }
                              });
                              return await resp.text();
                            }
                            """,
                            {"apiPath": api_path, "pg": pg, "pgsz": page_size, "extraQs": extra_qs},
                        ),
                        timeout=per_call_timeout_sec,
                    )
                except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                    stopped_at_page = pg
                    break
                if not cipher:
                    stopped_at_page = pg
                    break
                payload = _try_decode_payload(cipher, decrypt_key, decrypt_iv)
                if not payload:
                    stopped_at_page = pg
                    break
                rows = payload.get("data", {}).get("list", [])
                if not isinstance(rows, list) or not rows:
                    stopped_at_page = pg
                    break
                batch_rows.extend(rows)
                if len(rows) < page_size:
                    stopped_at_page = pg + 1
                    break
                await page.wait_for_timeout(200)

            _log(f"batch {bi+1}/{len(batches)} [{batch_label}] rows={len(batch_rows)} stopped@page={stopped_at_page}")
            batches_since_refresh += 1

            if not batch_rows:
                consecutive_empty += 1
                if consecutive_empty >= max_consecutive_empty_batches:
                    if refreshes_on_empty < max_refreshes_on_empty:
                        _log(
                            f"empty streak (consecutive={consecutive_empty}) -> refresh browser "
                            f"({refreshes_on_empty+1}/{max_refreshes_on_empty}), will retry batch {bi+1}"
                        )
                        ok = await _open_session()
                        if not ok:
                            _log("refresh-on-empty failed; abort")
                            break
                        batches_since_refresh = 0
                        consecutive_empty = 0
                        refreshes_on_empty += 1
                        # 新 session 后重试当前 batch（不 +=1，下轮循环同一个 bi）
                        continue
                    _log(f"giving up after {refreshes_on_empty} empty-refreshes")
                    break
                await page.wait_for_timeout(800)
                bi += 1
                continue
            consecutive_empty = 0
            refreshes_on_empty = 0  # 成功批次，重置失败计数

            if dedup_field:
                new_rows: List[Dict] = []
                for r in batch_rows:
                    k = str(r.get(dedup_field, ""))
                    if k and k not in seen:
                        seen.add(k)
                        new_rows.append(r)
                all_rows.extend(new_rows)
                streamed_rows = new_rows
            else:
                all_rows.extend(batch_rows)
                streamed_rows = batch_rows

            # 流式回调：让 pipeline 层立即 insert+commit 当前 batch
            if on_batch is not None and streamed_rows:
                try:
                    on_batch(batch_label, streamed_rows)
                except Exception as e:  # noqa: BLE001
                    _log(f"on_batch callback error: {e!r}")

            await page.wait_for_timeout(400)
            bi += 1

        _log(f"done: total_rows={len(all_rows)} refresh_count={refresh_count}")
        if context is not None:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass
        if browser is not None:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass

    return all_rows


def _collect_batched_sync(
    base_url: str,
    page_path: str,
    api_path: str,
    page_size: int,
    max_pages_per_batch: int,
    decrypt_key: bytes,
    decrypt_iv: bytes,
    batches: List[Dict[str, str]],
    dedup_field: str | None = None,
    max_consecutive_empty_batches: int = 3,
    per_call_timeout_sec: float = 25.0,
    progress_tag: str = "",
    on_batch: "Callable[[str, List[Dict]], None] | None" = None,
    browser_refresh_every: int = 8,
    max_refreshes_on_empty: int = 4,
) -> List[Dict]:
    return asyncio.run(
        _collect_batched_async(
            base_url=base_url,
            page_path=page_path,
            api_path=api_path,
            page_size=page_size,
            max_pages_per_batch=max_pages_per_batch,
            decrypt_key=decrypt_key,
            decrypt_iv=decrypt_iv,
            batches=batches,
            dedup_field=dedup_field,
            max_consecutive_empty_batches=max_consecutive_empty_batches,
            per_call_timeout_sec=per_call_timeout_sec,
            progress_tag=progress_tag,
            on_batch=on_batch,
            browser_refresh_every=browser_refresh_every,
            max_refreshes_on_empty=max_refreshes_on_empty,
        )
    )


def _try_decode_payload(cipher_text: str, key: bytes, iv: bytes) -> Dict | None:
    t = (cipher_text or "").strip()
    if not t:
        return None

    # Some responses may already be plain JSON (e.g., busy/error).
    if t.startswith("{"):
        try:
            obj = json.loads(t)
            if obj.get("code") in (401, 503):
                return None
            return obj
        except json.JSONDecodeError:
            return None

    try:
        plain = _aes_cbc_decrypt_hex(t, key, iv)
        obj = json.loads(plain)
        if obj.get("code") in (401, 503):
            return None
        return obj
    except Exception:  # noqa: BLE001
        return None


def _fetch_html_with_fallback(url: str) -> tuple[str, str]:
    # 1) direct HTTP fetch
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            b = resp.read(800_000)
            final_url = resp.geturl()
            return b.decode("utf-8", "ignore"), final_url
    except Exception:
        pass

    # 2) playwright fallback for JS-heavy/anti-bot pages
    async def _pw() -> tuple[str, str]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--ignore-certificate-errors",
                    "--ignore-certificate-errors-spki-list",
                    "--allow-insecure-localhost",
                    "--allow-running-insecure-content",
                    "--disable-features=BlockInsecurePrivateNetworkRequests",
                ],
            )
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=120000)
            await page.wait_for_timeout(2000)
            html = await page.content()
            final_url = page.url
            await context.close()
            await browser.close()
            return html, final_url

    return asyncio.run(_pw())


def _extract_title(html: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _extract_anchors(html: str, base_url: str) -> List[Dict[str, str]]:
    anchors: List[Dict[str, str]] = []
    for m in re.finditer(r"<a[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, re.I | re.S):
        href = (m.group(1) or "").strip()
        text = re.sub(r"<[^>]+>", "", m.group(2) or "")
        text = re.sub(r"\s+", " ", text).strip()
        if not href:
            continue
        if href.startswith("javascript:") or href.startswith("#"):
            continue
        full = urllib.parse.urljoin(base_url, href)
        anchors.append({"href": full, "text": text})

    # Deduplicate by href+text
    seen = set()
    uniq = []
    for a in anchors:
        k = (a["href"], a["text"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(a)
    return uniq


def _classify_entry(text: str, href: str) -> str:
    t = f"{text} {href}".lower()
    if any(k in t for k in ["企业", "company", "comp"]):
        return "enterprise"
    if any(k in t for k in ["人员", "staff", "person", "ry_"]):
        return "staff"
    if any(k in t for k in ["项目", "project", "prj"]):
        return "project"
    if any(k in t for k in ["招标", "投标", "tender", "bid"]):
        return "tender"
    if any(k in t for k in ["信用", "诚信", "credit"]):
        return "credit"
    return "other"


def _aes_cbc_decrypt_hex(cipher_hex: str, key: bytes, iv: bytes) -> str:
    encrypted = bytes.fromhex(cipher_hex.strip())
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend()).decryptor()
    plain = decryptor.update(encrypted) + decryptor.finalize()
    pad = plain[-1]
    if 1 <= pad <= 16:
        plain = plain[:-pad]
    return plain.decode("utf-8", "ignore")


def _epoch_ms_to_date(v) -> str:
    try:
        if v is None:
            return time.strftime("%Y-%m-%d")
        iv = int(v)
        if iv <= 0:
            return time.strftime("%Y-%m-%d")
        return time.strftime("%Y-%m-%d", time.localtime(iv / 1000))
    except Exception:  # noqa: BLE001
        return time.strftime("%Y-%m-%d")


def _to_city_code(region_code: str, fallback: str) -> str:
    region_code = (region_code or "").strip()
    if not region_code:
        return fallback
    if len(region_code) == 6 and region_code.isdigit():
        return region_code
    if len(region_code) == 4 and region_code.isdigit():
        return f"{region_code}00"
    if len(region_code) == 2 and region_code.isdigit():
        return f"{region_code}0100"
    return fallback


def _to_province_code(city_code: str) -> str:
    city_code = (city_code or "000000").strip()
    if len(city_code) == 6 and city_code.isdigit():
        return f"{city_code[:2]}0000"
    return "000000"


def _resolve_admin_codes(source: SourceDefinition) -> tuple[str, str]:
    province_code = (source.province_code or "").strip()
    city_code = (source.city_code or "").strip()

    if not (len(province_code) == 6 and province_code.isdigit() and province_code != "000000"):
        m = re.match(r"(prov_\d{2})", source.source_id or "")
        if m:
            province_code = PROVINCE_CODE_BY_SOURCE_PREFIX.get(m.group(1), "000000")
        else:
            province_code = "000000"

    if not (len(city_code) == 6 and city_code.isdigit() and city_code != "000000"):
        city_code = f"{province_code[:2]}0100" if province_code != "000000" else "000000"

    return province_code, city_code


def _discover_zj_api_root(base_url: str) -> str | None:
    """
    动态发现浙江站当前有效 API 根路径。
    优先从 PublicWeb 的 app.*.js 里提取 `$url:"https://.../publishserver/.../OTMpyrr"`。
    """
    try:
        index_url = f"{base_url}/PublicWeb/index.html"
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            idx = client.get(index_url).text
            js_rel_paths = re.findall(r"static/js/app\.[a-f0-9]+\.js", idx)
            candidates: List[str] = []
            for rel in js_rel_paths:
                app_js_url = f"{base_url}/PublicWeb/{rel}"
                js = client.get(app_js_url).text
                # 收集 app.js 里所有 publishserver 根路径候选
                roots = re.findall(r"https?://[^\"']+/publishserver/[^\"']+", js)
                for root in roots:
                    root = root.rstrip("/")
                    if root not in candidates:
                        candidates.append(root)

            # 对候选逐个探测：以 enterpriseInfo page=1,size=1 判断是否可用
            probe_headers = {
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": "https://jzsc.jst.zj.gov.cn",
                "Referer": "https://jzsc.jst.zj.gov.cn/PublicWeb/index.html",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/145.0.0.0 Safari/537.36"
                ),
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            }
            probe_payload = {
                "CertID": "",
                "EndDate": "",
                "Zzmark": "",
                "City": "",
                "COUNTY": "",
                "pageIndex": 1,
                "pageSize": 1,
            }
            for root in candidates:
                try:
                    resp = client.post(
                        f"{root}/EnterpriseInfo/enterpriseInfo",
                        headers=probe_headers,
                        json=probe_payload,
                        timeout=12,
                    )
                    if resp.status_code != 200:
                        continue
                    body = resp.json()
                    if int(body.get("code", -1)) == 0:
                        return root
                except Exception:  # noqa: BLE001
                    continue
    except Exception:  # noqa: BLE001
        return None
    return None


def _fetch_zj_city_codes(
    api_root: str,
    headers: Dict[str, str],
    timeout: int = 20,
) -> List[tuple[str, str]]:
    """
    返回 [(city_code, city_name), ...]，例如 [("330100","杭州市"), ...]。
    """
    url = f"{api_root}/EnterpriseInfo/getCity"
    out: List[tuple[str, str]] = []
    try:
        with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
            # HAR 显示 GET/POST 都可用，这里优先 GET，失败再 POST。
            resp = client.get(url)
            if resp.status_code != 200:
                resp = client.post(url, json={})
            resp.raise_for_status()
            body = resp.json()
            if int(body.get("code", -1)) != 0:
                return []
            rows = body.get("data") or []
            if not isinstance(rows, list):
                return []
            for r in rows:
                code_raw = str(r.get("adminareaclassid", "")).strip()
                name = str(r.get("adminareaname", "")).strip()
                if not code_raw:
                    continue
                # API 期望 6 位 code
                code = code_raw if len(code_raw) == 6 else code_raw[:6]
                if len(code) == 6 and code.isdigit():
                    out.append((code, name or code))
    except Exception:  # noqa: BLE001
        return []
    # 去重保序
    uniq: List[tuple[str, str]] = []
    seen = set()
    for c in out:
        if c[0] in seen:
            continue
        seen.add(c[0])
        uniq.append(c)
    return uniq


CONNECTOR_REGISTRY: Dict[str, Type[BaseConnector]] = {
    JzscCompanyLiveConnector.source_type: JzscCompanyLiveConnector,
    JzscStaffLiveConnector.source_type: JzscStaffLiveConnector,
    JzscProjectLiveConnector.source_type: JzscProjectLiveConnector,
    JzscStaffByCompanyConnector.source_type: JzscStaffByCompanyConnector,
    JzscProjectByCompanyConnector.source_type: JzscProjectByCompanyConnector,
    ZjJzscEnterpriseConnector.source_type: ZjJzscEnterpriseConnector,
    ZjJzscPersonnelConnector.source_type: ZjJzscPersonnelConnector,
    ProvincePortalIndexConnector.source_type: ProvincePortalIndexConnector,
    ProvinceEntryProbeConnector.source_type: ProvinceEntryProbeConnector,
}


def build_connector(source: SourceDefinition) -> BaseConnector:
    connector_cls = CONNECTOR_REGISTRY.get(source.source_type)
    if connector_cls is None:
        raise ValueError(f"Unsupported source type: {source.source_type}")
    return connector_cls(source)


def build_connector_with_cursor(
    source: SourceDefinition,
    cursor_value: str | None,
) -> BaseConnector:
    connector_cls = CONNECTOR_REGISTRY.get(source.source_type)
    if connector_cls is None:
        raise ValueError(f"Unsupported source type: {source.source_type}")
    return connector_cls(source, cursor_value=cursor_value)


def fetch_all_sources_stable(
    sources: Iterable[SourceDefinition],
    source_cursors: Dict[str, str] | None = None,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    max_workers: int = 8,
    per_source_timeout_sec: int = 75,
) -> tuple[List[RawRecord], List[SourceFailure]]:
    source_list = list(sources)
    raw_records: List[RawRecord] = []
    failures: List[SourceFailure] = []

    def _run_one(source: SourceDefinition) -> tuple[List[RawRecord], SourceFailure | None]:
        last_err: Exception | None = None
        cursor_value = (source_cursors or {}).get(source.source_id)
        for attempt in range(1, max_attempts + 1):
            try:
                connector = build_connector_with_cursor(source, cursor_value)
                records = connector.fetch()
                return list(records), None
            except Exception as err:  # noqa: BLE001
                last_err = err
                if attempt < max_attempts:
                    time.sleep(backoff_seconds * attempt)

        if last_err is not None:
            return [], SourceFailure(
                source_id=source.source_id,
                source_name=source.name,
                error_type=type(last_err).__name__,
                error_message=str(last_err),
                attempts=max_attempts,
            )
        return [], None

    workers = max(1, min(max_workers, len(source_list)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fut_to_source = {ex.submit(_run_one, source): source for source in source_list}
        for f in as_completed(fut_to_source):
            source = fut_to_source[f]
            try:
                records, failure = f.result(timeout=per_source_timeout_sec)
            except Exception as err:  # noqa: BLE001
                failures.append(
                    SourceFailure(
                        source_id=source.source_id,
                        source_name=source.name,
                        error_type=type(err).__name__,
                        error_message=str(err),
                        attempts=max_attempts,
                    )
                )
                continue
            if records:
                raw_records.extend(records)
            if failure is not None:
                failures.append(failure)

    return raw_records, failures
