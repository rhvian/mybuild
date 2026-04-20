"""
模拟 UI 真实交互 — 打开 /data/person，填入筛选条件，点击搜索，
观察 JS 实际发起的 API 请求完整信息（URL / method / headers / body）

用法：python3 collector/scripts/probe_ui_interaction.py
"""
from __future__ import annotations

import asyncio
import json

from playwright.async_api import async_playwright


async def main() -> None:
    captured_requests: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--ignore-certificate-errors", "--allow-running-insecure-content"],
        )
        ctx = await browser.new_context(ignore_https_errors=True)
        page = await ctx.new_page()

        # 拦截所有发往 /dataservice/query/ 的 API 请求
        def _on_request(req):
            if "dataservice/query" in req.url:
                captured_requests.append({
                    "url": req.url,
                    "method": req.method,
                    "headers": dict(req.headers),
                    "post_data": req.post_data,
                })

        page.on("request", _on_request)

        async def _inspect_page(target_url: str, label: str):
            print(f"\n========== {label} ==========")
            captured_requests.clear()
            await page.goto(target_url, timeout=60000, wait_until="networkidle")
            await page.wait_for_timeout(3000)
            print(f"[initial] {len(captured_requests)} requests")
            for r in captured_requests[-3:]:
                print(f"  {r['method']} {r['url']}")
                if r["post_data"]:
                    print(f"    body: {r['post_data'][:200]}")

            # 尝试填入筛选条件并触发搜索
            # person 页：姓名、身份证、注册号、注册单位、人员类别
            # project 页：项目名、建设单位
            captured_requests.clear()

            if "person" in target_url:
                inputs_to_try = [
                    ("input[placeholder*='姓名']", "张伟"),
                    ("input[placeholder*='身份证']", ""),
                    ("input[placeholder*='注册单位']", "中建"),
                ]
            elif "project" in target_url:
                inputs_to_try = [
                    ("input[placeholder*='项目']", "住宅"),
                    ("input[placeholder*='建设']", ""),
                ]
            else:
                inputs_to_try = []

            for selector, value in inputs_to_try:
                if not value:
                    continue
                try:
                    loc = page.locator(selector).first
                    if await loc.count() > 0:
                        await loc.fill(value)
                        await page.wait_for_timeout(300)
                        print(f"  filled {selector}={value}")
                except Exception as e:
                    print(f"  fill failed: {e}")

            # 点击搜索按钮
            try:
                btn = page.locator("#query-btn").first
                if await btn.count() > 0:
                    await btn.click()
                    await page.wait_for_timeout(5000)
                    print(f"[after search] {len(captured_requests)} requests")
                    for r in captured_requests:
                        print(f"  {r['method']} {r['url']}")
                        if r["post_data"]:
                            print(f"    body: {r['post_data']}")
                else:
                    print("  no #query-btn found")
            except Exception as e:
                print(f"  click failed: {e}")

        await _inspect_page("https://jzsc.mohurd.gov.cn/data/person", "人员查询页")
        await _inspect_page("https://jzsc.mohurd.gov.cn/data/project", "项目查询页")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
