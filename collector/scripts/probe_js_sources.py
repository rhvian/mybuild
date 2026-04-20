"""
JZSC JS 源码扫描 — 找出 staff / project API 的真实参数名

用法：python3 collector/scripts/probe_js_sources.py
不启动采集，仅爬取 JS 文件并分析。

输出：
  - /tmp/jzsc_js_dump.txt  所有 JS 源码拼接
  - 终端打印匹配到的 API 调用行（含上下文）
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from playwright.async_api import async_playwright


async def main() -> None:
    js_sources: list[tuple[str, str]] = []  # (url, content)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--ignore-certificate-errors", "--allow-running-insecure-content"],
        )
        ctx = await browser.new_context(ignore_https_errors=True)
        page = await ctx.new_page()

        # 拦截所有 JS 请求
        async def _capture_response(resp):
            url = resp.url
            if url.endswith(".js") or "script" in (resp.headers.get("content-type", "") or ""):
                try:
                    body = await resp.text()
                    js_sources.append((url, body))
                except Exception:
                    pass

        page.on("response", lambda r: asyncio.create_task(_capture_response(r)))

        for target in [
            "https://jzsc.mohurd.gov.cn/data/person",
            "https://jzsc.mohurd.gov.cn/data/project",
            "https://jzsc.mohurd.gov.cn/data/company",
        ]:
            print(f"\n==== {target} ====")
            await page.goto(target, timeout=60000, wait_until="networkidle")
            await page.wait_for_timeout(3000)

        await browser.close()

    print(f"\nCaptured {len(js_sources)} JS files, total {sum(len(c) for _, c in js_sources)} bytes")

    # Dump 全部到文件
    out = Path("/tmp/jzsc_js_dump.txt")
    with out.open("w", encoding="utf-8") as f:
        for url, body in js_sources:
            f.write(f"\n\n===== {url} =====\n\n")
            f.write(body)
    print(f"Dumped to {out}")

    # 搜索 API 关键字
    patterns = [
        r"staff/list[^'\"]*",
        r"project/list[^'\"]*",
        r"comp/list[^'\"]*",
        r"query/staff/[^'\"]+",
        r"query/project/[^'\"]+",
        r"query/comp/[^'\"]+",
    ]
    print("\n==== API endpoint matches ====")
    seen: set[str] = set()
    for url, body in js_sources:
        for pat in patterns:
            for m in re.finditer(pat, body):
                match = m.group(0)
                if match in seen:
                    continue
                seen.add(match)
                # 取上下文
                start = max(0, m.start() - 120)
                end = min(len(body), m.end() + 120)
                ctx_text = body[start:end].replace("\n", " ")
                print(f"  [{Path(url).name}] {match}")
                print(f"    ctx: ...{ctx_text}...")

    # 搜索参数名常见模式 — staff 相关
    print("\n==== 可能的参数名 ====")
    param_patterns = [
        r"(ry_\w+)",            # ry_name, ry_region etc
        r"(qy_\w+)",            # qy_region, qy_name etc
        r"(reg_\w+)",           # reg_type, reg_qymc etc
        r"(apt_\w+)",           # apt_root, apt_code etc
        r"(prj_\w+)",           # prj_region etc
        r"(build_?corp\w*)",    # buildcorpname
    ]
    all_text = "\n".join(body for _, body in js_sources)
    for pat in param_patterns:
        names = set(re.findall(pat, all_text))
        if names:
            print(f"  {pat}: {sorted(names)[:20]}")


if __name__ == "__main__":
    asyncio.run(main())
