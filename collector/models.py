from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SourceDefinition:
    source_id: str
    name: str
    source_type: str
    source_level: str
    base_url: str
    province_code: str | None = None
    city_code: str | None = None
    enabled: bool = True


@dataclass(slots=True)
class RawRecord:
    source_id: str
    source_name: str
    source_level: str
    source_url: str
    record_type: str
    city_code: str
    city_name: str
    province_code: str
    payload: Dict[str, Any]
    captured_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class NormalizedEntity:
    entity_key: str
    entity_type: str
    name: str
    uscc: str
    project_code: str
    city_code: str
    city_name: str
    province_code: str
    score: int
    risk_level: str
    status: str
    event_date: str
    source_id: str
    source_url: str
    source_level: str
    evidence_hash: str
    raw_payload: Dict[str, Any]


@dataclass(slots=True)
class QualityIssue:
    source_id: str
    entity_key: str
    issue_code: str
    issue_message: str
    severity: str
    detected_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class SourceFailure:
    source_id: str
    source_name: str
    error_type: str
    error_message: str
    attempts: int
    failed_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class RunSummary:
    run_id: str
    started_at: str
    ended_at: str
    source_count: int
    raw_count: int
    normalized_count: int
    issue_count: int
    failed_source_count: int
    issues: List[QualityIssue]
    failures: List[SourceFailure]
