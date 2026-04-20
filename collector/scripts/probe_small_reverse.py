"""
小规模测试：用前 10 家企业跑 ry_qymc 和 buildCorpName 反查，验证机制和估算数据量。
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
        enc = bytes.fromhex(s)
        d = Cipher(algorithms.AES(KEY), modes.CBC(IV), backend=default_backend()).decryptor()
        plain = d.update(enc) + d.finalize()
        pad = plain[-1]
        if 1 <= pad <= 16:
            plain = plain[:-pad]
        return json.loads(plain.decode("utf-8", "ignore"))
    except Exception:
        return None


def _sample_companies(n: int = 10) -> list[str]:
    conn = sqlite3.connect("collector/data/collector.db")
    rows = conn.execute(
        "SELECT DISTINCT name FROM normalized_entity WHERE entity_type='enterprise' AND name != '' ORDER BY RANDOM() LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows if r[0]]


async def main():
    companies = _sample_companies(10)
    print(f"sampling {len(companies)} companies:")
    for c in companies:
        print(f"  {c}")
    print()

    staff_total = 0
    project_total = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--ignore-certificate-errors"])
        ctx = await browser.new_context(ignore_https_errors=True)

        # === staff by ry_qymc ===
        page_s = await ctx.new_page()
        await page_s.goto("https://jzsc.mohurd.gov.cn/data/person", timeout=60000, wait_until="domcontentloaded")
        await page_s.wait_for_timeout(2000)
        print("\n=== Staff by ry_qymc ===")
        for c in companies:
            cipher = await page_s.evaluate(
                """async ({v}) => {
                  const resp = await fetch(`/APi/webApi/dataservice/query/staff/list?pg=0&pgsz=15&total=0&ry_qymc=${encodeURIComponent(v)}`,
                    {credentials:'include', headers:{v:'231012',accessToken:''}});
                  return await resp.text();
                }""",
                {"v": c},
            )
            obj = _decode(cipher) or {}
            data = obj.get("data", {}) if isinstance(obj.get("data"), dict) else {}
            total = data.get("total", 0) if isinstance(data.get("total"), int) else 0
            rows = data.get("list") or []
            mark = "★" if total > 0 else " "
            print(f"  {mark} {c[:30]:30s} total={total:4d} rows[0]={rows[0].get('RY_NAME','') if rows else '-'}|{rows[0].get('REG_TYPE_NAME','') if rows else ''}")
            staff_total += total

        # === project by buildCorpName ===
        page_p = await ctx.new_page()
        await page_p.goto("https://jzsc.mohurd.gov.cn/data/project", timeout=60000, wait_until="domcontentloaded")
        await page_p.wait_for_timeout(2000)
        print("\n=== Project by buildCorpName ===")
        for c in companies:
            cipher = await page_p.evaluate(
                """async ({v}) => {
                  const resp = await fetch(`/APi/webApi/dataservice/query/project/list?pg=0&pgsz=15&total=0&buildCorpName=${encodeURIComponent(v)}`,
                    {credentials:'include', headers:{v:'231012',accessToken:''}});
                  return await resp.text();
                }""",
                {"v": c},
            )
            obj = _decode(cipher) or {}
            data = obj.get("data", {}) if isinstance(obj.get("data"), dict) else {}
            total = data.get("total", 0) if isinstance(data.get("total"), int) else 0
            rows = data.get("list") or []
            mark = "★" if total > 0 else " "
            sample_name = (rows[0].get("PRJNAME", "")[:25] if rows else "-")
            builder = (rows[0].get("BUILDCORPNAME", "")[:15] if rows else "")
            print(f"  {mark} {c[:30]:30s} total={total:4d} [{sample_name}]|builder={builder}")
            project_total += total

        await browser.close()

    print(f"\n=== 小样本统计 ===")
    print(f"  sampled {len(companies)} companies")
    print(f"  staff total: {staff_total}  avg per company: {staff_total/len(companies):.1f}")
    print(f"  project total: {project_total}  avg per company: {project_total/len(companies):.1f}")
    print(f"\n=== 全量外推（14,076 企业） ===")
    print(f"  预估 staff  : {int(14076 * (staff_total / max(len(companies), 1))):,}")
    print(f"  预估 project: {int(14076 * (project_total / max(len(companies), 1))):,}")


if __name__ == "__main__":
    asyncio.run(main())
