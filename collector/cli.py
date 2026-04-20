from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .export_interface_catalog import export_interface_catalog
from .export_live_data import export_live_json
from .export_source_routes import export_source_routes_json
from .pipeline import bootstrap_source_registry, run_pipeline, run_pipeline_streaming


def _default_db_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "collector.db"


def _default_config_path() -> Path:
    return Path(__file__).resolve().parent / "config" / "sources.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Construction market integrity collector.")
    sub = parser.add_subparsers(dest="command", required=True)

    init_cmd = sub.add_parser("init-db", help="Initialize database and source registry.")
    init_cmd.add_argument("--db", type=Path, default=_default_db_path())
    init_cmd.add_argument("--config", type=Path, default=_default_config_path())

    run_cmd = sub.add_parser("run", help="Run one ingestion pipeline.")
    run_cmd.add_argument("--db", type=Path, default=_default_db_path())
    run_cmd.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    run_cmd.add_argument(
        "--force-unlock",
        action="store_true",
        help="Force clear the existing run lock before pipeline starts.",
    )

    stream_cmd = sub.add_parser(
        "run-stream",
        help="Run pipeline in streaming mode: commits after each batch, Ctrl+C-safe.",
    )
    stream_cmd.add_argument("--db", type=Path, default=_default_db_path())
    stream_cmd.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    stream_cmd.add_argument("--force-unlock", action="store_true")
    stream_cmd.add_argument(
        "--skip-export",
        action="store_true",
        help="Skip re-exporting scripts/live-data.json and scripts/source-routes.json at end.",
    )
    stream_cmd.add_argument(
        "--source-id",
        action="append",
        default=None,
        help="Only run the given source_id (can be repeated, or comma-separated). Overrides sources.json enabled flags.",
    )

    export_cmd = sub.add_parser("export-interfaces", help="Export nationwide interface candidates.")
    export_cmd.add_argument("--db", type=Path, default=_default_db_path())
    export_cmd.add_argument("--output", type=Path, default=None)
    export_cmd.add_argument("--max-pages", type=int, default=600)
    export_cmd.add_argument("--workers", type=int, default=12)
    export_cmd.add_argument("--timeout", type=int, default=18)

    return parser


def cmd_init_db(db: Path, config: Path) -> None:
    count = bootstrap_source_registry(db_path=db, config_path=config)
    print(f"[init-db] source registry loaded: {count} entries")
    print(f"[init-db] sqlite path: {db}")


def cmd_run(db: Path, force_unlock: bool = False) -> None:
    if force_unlock:
        print("[run] force-unlock enabled: clearing existing run lock before starting")

    summary = run_pipeline(db_path=db, force_unlock=force_unlock)
    project_root = Path(__file__).resolve().parent.parent
    export_live_json(
        db_path=db,
        output_path=project_root / "scripts" / "live-data.json",
        limit_each=20000,
    )
    export_source_routes_json(
        db_path=db,
        output_path=project_root / "scripts" / "source-routes.json",
        limit_each=600,
    )
    print(f"[run] run_id={summary.run_id}")
    print(
        f"[run] sources={summary.source_count} raw={summary.raw_count} "
        f"normalized={summary.normalized_count} issues={summary.issue_count} "
        f"failed_sources={summary.failed_source_count}"
    )
    if summary.failures:
        print("[run] source failures:")
        for failure in summary.failures:
            print(
                f"  - {failure.source_id} ({failure.source_name}) "
                f"[{failure.error_type}] attempts={failure.attempts}: {failure.error_message}"
            )
    if summary.issues:
        print("[run] quality issues:")
        for issue in summary.issues:
            print(
                f"  - [{issue.severity}] {issue.issue_code} "
                f"{issue.entity_key}: {issue.issue_message}"
            )
    print("[run] live json exported: scripts/live-data.json")
    print("[run] source routes exported: scripts/source-routes.json")


def cmd_export_interfaces(
    db: Path,
    output: Path | None,
    max_pages: int,
    workers: int,
    timeout: int,
) -> None:
    project_root = Path(__file__).resolve().parent.parent
    output_path = output or (project_root / "scripts" / "interface-catalog.json")
    data = export_interface_catalog(
        db_path=db,
        output_path=output_path,
        max_pages=max_pages,
        workers=workers,
        timeout_sec=timeout,
    )
    print(
        f"[export-interfaces] run_id={data['run_id']} "
        f"pages={data['pages_scanned']} failed={data['pages_failed']} "
        f"endpoint_unique={data['endpoint_unique_count']}"
    )
    print(f"[export-interfaces] written: {output_path}")


def cmd_run_stream(
    db: Path,
    force_unlock: bool = False,
    skip_export: bool = False,
    source_ids: list[str] | None = None,
) -> None:
    if force_unlock:
        print("[run-stream] force-unlock enabled: clearing existing run lock before starting", flush=True)
    try:
        summary = run_pipeline_streaming(
            db_path=db,
            force_unlock=force_unlock,
            source_ids=source_ids,
        )
    except KeyboardInterrupt:
        print("\n[run-stream] interrupted; partial data already committed to DB", flush=True)
        return
    project_root = Path(__file__).resolve().parent.parent
    if not skip_export:
        print("[run-stream] exporting scripts/live-data.json and scripts/source-routes.json ...", flush=True)
        export_live_json(
            db_path=db,
            output_path=project_root / "scripts" / "live-data.json",
            limit_each=6000,
        )
        export_source_routes_json(
            db_path=db,
            output_path=project_root / "scripts" / "source-routes.json",
            limit_each=600,
        )
    print(
        f"[run-stream] done run_id={summary.run_id} "
        f"raw={summary.raw_count} norm={summary.normalized_count} "
        f"issues={summary.issue_count} failed_sources={summary.failed_source_count}",
        flush=True,
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init-db":
        cmd_init_db(db=args.db, config=args.config)
        return
    if args.command == "run":
        logging.basicConfig(
            level=getattr(logging, args.log_level),
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        cmd_run(db=args.db, force_unlock=args.force_unlock)
        return
    if args.command == "run-stream":
        logging.basicConfig(
            level=getattr(logging, args.log_level),
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        # --source-id 可多次出现或逗号分隔
        raw_ids = args.source_id or []
        expanded: list[str] = []
        for item in raw_ids:
            for part in str(item).split(","):
                s = part.strip()
                if s:
                    expanded.append(s)
        cmd_run_stream(
            db=args.db,
            force_unlock=args.force_unlock,
            skip_export=args.skip_export,
            source_ids=expanded or None,
        )
        return
    if args.command == "export-interfaces":
        cmd_export_interfaces(
            db=args.db,
            output=args.output,
            max_pages=args.max_pages,
            workers=args.workers,
            timeout=args.timeout,
        )
        return

    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
