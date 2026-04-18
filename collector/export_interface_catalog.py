from __future__ import annotations

import argparse
import json
import re
import sqlite3
import ssl
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


SCRIPT_SRC_RE = re.compile(r"<script[^>]*\bsrc=['\"]([^'\"]+)['\"][^>]*>", re.I)
FETCH_RE = re.compile(r"(?:fetch|axios\.(?:get|post|request))\s*\(\s*['\"]([^'\"]+)['\"]", re.I)
AJAX_URL_RE = re.compile(r"\burl\s*:\s*['\"]([^'\"]+)['\"]", re.I)
ABSOLUTE_URL_RE = re.compile(r"['\"](https?://[^'\"\s]+)['\"]", re.I)
RELATIVE_URL_RE = re.compile(r"['\"](/[^'\"\s]{1,280})['\"]")
ATTR_URL_RE = re.compile(r"\b(?:href|action|data-url)\s*=\s*['\"]([^'\"]+)['\"]", re.I)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)

ENDPOINT_HINTS = (
    "/api",
    "api/",
    "webapi",
    "dataservice",
    "query/",
    "/query",
    "service/",
    "/service",
    "rest/",
    "/rest",
    ".ashx",
    ".asmx",
    ".do",
    ".action",
    ".json",
)

ASSET_SUFFIXES = (
    ".js",
    ".mjs",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".ico",
    ".map",
    ".mp4",
    ".mp3",
    ".pdf",
    ".zip",
    ".rar",
    ".7z",
)


@dataclass(slots=True)
class PageTarget:
    url: str
    source_id: str
    province_code: str
    city_code: str
    city_name: str
    category: str
    weight: int


def _normalize_category(category: str) -> str:
    c = (category or "").strip().lower()
    if c in {"enterprise", "staff", "project", "tender", "credit", "other"}:
        return c
    return "other"


def _guess_category(*parts: str) -> str:
    text = " ".join(parts).lower()
    if any(k in text for k in ("企业", "company", "enterprise", "comp")):
        return "enterprise"
    if any(k in text for k in ("人员", "staff", "person", "ry_")):
        return "staff"
    if any(k in text for k in ("项目", "project", "prj")):
        return "project"
    if any(k in text for k in ("招标", "投标", "tender", "bid")):
        return "tender"
    if any(k in text for k in ("信用", "诚信", "credit")):
        return "credit"
    return "other"


def _fetch_html(url: str, timeout_sec: int) -> Tuple[str, str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec, context=ctx) as resp:
            body = resp.read(1_500_000)
            final_url = resp.geturl()
            return body.decode("utf-8", "ignore"), final_url, ""
    except Exception as exc:  # noqa: BLE001
        return "", url, str(exc)


def _clean_url(raw: str, base_url: str) -> str:
    val = (raw or "").strip().replace("&amp;", "&")
    if not val or val.startswith(("javascript:", "#", "mailto:")):
        return ""
    abs_url = urllib.parse.urljoin(base_url, val)
    if not abs_url.startswith("http"):
        return ""
    return abs_url[:600]


def _looks_like_endpoint(url: str) -> bool:
    u = (url or "").lower()
    if any(u.endswith(s) for s in ASSET_SUFFIXES):
        return False
    return any(h in u for h in ENDPOINT_HINTS) or "?" in u


def _confidence(url: str, signal: str) -> str:
    u = url.lower()
    if signal in {"fetch_call", "ajax_url"}:
        return "high"
    if any(h in u for h in ENDPOINT_HINTS):
        return "high"
    if signal in {"absolute_url", "relative_url", "attr_url"} and "?" in u:
        return "medium"
    return "low"


