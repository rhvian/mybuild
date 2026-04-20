"""
通过企业 QY_ID 反查人员 / 项目 — 假设 API 支持 reg_qyid / build_corp_id 筛选

用法：python3 collector/scripts/probe_by_qyid.py
从数据库取出 10 个已采集的 QY_ID，逐一试下列参数组合。

如果找到有效参数，后续可以实现新的连接器：
  JzscStaffByCompanyConnector  / JzscProjectByCompanyConnector
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from playwright.async_api import async_playwright

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


KEY = b"Dt8j9wGw%6HbxfFn"
IV = b"0123456789ABCDEF"


def _decode(cipher: str):
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


def _get_sample_qyids(limit: int = 5) -> list[dict]:
    conn = sqlite3.connect("collector/data/collector.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT name, raw_payload_json
        FROM normalized_entity
        WHERE entity_type='enterprise'
        ORDER BY RANDOM() LIMIT ?
        """,
        (limit,),
    ).fetchall()
    result = []
    for r in rows:
        p = json.loads(r["raw_payload_json"] or "{}")
        qy_id = p.get("project_code", "")
        if qy_id and qy_id.startswith("Q"):  # 某些 fallback 是 QY-xxx
            continue
        result.append({"name": r["name"], "qy_id": qy_id})
    conn.close()
    return result


async def main() -> None:
    samples = _get_sample_qyids(5)
    print(f"Sampled {len(samples)} companies:")
    for s in samples:
        print(f"  {s['name']}: QY_ID={s['qy_id']}")

    if not samples:
        print("no samples available")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--ignore-certificate-errors"])
        ctx = await browser.new_context(ignore_https_errors=True)
        page = await ctx.new_page()
        await page.goto("https://jzsc.mohurd.gov.cn/data/person", timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # 试各种参数组合
        test_matrix = [
            ("/APi/webApi/dataservice/query/staff/list", "reg_qyid"),
            ("/APi/webApi/dataservice/query/staff/list", "reg_qy_id"),
            ("/APi/webApi/dataservice/query/staff/list", "qy_id"),
            ("/APi/webApi/dataservice/query/staff/list", "qyid"),
            ("/APi/webApi/dataservice/query/staff/list", "corp_id"),
            ("/APi/webApi/dataservice/query/project/list", "buildcorpid"),
            ("/APi/webApi/dataservice/query/project/list", "build_corp_id"),
            ("/APi/webApi/dataservice/query/project/list", "buildcorpcode"),
            ("/APi/webApi/dataservice/query/project/list", "buildcorp"),
            ("/APi/webApi/dataservice/query/project/list", "qy_id"),
        ]

        sample_qy_id = samples[0]["qy_id"]
        sample_name = samples[0]["name"]
        print(f"\nUsing {sample_name} QY_ID={sample_qy_id}")

        for api_path, param in test_matrix:
            cipher = await page.evaluate(
                """
                async ({apiPath, p, v}) => {
                  const url = `${apiPath}?pg=0&pgsz=15&total=0&${p}=${encodeURIComponent(v)}`;
                  const resp = await fetch(url, {
                    credentials: 'include',
                    headers: { v: '231012', accessToken: '' }
                  });
                  return await resp.text();
                }
                """,
                {"apiPath": api_path, "p": param, "v": sample_qy_id},
            )
            obj = _decode(cipher) or {}
            data = obj.get("data", {})
            total = data.get("total", "?")
            rows = data.get("list") or []
            hint = ""
            if rows:
                r0 = rows[0]
                if "RY_NAME" in r0:
                    hint = f"staff:{r0.get('RY_NAME','')}|{r0.get('REG_QYMC','')[:20]}"
                elif "PRJNAME" in r0:
                    hint = f"project:{r0.get('PRJNAME','')[:40]}|builder:{r0.get('BUILDCORPNAME','')[:20]}"
            mark = "★" if (isinstance(total, int) and 0 < total < 100000) else " "
            print(f"  {mark} {api_path.split('/')[-2]}/list ?{param}={sample_qy_id[:20]} -> total={total} rows={len(rows)} {hint}")

        # 另外试详情 API
        print(f"\n=== 详情 API 尝试（查单个企业/人员/项目） ===")
        detail_paths = [
            "/APi/webApi/dataservice/query/comp/detail",
            "/APi/webApi/dataservice/query/comp/getInfo",
            "/APi/webApi/dataservice/query/comp/view",
            "/APi/webApi/dataservice/query/company/detail",
        ]
        for dp in detail_paths:
            cipher = await page.evaluate(
                """
                async ({apiPath, qy_id}) => {
                  const url = `${apiPath}?qy_id=${qy_id}`;
                  const resp = await fetch(url, {
                    credentials: 'include',
                    headers: { v: '231012', accessToken: '' }
                  });
                  return {status: resp.status, text: await resp.text()};
                }
                """,
                {"apiPath": dp, "qy_id": sample_qy_id},
            )
            text_snippet = (cipher.get("text") or "")[:100]
            print(f"  {dp} -> status={cipher['status']} text={text_snippet}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
