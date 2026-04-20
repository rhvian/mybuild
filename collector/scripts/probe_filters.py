"""
探测 JZSC API 支持的筛选参数。
用法：python3 collector/scripts/probe_filters.py
结果用于扩展 JzscCompanyLiveConnector / JzscStaffLiveConnector / JzscProjectLiveConnector 的 region_codes 策略。

注意：必须在主 pipeline 不跑时使用（避免 Playwright 实例冲突）。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Iterable, List, Tuple

from playwright.async_api import async_playwright

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


KEY = b"Dt8j9wGw%6HbxfFn"
IV = b"0123456789ABCDEF"


def _decode(cipher: str) -> Dict[str, Any] | None:
    s = (cipher or "").strip()
    if not s:
        return None
    if s.startswith("{"):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None
    try:
        encrypted = bytes.fromhex(s)
        d = Cipher(algorithms.AES(KEY), modes.CBC(IV), backend=default_backend()).decryptor()
        plain = d.update(encrypted) + d.finalize()
        pad = plain[-1]
        if 1 <= pad <= 16:
            plain = plain[:-pad]
        return json.loads(plain.decode("utf-8", "ignore"))
    except Exception:
        return None


async def _probe(page, api_path: str, params: Dict[str, str]) -> Tuple[int, int]:
    """返回 (total, rows_count)"""
    param_str = "&".join(f"{k}={v}" for k, v in params.items())
    cipher = await page.evaluate(
        """
        async ({apiPath, paramStr}) => {
          const url = `${apiPath}?pg=0&pgsz=15&total=0&${paramStr}`;
          const resp = await fetch(url, {
            credentials: 'include',
            headers: { v: '231012', accessToken: '' }
          });
          return await resp.text();
        }
        """,
        {"apiPath": api_path, "paramStr": param_str},
    )
    obj = _decode(cipher)
    if not obj:
        return (-1, 0)
    data = obj.get("data", {})
    total = data.get("total", -1)
    rows = data.get("list", []) or []
    return (total, len(rows))


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--ignore-certificate-errors"])
        ctx = await browser.new_context(ignore_https_errors=True)

        endpoints = [
            ("comp", "/data/company", "/APi/webApi/dataservice/query/comp/list"),
            ("staff", "/data/person", "/APi/webApi/dataservice/query/staff/list"),
            ("project", "/data/project", "/APi/webApi/dataservice/query/project/list"),
        ]

        # 通用参数名候选
        region_params = ["qy_region", "reg_pro_code", "reg_region", "apt_region", "prj_region", "city_code", "regist_region"]
        apt_params = ["apt_root", "apt_code", "apt_class", "APT_ROOT", "apt_type"]
        name_params = ["apt_name", "qy_name", "qymc", "keyword", "key", "name"]

        sample_values = {
            "region": "440000",  # 广东
            "apt_root": "1",
            "apt_code": "235",
            "name": "中国建筑",
        }

        for tag, page_path, api_path in endpoints:
            print(f"\n===== {tag} ({api_path}) =====")
            page = await ctx.new_page()
            await page.goto(f"https://jzsc.mohurd.gov.cn{page_path}", timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            print("-- region params --")
            for rp in region_params:
                total, cnt = await _probe(page, api_path, {rp: sample_values["region"]})
                print(f"  {rp}=440000 -> total={total} rows={cnt}")
            print("-- apt params --")
            for ap in apt_params:
                total, cnt = await _probe(page, api_path, {ap: sample_values["apt_root"]})
                print(f"  {ap}=1 -> total={total} rows={cnt}")
            print("-- name/keyword params --")
            for np in name_params:
                total, cnt = await _probe(page, api_path, {np: sample_values["name"]})
                print(f"  {np}={sample_values['name']} -> total={total} rows={cnt}")
            await page.close()

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
