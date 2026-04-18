from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from typing import Dict, Iterable, List, Sequence, Type

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

    def __init__(self, source: SourceDefinition):
        self.source = source

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
    max_pages = 100

    def fetch(self) -> Sequence[RawRecord]:
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

    def _map_rows(self, rows: List[Dict]) -> List[RawRecord]:
        raise NotImplementedError


class JzscCompanyLiveConnector(JzscLiveConnectorBase):
    source_type = "jzsc_company_live"
    page_path = "/data/company"
    api_path = "/APi/webApi/dataservice/query/comp/list"
    record_type = "enterprise"
    entity_type = "enterprise"

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
) -> List[Dict]:
    all_rows: List[Dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()
        await page.goto(f"{base_url}{page_path}", wait_until="domcontentloaded", timeout=120000)
        await page.wait_for_timeout(1200)

        for pg in range(max_pages):
            cipher = await page.evaluate(
                """
                async ({apiPath, pg, pgsz}) => {
                  const url = `${apiPath}?pg=${pg}&pgsz=${pgsz}&total=0`;
                  const resp = await fetch(url, {
                    credentials: 'include',
                    headers: { v: '231012', accessToken: '' }
                  });
                  return await resp.text();
                }
                """,
                {"apiPath": api_path, "pg": pg, "pgsz": page_size},
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
            browser = await p.chromium.launch(headless=True)
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


CONNECTOR_REGISTRY: Dict[str, Type[BaseConnector]] = {
    JzscCompanyLiveConnector.source_type: JzscCompanyLiveConnector,
    JzscStaffLiveConnector.source_type: JzscStaffLiveConnector,
    JzscProjectLiveConnector.source_type: JzscProjectLiveConnector,
    ProvincePortalIndexConnector.source_type: ProvincePortalIndexConnector,
    ProvinceEntryProbeConnector.source_type: ProvinceEntryProbeConnector,
}


def build_connector(source: SourceDefinition) -> BaseConnector:
    connector_cls = CONNECTOR_REGISTRY.get(source.source_type)
    if connector_cls is None:
        raise ValueError(f"Unsupported source type: {source.source_type}")
    return connector_cls(source)


def fetch_all_sources_stable(
    sources: Iterable[SourceDefinition],
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
        for attempt in range(1, max_attempts + 1):
            try:
                connector = build_connector(source)
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
