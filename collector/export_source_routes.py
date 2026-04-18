from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def _normalize_category(category: str) -> str:
    c = (category or "other").strip().lower()
    if c in {"enterprise", "staff", "project", "tender", "credit", "other"}:
        return c
    return "other"


def export_source_routes_json(
    db_path: Path,
    output_path: Path,
    limit_each: int = 600,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    run = cur.execute("SELECT run_id, ended_at FROM ingestion_run ORDER BY rowid DESC LIMIT 1").fetchone()

    rows = cur.execute(
        """
        SELECT
          id,
          source_id,
          source_level,
          city_name,
          province_code,
          name,
          source_url,
          raw_payload_json
        FROM normalized_entity
        WHERE entity_type IN ('portal_entry', 'entry_probe_link')
        ORDER BY id DESC
        """
    ).fetchall()

    bucket: Dict[str, Dict[Tuple[str, str], dict]] = {
        "enterprise": {},
        "staff": {},
        "project": {},
        "tender": {},
        "credit": {},
        "other": {},
    }

    for r in rows:
        payload = json.loads(r["raw_payload_json"] or "{}")
        category = _normalize_category(str(payload.get("entry_category", "other")))
        url = str(payload.get("entry_url") or r["source_url"] or "").strip()
        if not url.startswith("http"):
            continue
        title = str(payload.get("name") or r["name"] or "").strip() or url
        city_name = str(r["city_name"] or "").strip()
        key = (url, city_name)

        cur_bucket = bucket[category]
        item = cur_bucket.get(key)
        if item is None:
            cur_bucket[key] = {
                "url": url,
                "title": title,
                "category": category,
                "source_id": r["source_id"],
                "source_level": r["source_level"],
                "city_name": city_name,
                "province_code": r["province_code"],
                "weight": 1,
            }
        else:
            item["weight"] += 1

    routes: Dict[str, List[dict]] = {}
    for category, values in bucket.items():
        items = sorted(
            values.values(),
            key=lambda x: (x["weight"], x["source_level"], x["city_name"]),
            reverse=True,
        )[:limit_each]
        routes[category] = items

    data = {
        "run_id": run["run_id"] if run else "",
        "updated_at": run["ended_at"] if run else "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "routes": routes,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.close()


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    db_path = project_root / "collector" / "data" / "collector.db"
    output_path = project_root / "scripts" / "source-routes.json"
    export_source_routes_json(db_path=db_path, output_path=output_path)
    print(f"[export] source routes written to: {output_path}")


if __name__ == "__main__":
    main()