def _extract_title(html: str) -> str:
    m = TITLE_RE.search(html)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _extract_endpoint_observations(
    html: str,
    base_url: str,
    source_category: str,
) -> List[Dict]:
    observations: List[Dict] = []
    seen = set()

    def _push(signal: str, raw_url: str) -> None:
        endpoint_url = _clean_url(raw_url, base_url)
        if not endpoint_url:
            return
        if not _looks_like_endpoint(endpoint_url):
            return
        key = (endpoint_url, signal)
        if key in seen:
            return
        seen.add(key)
        observations.append(
            {
                "endpoint_url": endpoint_url,
                "signal": signal,
                "confidence": _confidence(endpoint_url, signal),
                "category": _normalize_category(_guess_category(source_category, endpoint_url)),
            }
        )

    for m in SCRIPT_SRC_RE.finditer(html):
        _push("script_src", m.group(1))
    for m in FETCH_RE.finditer(html):
        _push("fetch_call", m.group(1))
    for m in AJAX_URL_RE.finditer(html):
        _push("ajax_url", m.group(1))
    for m in ABSOLUTE_URL_RE.finditer(html):
        _push("absolute_url", m.group(1))
    for m in RELATIVE_URL_RE.finditer(html):
        _push("relative_url", m.group(1))
    for m in ATTR_URL_RE.finditer(html):
        _push("attr_url", m.group(1))

    return observations


