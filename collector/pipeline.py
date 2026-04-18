from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from uuid import uuid4

from .connectors import fetch_all_sources_stable
from .models import RunSummary, SourceDefinition
from .normalizer import normalize_batch
from .quality import validate_batch
from .storage import (
    acquire_run_lock,
    connect,
    force_release_run_lock,
    init_schema,
    insert_quality_issues,
    insert_raw_records,
    insert_run_summary,
    read_run_lock,
    insert_source_failures,
    read_source_cursors,
    read_enabled_sources,
    release_run_lock,
    upsert_source_cursors,
    upsert_normalized,
    upsert_sources,
)


logger = logging.getLogger("collector.pipeline")
RUN_LOCK_NAME = "collector_pipeline"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_sources_from_json(config_path: Path) -> List[SourceDefinition]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    sources: List[SourceDefinition] = []
    for entry in payload:
        sources.append(
            SourceDefinition(
                source_id=entry["source_id"],
                name=entry["name"],
                source_type=entry["source_type"],
                source_level=entry["source_level"],
                base_url=entry["base_url"],
                province_code=entry.get("province_code"),
                city_code=entry.get("city_code"),
                enabled=bool(entry.get("enabled", True)),
            )
        )
    return sources


def bootstrap_source_registry(db_path: Path, config_path: Path) -> int:
    conn = connect(db_path)
    try:
        init_schema(conn)
        sources = load_sources_from_json(config_path)
        upsert_sources(conn, sources)
        return len(sources)
    finally:
        conn.close()


def run_pipeline(db_path: Path, force_unlock: bool = False) -> RunSummary:
    run_id = f"run_{uuid4().hex[:12]}"
    owner_id = f"owner_{uuid4().hex[:12]}"
    started_at = _utc_now_iso()

    conn = connect(db_path)
    lock_acquired = False
    try:
        init_schema(conn)
        if force_unlock:
            force_release_run_lock(conn, lock_name=RUN_LOCK_NAME)

        lock_acquired = acquire_run_lock(conn, lock_name=RUN_LOCK_NAME, owner_id=owner_id)
        if not lock_acquired:
            existing_lock = read_run_lock(conn, lock_name=RUN_LOCK_NAME)
            if existing_lock:
                raise RuntimeError(
                    "Pipeline already running: run lock not acquired "
                    f"(owner={existing_lock['owner_id']}, "
                    f"acquired_at={existing_lock['acquired_at']}, "
                    f"expires_at={existing_lock['expires_at']})"
                )
            raise RuntimeError("Pipeline already running: run lock not acquired")

        sources = read_enabled_sources(conn)
        read_source_cursors(conn)  # reserved for incremental connectors
        raw_records, source_failures = fetch_all_sources_stable(sources)
        normalized = normalize_batch(raw_records)
        quality_issues = validate_batch(normalized)

        raw_count = insert_raw_records(conn, run_id, raw_records)
        normalized_count = upsert_normalized(conn, run_id, normalized)
        issue_count = insert_quality_issues(conn, run_id, quality_issues)
        failed_source_count = insert_source_failures(conn, run_id, source_failures)
        upsert_source_cursors(
            conn,
            {source.source_id: ended_cursor() for source in sources},
        )

        ended_at = _utc_now_iso()
        insert_run_summary(
            conn=conn,
            run_id=run_id,
            started_at=started_at,
            ended_at=ended_at,
            source_count=len(sources),
            raw_count=raw_count,
            normalized_count=normalized_count,
            issue_count=issue_count,
            failed_source_count=failed_source_count,
        )
    finally:
        if lock_acquired:
            release_run_lock(conn, lock_name=RUN_LOCK_NAME, owner_id=owner_id)
        conn.close()

    logger.info(
        "pipeline_finished run_id=%s sources=%s raw=%s normalized=%s issues=%s failed_sources=%s",
        run_id,
        len(sources),
        raw_count,
        normalized_count,
        issue_count,
        failed_source_count,
    )

    return RunSummary(
        run_id=run_id,
        started_at=started_at,
        ended_at=ended_at,
        source_count=len(sources),
        raw_count=raw_count,
        normalized_count=normalized_count,
        issue_count=issue_count,
        failed_source_count=failed_source_count,
        issues=quality_issues,
        failures=source_failures,
    )


def ended_cursor() -> str:
    # Stable incremental watermark for next run.
    return _utc_now_iso()
