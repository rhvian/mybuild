from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path


PROVINCE_CODE_TO_NAME = {
    "110000": "北京", "120000": "天津", "130000": "河北", "140000": "山西",
    "150000": "内蒙古", "210000": "辽宁", "220000": "吉林", "230000": "黑龙江",
    "310000": "上海", "320000": "江苏", "330000": "浙江", "340000": "安徽",
    "350000": "福建", "360000": "江西", "370000": "山东", "410000": "河南",
    "420000": "湖北", "430000": "湖南", "440000": "广东", "450000": "广西",
    "460000": "海南", "500000": "重庆", "510000": "四川", "520000": "贵州",
    "530000": "云南", "540000": "西藏", "610000": "陕西", "620000": "甘肃",
    "630000": "青海", "640000": "宁夏", "650000": "新疆",
}


def _rows(cur: sqlite3.Cursor, entity_type: str, limit_each: int):
    rows = cur.execute(
        """
        SELECT
          id,
          run_id,
          name,
          uscc,
          project_code,
          event_date,
          status,
          city_name,
          source_url,
          raw_payload_json
        FROM normalized_entity
        WHERE entity_type = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (entity_type, limit_each),
    ).fetchall()
    result = []
    for r in rows:
        payload = json.loads(r["raw_payload_json"] or "{}")
        result.append(
            {
                "id": r["id"],
                "run_id": r["run_id"],
                "name": r["name"],
                "uscc": r["uscc"],
                "project_code": r["project_code"],
                "event_date": r["event_date"],
                "status": r["status"],
                "city_name": r["city_name"],
                "source_url": r["source_url"],
                "payload": payload,
            }
        )
    return result


def _build_stats(cur: sqlite3.Cursor) -> dict:
    """汇总整个 DB 的累计统计，用于首页和 dashboard。"""
    total_by_type = {}
    for r in cur.execute(
        "SELECT entity_type, COUNT(*) FROM normalized_entity GROUP BY entity_type"
    ):
        total_by_type[r[0]] = r[1]

    province_enterprise = []
    rows = cur.execute(
        """
        SELECT province_code, COUNT(*) as cnt
        FROM normalized_entity
        WHERE entity_type='enterprise'
        GROUP BY province_code
        ORDER BY cnt DESC
        """
    ).fetchall()
    for r in rows:
        code = r[0] or "000000"
        province_enterprise.append({
            "province_code": code,
            "province_name": PROVINCE_CODE_TO_NAME.get(code, code),
            "count": r[1],
        })

    recent_runs = []
    for r in cur.execute(
        """
        SELECT run_id, started_at, ended_at, raw_count, normalized_count, issue_count
        FROM ingestion_run
        ORDER BY rowid DESC LIMIT 14
        """
    ):
        recent_runs.append({
            "run_id": r[0],
            "started_at": r[1],
            "ended_at": r[2],
            "raw_count": r[3],
            "normalized_count": r[4],
            "issue_count": r[5],
        })

    staff_types = []
    staff_type_counter = Counter()
    for r in cur.execute(
        """
        SELECT raw_payload_json FROM normalized_entity
        WHERE entity_type='staff'
        """
    ):
        try:
            payload = json.loads(r[0] or "{}")
            t = (payload.get("register_type") or "").strip()
            if t:
                staff_type_counter[t] += 1
        except Exception:
            pass
    for name, cnt in staff_type_counter.most_common(20):
        staff_types.append({"register_type": name, "count": cnt})

    return {
        "total_by_type": total_by_type,
        "total_enterprise": total_by_type.get("enterprise", 0),
        "total_staff": total_by_type.get("staff", 0),
        "total_tender": total_by_type.get("tender", 0),
        "province_enterprise": province_enterprise,
        "staff_register_type": staff_types,
        "recent_runs": recent_runs,
    }


def export_live_json(
    db_path: Path,
    output_path: Path,
    limit_each: int = 500,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    run = cur.execute("SELECT run_id, ended_at FROM ingestion_run ORDER BY rowid DESC LIMIT 1").fetchone()
    if run is None:
        data = {
            "run_id": "",
            "updated_at": "",
            "stats": {},
            "enterprise": [],
            "staff": [],
            "tender": [],
        }
    else:
        run_id = run["run_id"]
        data = {
            "run_id": run_id,
            "updated_at": run["ended_at"],
            "stats": _build_stats(cur),
            # 各实体默认仅导出最近 limit_each 条，避免 live-data.json 持续膨胀。
            "enterprise": _rows(cur, "enterprise", limit_each),
            # staff 仍受硬上限保护（防止被外部调用传入过大值）
            "staff": _rows(cur, "staff", min(limit_each, 5000)),
            # tender 同上
            "tender": _rows(cur, "tender", min(limit_each, 5000)),
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.close()


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    db_path = project_root / "collector" / "data" / "collector.db"
    output_path = project_root / "scripts" / "live-data.json"
    export_live_json(db_path=db_path, output_path=output_path, limit_each=500)
    print(f"[export] live data written to: {output_path}")


if __name__ == "__main__":
    main()