def _load_targets(db_path: Path, max_pages: int) -> Tuple[str, List[PageTarget]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    run = cur.execute("SELECT run_id FROM ingestion_run ORDER BY rowid DESC LIMIT 1").fetchone()
    if run is None:
        conn.close()
        return "", []
    run_id = str(run["run_id"])

    rows = cur.execute(
        """
        SELECT
          source_id,
          source_url,
          province_code,
          city_code,
          city_name,
          name,
          raw_payload_json
        FROM normalized_entity
        WHERE run_id = ?
          AND entity_type IN ('portal_entry', 'entry_probe_link', 'entry_probe')
        ORDER BY id DESC
        """,
        (run_id,),
    ).fetchall()
    conn.close()

    bucket: Dict[str, PageTarget] = {}

    for r in rows:
        payload = json.loads(r["raw_payload_json"] or "{}")
        candidates = [
            payload.get("entry_url"),
            payload.get("probe_url"),
            r["source_url"],
        ]
        category = _normalize_category(
            str(payload.get("entry_category") or payload.get("probe_category") or _guess_category(r["name"], r["source_url"]))
        )

        for candidate in candidates:
            c = _clean_url(str(candidate or ""), str(r["source_url"] or ""))
            if not c:
                continue
            item = bucket.get(c)
            if item is None:
                bucket[c] = PageTarget(
                    url=c,
                    source_id=str(r["source_id"] or ""),
                    province_code=str(r["province_code"] or ""),
                    city_code=str(r["city_code"] or ""),
                    city_name=str(r["city_name"] or ""),
                    category=category,
                    weight=1,
                )
            else:
                item.weight += 1

    items = sorted(bucket.values(), key=lambda x: x.weight, reverse=True)
    if max_pages > 0:
        items = items[:max_pages]
    return run_id, items


def export_interface_catalog(
    db_path: Path,
    output_path: Path,
    max_pages: int = 600,
    workers: int = 12,
    timeout_sec: int = 18,
) -> Dict:
    run_id, targets = _load_targets(db_path=db_path, max_pages=max_pages)

    observations: List[Dict] = []
    failed_pages: List[Dict] = []
    pages: List[Dict] = []
    endpoint_agg: Dict[str, Dict] = {}
    category_counts: Dict[str, int] = {}

    def _scan_one(target: PageTarget) -> Dict:
        html, final_url, err = _fetch_html(target.url, timeout_sec=timeout_sec)
        if err:
            return {
                "ok": False,
                "target": target,
                "final_url": final_url,
                "error": err,
                "title": "",
                "observations": [],
            }
        title = _extract_title(html)
        obs = _extract_endpoint_observations(
            html=html,
            base_url=final_url,
            source_category=target.category,
        )
        return {
            "ok": True,
            "target": target,
            "final_url": final_url,
            "error": "",
            "title": title,
            "observations": obs,
        }

    max_workers = max(1, min(workers, len(targets) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_map = {ex.submit(_scan_one, t): t for t in targets}
        for fut in as_completed(fut_map):
            res = fut.result()
            target: PageTarget = res["target"]
            page_info = {
                "url": target.url,
                "final_url": res["final_url"],
                "source_id": target.source_id,
                "province_code": target.province_code,
                "city_code": target.city_code,
                "city_name": target.city_name,
                "category": target.category,
                "weight": target.weight,
                "title": res["title"],
                "endpoint_count": len(res["observations"]),
                "error": res["error"],
            }
            pages.append(page_info)

            if not res["ok"]:
                failed_pages.append(page_info)
                continue

            for obs in res["observations"]:
                row = {
                    "endpoint_url": obs["endpoint_url"],
                    "page_url": res["final_url"],
                    "page_title": res["title"],
                    "signal": obs["signal"],
                    "confidence": obs["confidence"],
                    "category": obs["category"],
                    "source_id": target.source_id,
                    "province_code": target.province_code,
                    "city_code": target.city_code,
                    "city_name": target.city_name,
                }
                observations.append(row)
                category_counts[row["category"]] = category_counts.get(row["category"], 0) + 1

                agg = endpoint_agg.get(row["endpoint_url"])
                if agg is None:
                    endpoint_agg[row["endpoint_url"]] = {
                        "endpoint_url": row["endpoint_url"],
                        "category": row["category"],
                        "confidence": row["confidence"],
                        "observations": 1,
                        "sources": {row["source_id"]},
                        "province_codes": {row["province_code"]},
                        "city_names": {row["city_name"]},
                        "signals": {row["signal"]},
                        "sample_pages": [row["page_url"]],
                    }
                else:
                    agg["observations"] += 1
                    agg["sources"].add(row["source_id"])
                    agg["province_codes"].add(row["province_code"])
                    agg["city_names"].add(row["city_name"])
                    agg["signals"].add(row["signal"])
                    if len(agg["sample_pages"]) < 8 and row["page_url"] not in agg["sample_pages"]:
                        agg["sample_pages"].append(row["page_url"])
                    if row["confidence"] == "high":
                        agg["confidence"] = "high"
                    elif row["confidence"] == "medium" and agg["confidence"] == "low":
                        agg["confidence"] = "medium"

    endpoints = sorted(
        [
            {
                "endpoint_url": item["endpoint_url"],
                "category": item["category"],
                "confidence": item["confidence"],
                "observations": item["observations"],
                "source_count": len(item["sources"]),
                "province_codes": sorted([v for v in item["province_codes"] if v]),
                "city_names": sorted([v for v in item["city_names"] if v])[:20],
                "signals": sorted(item["signals"]),
                "sample_pages": item["sample_pages"],
            }
            for item in endpoint_agg.values()
        ],
        key=lambda x: (x["observations"], x["confidence"], x["source_count"]),
        reverse=True,
    )

    data = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "page_target_count": len(targets),
        "pages_scanned": len(pages),
        "pages_failed": len(failed_pages),
        "endpoint_observation_count": len(observations),
        "endpoint_unique_count": len(endpoints),
        "category_counts": category_counts,
        "endpoints": endpoints,
        "failed_pages": failed_pages,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export interface candidates from latest run portal pages.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=600)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=18)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    data = export_interface_catalog(
        db_path=args.db,
        output_path=args.output,
        max_pages=args.max_pages,
        workers=args.workers,
        timeout_sec=args.timeout,
    )
    print(
        f"[export-interface] run_id={data['run_id']} "
        f"pages={data['pages_scanned']} failed={data['pages_failed']} "
        f"endpoint_unique={data['endpoint_unique_count']}"
    )
    print(f"[export-interface] written: {args.output}")


if __name__ == "__main__":
    main()
