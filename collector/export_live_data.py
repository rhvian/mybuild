from __future__ import annotations

import json
import sqlite3
from pathlib import Path


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


def export_live_json(
    db_path: Path,
    output_path: Path,
    limit_each: int = 200,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    run = cur.execute("SELECT run_id, ended_at FROM ingestion_run ORDER BY rowid DESC LIMIT 1").fetchone()
    if run is None:
        data = {"run_id": "", "updated_at": "", "enterprise": [], "staff": [], "tender": []}
    else:
        run_id = run["run_id"]
        data = {
            "run_id": run_id,
            "updated_at": run["ended_at"],
            "enterprise": _rows(cur, "enterprise", limit_each),
            "staff": _rows(cur, "staff", limit_each),
            "tender": _rows(cur, "tender", limit_each),
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.close()


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    db_path = project_root / "collector" / "data" / "collector.db"
    output_path = project_root / "scripts" / "live-data.json"
    export_live_json(db_path=db_path, output_path=output_path, limit_each=6000)
    print(f"[export] live data written to: {output_path}")


if __name__ == "__main__":
    main()
