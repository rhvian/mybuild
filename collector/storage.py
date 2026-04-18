from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .models import (
    NormalizedEntity,
    QualityIssue,
    RawRecord,
    SourceDefinition,
    SourceFailure,
)


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS source_registry (
  source_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_level TEXT NOT NULL,
  base_url TEXT NOT NULL,
  province_code TEXT,
  city_code TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ingestion_run (
  run_id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  ended_at TEXT NOT NULL,
  source_count INTEGER NOT NULL,
  raw_count INTEGER NOT NULL,
  normalized_count INTEGER NOT NULL,
  issue_count INTEGER NOT NULL,
  failed_source_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS raw_record (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_level TEXT NOT NULL,
  source_url TEXT NOT NULL,
  record_type TEXT NOT NULL,
  province_code TEXT NOT NULL,
  city_code TEXT NOT NULL,
  city_name TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS normalized_entity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  entity_key TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  name TEXT NOT NULL,
  uscc TEXT,
  project_code TEXT,
  city_code TEXT NOT NULL,
  city_name TEXT NOT NULL,
  province_code TEXT NOT NULL,
  score INTEGER NOT NULL,
  risk_level TEXT NOT NULL,
  status TEXT NOT NULL,
  event_date TEXT,
  source_id TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_level TEXT NOT NULL,
  evidence_hash TEXT NOT NULL,
  raw_payload_json TEXT NOT NULL,
  UNIQUE(entity_key, source_id, event_date)
);

CREATE TABLE IF NOT EXISTS quality_issue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  entity_key TEXT NOT NULL,
  issue_code TEXT NOT NULL,
  issue_message TEXT NOT NULL,
  severity TEXT NOT NULL,
  detected_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_cursor (
  source_id TEXT PRIMARY KEY,
  cursor_value TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS source_failure_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_name TEXT NOT NULL,
  error_type TEXT NOT NULL,
  error_message TEXT NOT NULL,
  attempts INTEGER NOT NULL,
  failed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runner_lock (
  lock_name TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  acquired_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_normalized_city ON normalized_entity(city_code);
CREATE INDEX IF NOT EXISTS idx_normalized_uscc ON normalized_entity(uscc);
CREATE INDEX IF NOT EXISTS idx_quality_run ON quality_issue(run_id);
CREATE INDEX IF NOT EXISTS idx_failure_run ON source_failure_log(run_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    _migrate_schema(conn)
    conn.commit()


def _migrate_schema(conn: sqlite3.Connection) -> None:
    # Keep backward compatibility for existing database files.
    _ensure_column(
        conn,
        table="ingestion_run",
        column="failed_source_count",
        ddl="INTEGER NOT NULL DEFAULT 0",
    )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {row["name"] for row in rows}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def upsert_sources(conn: sqlite3.Connection, sources: Iterable[SourceDefinition]) -> None:
    source_list = list(sources)
    source_ids = [source.source_id for source in source_list]

    if source_ids:
        placeholders = ",".join(["?"] * len(source_ids))
        conn.execute(
            f"UPDATE source_registry SET enabled = 0, updated_at = datetime('now') "
            f"WHERE source_id NOT IN ({placeholders})",
            source_ids,
        )
    else:
        conn.execute("UPDATE source_registry SET enabled = 0, updated_at = datetime('now')")

    conn.executemany(
        """
        INSERT INTO source_registry (
          source_id, name, source_type, source_level, base_url, province_code, city_code, enabled, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(source_id) DO UPDATE SET
          name=excluded.name,
          source_type=excluded.source_type,
          source_level=excluded.source_level,
          base_url=excluded.base_url,
          province_code=excluded.province_code,
          city_code=excluded.city_code,
          enabled=excluded.enabled,
          updated_at=datetime('now')
        """,
        [
            (
                source.source_id,
                source.name,
                source.source_type,
                source.source_level,
                source.base_url,
                source.province_code,
                source.city_code,
                1 if source.enabled else 0,
            )
            for source in source_list
        ],
    )
    conn.commit()


def read_enabled_sources(conn: sqlite3.Connection) -> List[SourceDefinition]:
    rows = conn.execute(
        """
        SELECT source_id, name, source_type, source_level, base_url, province_code, city_code, enabled
        FROM source_registry
        WHERE enabled = 1
        ORDER BY source_id
        """
    ).fetchall()
    return [
        SourceDefinition(
            source_id=row["source_id"],
            name=row["name"],
            source_type=row["source_type"],
            source_level=row["source_level"],
            base_url=row["base_url"],
            province_code=row["province_code"],
            city_code=row["city_code"],
            enabled=bool(row["enabled"]),
        )
        for row in rows
    ]


def insert_raw_records(conn: sqlite3.Connection, run_id: str, records: Iterable[RawRecord]) -> int:
    records_list = list(records)
    conn.executemany(
        """
        INSERT INTO raw_record (
          run_id, source_id, source_name, source_level, source_url, record_type, province_code, city_code, city_name,
          captured_at, payload_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                run_id,
                record.source_id,
                record.source_name,
                record.source_level,
                record.source_url,
                record.record_type,
                record.province_code,
                record.city_code,
                record.city_name,
                record.captured_at,
                json.dumps(record.payload, ensure_ascii=False),
            )
            for record in records_list
        ],
    )
    conn.commit()
    return len(records_list)


def upsert_normalized(conn: sqlite3.Connection, run_id: str, entities: Iterable[NormalizedEntity]) -> int:
    entities_list = list(entities)
    conn.executemany(
        """
        INSERT INTO normalized_entity (
          run_id, entity_key, entity_type, name, uscc, project_code, city_code, city_name, province_code,
          score, risk_level, status, event_date, source_id, source_url, source_level, evidence_hash, raw_payload_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_key, source_id, event_date) DO UPDATE SET
          run_id=excluded.run_id,
          entity_type=excluded.entity_type,
          name=excluded.name,
          uscc=excluded.uscc,
          project_code=excluded.project_code,
          city_code=excluded.city_code,
          city_name=excluded.city_name,
          province_code=excluded.province_code,
          score=excluded.score,
          risk_level=excluded.risk_level,
          status=excluded.status,
          source_url=excluded.source_url,
          source_level=excluded.source_level,
          evidence_hash=excluded.evidence_hash,
          raw_payload_json=excluded.raw_payload_json
        """,
        [
            (
                run_id,
                entity.entity_key,
                entity.entity_type,
                entity.name,
                entity.uscc,
                entity.project_code,
                entity.city_code,
                entity.city_name,
                entity.province_code,
                entity.score,
                entity.risk_level,
                entity.status,
                entity.event_date,
                entity.source_id,
                entity.source_url,
                entity.source_level,
                entity.evidence_hash,
                json.dumps(entity.raw_payload, ensure_ascii=False),
            )
            for entity in entities_list
        ],
    )
    conn.commit()
    return len(entities_list)


def insert_quality_issues(conn: sqlite3.Connection, run_id: str, issues: Iterable[QualityIssue]) -> int:
    issues_list = list(issues)
    if not issues_list:
        return 0
    conn.executemany(
        """
        INSERT INTO quality_issue (
          run_id, source_id, entity_key, issue_code, issue_message, severity, detected_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                run_id,
                issue.source_id,
                issue.entity_key,
                issue.issue_code,
                issue.issue_message,
                issue.severity,
                issue.detected_at,
            )
            for issue in issues_list
        ],
    )
    conn.commit()
    return len(issues_list)


def insert_run_summary(
    conn: sqlite3.Connection,
    run_id: str,
    started_at: str,
    ended_at: str,
    source_count: int,
    raw_count: int,
    normalized_count: int,
    issue_count: int,
    failed_source_count: int,
) -> None:
    conn.execute(
        """
        INSERT INTO ingestion_run (
          run_id, started_at, ended_at, source_count, raw_count, normalized_count, issue_count, failed_source_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            started_at,
            ended_at,
            source_count,
            raw_count,
            normalized_count,
            issue_count,
            failed_source_count,
        ),
    )
    conn.commit()


def read_source_cursors(conn: sqlite3.Connection) -> Dict[str, str]:
    rows = conn.execute("SELECT source_id, cursor_value FROM source_cursor").fetchall()
    return {row["source_id"]: row["cursor_value"] for row in rows if row["cursor_value"]}


def upsert_source_cursors(conn: sqlite3.Connection, cursors: Dict[str, str]) -> None:
    if not cursors:
        return
    conn.executemany(
        """
        INSERT INTO source_cursor (source_id, cursor_value, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(source_id) DO UPDATE SET
          cursor_value=excluded.cursor_value,
          updated_at=datetime('now')
        """,
        [(source_id, cursor_value) for source_id, cursor_value in cursors.items()],
    )
    conn.commit()


def insert_source_failures(conn: sqlite3.Connection, run_id: str, failures: Iterable[SourceFailure]) -> int:
    failures_list = list(failures)
    if not failures_list:
        return 0
    conn.executemany(
        """
        INSERT INTO source_failure_log (
          run_id, source_id, source_name, error_type, error_message, attempts, failed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                run_id,
                failure.source_id,
                failure.source_name,
                failure.error_type,
                failure.error_message,
                failure.attempts,
                failure.failed_at,
            )
            for failure in failures_list
        ],
    )
    conn.commit()
    return len(failures_list)


def read_run_lock(conn: sqlite3.Connection, lock_name: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT lock_name, owner_id, acquired_at, expires_at
        FROM runner_lock
        WHERE lock_name = ?
        """,
        (lock_name,),
    ).fetchone()


def acquire_run_lock(
    conn: sqlite3.Connection,
    lock_name: str,
    owner_id: str,
    ttl_seconds: int = 1800,
) -> bool:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl_seconds)
    now_iso = now.isoformat()
    expires_iso = expires.isoformat()

    # Remove stale lock first.
    conn.execute(
        """
        DELETE FROM runner_lock
        WHERE lock_name = ?
          AND expires_at < ?
        """,
        (lock_name, now_iso),
    )

    try:
        conn.execute(
            """
            INSERT INTO runner_lock (lock_name, owner_id, acquired_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (lock_name, owner_id, now_iso, expires_iso),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def force_release_run_lock(conn: sqlite3.Connection, lock_name: str) -> int:
    cursor = conn.execute(
        """
        DELETE FROM runner_lock
        WHERE lock_name = ?
        """,
        (lock_name,),
    )
    conn.commit()
    return int(cursor.rowcount or 0)


def release_run_lock(conn: sqlite3.Connection, lock_name: str, owner_id: str) -> None:
    conn.execute(
        """
        DELETE FROM runner_lock
        WHERE lock_name = ?
          AND owner_id = ?
        """,
        (lock_name, owner_id),
    )
    conn.commit()
