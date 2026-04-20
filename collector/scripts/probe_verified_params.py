"""
验证从 JS 源码提取的参数名和 API 路径。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3

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


def _sample_companies(n: int = 3) -> list:
    conn = sqlite3.connect("collector/data/collector.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT name, raw_payload_json
           FROM normalized_entity
           WHERE entity_type='enterprise' AND name LIKE '%建%'
           ORDER BY RANDOM() LIMIT ?""",
        (n,),
    ).fetchall()
    out = []
    for r in rows:
        p = json.loads(r["raw_payload_json"] or "{}")
        out.append({"name": r["name"], "qy_id": p.get("project_code", "")})
    conn.close()
    return out


async def main():
    samples = _sample_companies(3)
    print("samples:", samples)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--ignore-certificate-errors"])
        ctx = await browser.new_context(ignore_https_errors=True)
        page = await ctx.new_page()

        # ===== 测试 1：staff API 用正确参数 ry_qymc =====
        print("\n===== TEST 1: staff/list ?ry_qymc=中国建筑 =====")
        await page.goto("https://jzsc.mohurd.gov.cn/data/person", timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        for param, value in [("ry_qymc", "中国建筑"), ("ry_name", "张伟"), ("ry_reg_type", "1"),
                             ("apt_code", "235"), ("apt_root", "1")]:
            cipher = await page.evaluate(
                """async ({apiPath, p, v}) => {
                  const url = `${apiPath}?pg=0&pgsz=15&total=0&${p}=${encodeURIComponent(v)}`;
                  const resp = await fetch(url, {credentials: 'include', headers: {v:'231012', accessToken:''}});
                  return await resp.text();
                }""",
                {"apiPath": "/APi/webApi/dataservice/query/staff/list", "p": param, "v": value},
            )
            obj = _decode(cipher) or {}
            data = obj.get("data", {})
            total = data.get("total", "?")
            rows = data.get("list") or []
            sample_info = ""
            if rows:
                r0 = rows[0]
                sample_info = f"{r0.get('RY_NAME','')}|{r0.get('REG_TYPE_NAME','')}|{r0.get('REG_QYMC','')[:15]}"
            mark = "★" if (isinstance(total, int) and total != 4677152) else " "
            print(f"  {mark} {param}={value!r} total={total} rows={len(rows)} {sample_info}")

        # ===== 测试 2：company detail API =====
        print("\n===== TEST 2: comp/compDetail + comp/regStaffList =====")
        if samples:
            s0 = samples[0]
            await page.goto(f"https://jzsc.mohurd.gov.cn/data/company/detail/{s0['qy_id']}", timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            # compDetail
            cipher = await page.evaluate(
                """async ({compId}) => {
                  const url = `/APi/webApi/dataservice/query/comp/compDetail?compId=${compId}`;
                  const resp = await fetch(url, {credentials: 'include', headers: {v:'231012', accessToken:''}});
                  return await resp.text();
                }""",
                {"compId": s0['qy_id']},
            )
            obj = _decode(cipher) or {}
            print(f"  compDetail compId={s0['qy_id'][:20]}... code={obj.get('code')} keys={list((obj.get('data') or {}).keys())[:10]}")
            if isinstance(obj.get("data"), dict):
                d = obj["data"]
                for k in ("QY_ID", "QY_NAME", "QY_ORG_CODE", "QY_FR_NAME", "QY_REGION_NAME", "APT_CERT_TOTAL"):
                    if k in d:
                        print(f"    {k}: {d[k]}")

            # regStaffList
            cipher = await page.evaluate(
                """async ({compId}) => {
                  const url = `/APi/webApi/dataservice/query/comp/regStaffList?compId=${compId}&pg=0&pgsz=15`;
                  const resp = await fetch(url, {credentials: 'include', headers: {v:'231012', accessToken:''}});
                  return await resp.text();
                }""",
                {"compId": s0['qy_id']},
            )
            obj = _decode(cipher) or {}
            data = obj.get("data", {})
            if isinstance(data, dict):
                total = data.get("total", "?")
                rows = data.get("list") or []
                print(f"  regStaffList compId={s0['qy_id'][:20]}... total={total} rows={len(rows)}")
                for r in rows[:3]:
                    print(f"    {r.get('RY_NAME','')} | {r.get('REG_TYPE_NAME','')} | {r.get('REG_SEAL_CODE','')}")
            else:
                print(f"  regStaffList: unexpected response {str(data)[:100]}")

            # compPerformanceListSys
            cipher = await page.evaluate(
                """async ({compId}) => {
                  const url = `/APi/webApi/dataservice/query/comp/compPerformanceListSys?compId=${compId}&pg=0&pgsz=15`;
                  const resp = await fetch(url, {credentials: 'include', headers: {v:'231012', accessToken:''}});
                  return await resp.text();
                }""",
                {"compId": s0['qy_id']},
            )
            obj = _decode(cipher) or {}
            data = obj.get("data", {})
            if isinstance(data, dict):
                total = data.get("total", "?")
                rows = data.get("list") or []
                print(f"  compPerformanceListSys compId={s0['qy_id'][:20]}... total={total} rows={len(rows)}")
                for r in rows[:3]:
                    print(f"    {r.get('PRJNAME','')[:40]} | {r.get('PRJNUM','')[:15]}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
