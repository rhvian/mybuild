from __future__ import annotations

from typing import Iterable, List

from .models import NormalizedEntity, RawRecord
from .utils import normalize_uscc, parse_date, risk_from_score, stable_hash


def normalize_record(record: RawRecord) -> NormalizedEntity:
    payload = record.payload
    score = int(payload.get("score", 0))
    event_date = parse_date(payload.get("event_date"))
    uscc = normalize_uscc(payload.get("uscc"))
    project_code = str(payload.get("project_code", "")).strip()
    entity_type = str(payload.get("entity_type", "enterprise")).strip().lower()
    name = str(payload.get("name", "")).strip()
    status = str(payload.get("status", "UNKNOWN")).strip().upper()

    record_type = record.record_type.strip().lower()
    if record_type == "staff":
        entity_key = f"STAFF:{record.city_code}:{name}:{project_code}"
    elif record_type == "tender":
        entity_key = f"TENDER:{record.city_code}:{project_code}"
    elif record_type == "endpoint_catalog":
        entity_key = f"ENDPOINT:{record.source_id}:{project_code}"
    else:
        entity_key = uscc or f"{record.city_code}:{name}:{project_code}"
    evidence_hash = stable_hash(
        {
            "source_id": record.source_id,
            "source_url": record.source_url,
            "payload": payload,
            "captured_at": record.captured_at,
        }
    )

    return NormalizedEntity(
        entity_key=entity_key,
        entity_type=entity_type,
        name=name,
        uscc=uscc,
        project_code=project_code,
        city_code=record.city_code,
        city_name=record.city_name,
        province_code=record.province_code,
        score=score,
        risk_level=risk_from_score(score),
        status=status,
        event_date=event_date,
        source_id=record.source_id,
        source_url=record.source_url,
        source_level=record.source_level,
        evidence_hash=evidence_hash,
        raw_payload=payload,
    )


def normalize_batch(records: Iterable[RawRecord]) -> List[NormalizedEntity]:
    return [normalize_record(record) for record in records]
