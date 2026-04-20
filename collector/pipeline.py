from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from uuid import uuid4

from .connectors import (
    JzscLiveConnectorBase,
    build_connector,
    fetch_all_sources_stable,
)
from .models import RawRecord, RunSummary, SourceDefinition, SourceFailure
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


def run_pipeline_streaming(
    db_path: Path,
    force_unlock: bool = False,
    source_ids: List[str] | None = None,
) -> RunSummary:
    """
    流式 pipeline：每完成一个 batch（region / source）立即 insert + commit，
    避免中断时整批数据丢失。
    进度实时打印到 stdout，方便人工观察。

    source_ids: 可选，只跑白名单里的 source_id（来自 CLI --source-id）；
                None 表示跑所有 enabled 源。
    """
    import sys

    run_id = f"run_{uuid4().hex[:12]}"
    owner_id = f"owner_{uuid4().hex[:12]}"
    started_at = _utc_now_iso()

    def _print(msg: str) -> None:
        ts = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", file=sys.stdout, flush=True)

    conn = connect(db_path)
    lock_acquired = False
    total_raw = 0
    total_normalized = 0
    total_issues = 0
    all_failures: List[SourceFailure] = []
    all_issues = []

    try:
        init_schema(conn)
        if force_unlock:
            force_release_run_lock(conn, lock_name=RUN_LOCK_NAME)

        lock_acquired = acquire_run_lock(conn, lock_name=RUN_LOCK_NAME, owner_id=owner_id)
        if not lock_acquired:
            existing_lock = read_run_lock(conn, lock_name=RUN_LOCK_NAME)
            raise RuntimeError(
                f"Pipeline already running: run lock not acquired (existing={existing_lock})"
            )

        sources = list(read_enabled_sources(conn))
        if source_ids:
            wanted = set(source_ids)
            found_ids = {s.source_id for s in sources}
            missing = wanted - found_ids
            if missing:
                _print(f"! warning: requested source_ids not enabled or not found: {sorted(missing)}")
            sources = [s for s in sources if s.source_id in wanted]
            if not sources:
                _print(f"! aborted: no matching enabled sources for {sorted(wanted)}")
                ended_at = _utc_now_iso()
                insert_run_summary(
                    conn=conn, run_id=run_id, started_at=started_at, ended_at=ended_at,
                    source_count=0, raw_count=0, normalized_count=0, issue_count=0, failed_source_count=0,
                )
                return RunSummary(
                    run_id=run_id, started_at=started_at, ended_at=ended_at,
                    source_count=0, raw_count=0, normalized_count=0, issue_count=0,
                    failed_source_count=0, issues=[], failures=[],
                )
        _print(f"run_id={run_id} sources={len(sources)} mode=streaming" + (f" filter={sorted(source_ids)}" if source_ids else ""))

        for src_idx, source in enumerate(sources, start=1):
            src_raw = 0
            src_norm = 0
            _print(f"source {src_idx}/{len(sources)} [{source.source_id}] type={source.source_type} starting")

            def _on_batch(batch_label: str, records: List[RawRecord]) -> None:
                nonlocal src_raw, src_norm, total_raw, total_normalized, total_issues
                if not records:
                    return
                raw_n = insert_raw_records(conn, run_id, records)
                normalized = normalize_batch(records)
                norm_n = upsert_normalized(conn, run_id, normalized)
                issues = validate_batch(normalized)
                insert_quality_issues(conn, run_id, issues)
                src_raw += raw_n
                src_norm += norm_n
                total_raw += raw_n
                total_normalized += norm_n
                total_issues += len(issues)
                all_issues.extend(issues)
                _print(
                    f"  committed [{batch_label}] raw+={raw_n} norm+={norm_n} "
                    f"src_total(raw={src_raw},norm={src_norm}) "
                    f"run_total(raw={total_raw},norm={total_normalized},issues={total_issues})"
                )

            try:
                connector = build_connector(source)
            except Exception as e:  # noqa: BLE001
                _print(f"  ! connector build failed: {e!r}")
                all_failures.append(
                    SourceFailure(
                        source_id=source.source_id,
                        source_name=source.name,
                        error_type=type(e).__name__,
                        error_message=str(e),
                        attempts=1,
                    )
                )
                continue

            try:
                if isinstance(connector, JzscLiveConnectorBase):
                    # 原生支持流式
                    connector.iter_fetch_batches(_on_batch)
                else:
                    # 非 jzsc 连接器：直接 fetch，整包作为单 batch 提交
                    records = list(connector.fetch())
                    _on_batch("all", records)
                _print(f"source {src_idx}/{len(sources)} [{source.source_id}] done src_raw={src_raw} src_norm={src_norm}")
                # 每 source 完成就推进 cursor（可断点续）
                upsert_source_cursors(conn, {source.source_id: ended_cursor()})
            except KeyboardInterrupt:
                _print(f"  ! interrupted by user during [{source.source_id}]")
                raise
            except Exception as e:  # noqa: BLE001
                _print(f"  ! source error: {type(e).__name__}: {e}")
                all_failures.append(
                    SourceFailure(
                        source_id=source.source_id,
                        source_name=source.name,
                        error_type=type(e).__name__,
                        error_message=str(e),
                        attempts=1,
                    )
                )

        if all_failures:
            insert_source_failures(conn, run_id, all_failures)

        ended_at = _utc_now_iso()
        insert_run_summary(
            conn=conn,
            run_id=run_id,
            started_at=started_at,
            ended_at=ended_at,
            source_count=len(sources),
            raw_count=total_raw,
            normalized_count=total_normalized,
            issue_count=total_issues,
            failed_source_count=len(all_failures),
        )
        _print(
            f"run_finished run_id={run_id} raw={total_raw} "
            f"norm={total_normalized} issues={total_issues} failed_sources={len(all_failures)}"
        )
    except KeyboardInterrupt:
        ended_at = _utc_now_iso()
        _print(f"! aborted by user run_id={run_id} partial_raw={total_raw} partial_norm={total_normalized}")
        try:
            insert_run_summary(
                conn=conn,
                run_id=run_id,
                started_at=started_at,
                ended_at=ended_at,
                source_count=len(sources) if 'sources' in dir() else 0,
                raw_count=total_raw,
                normalized_count=total_normalized,
                issue_count=total_issues,
                failed_source_count=len(all_failures),
            )
        except Exception:
            pass
        raise
    finally:
        if lock_acquired:
            release_run_lock(conn, lock_name=RUN_LOCK_NAME, owner_id=owner_id)
        conn.close()

    return RunSummary(
        run_id=run_id,
        started_at=started_at,
        ended_at=ended_at,
        source_count=len(sources),
        raw_count=total_raw,
        normalized_count=total_normalized,
        issue_count=total_issues,
        failed_source_count=len(all_failures),
        issues=all_issues,
        failures=all_failures,
    )
