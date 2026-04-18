from __future__ import annotations

from typing import Iterable, List

from .models import NormalizedEntity, QualityIssue
from .utils import is_valid_city_code, is_valid_uscc


def validate_entity(entity: NormalizedEntity) -> List[QualityIssue]:
    issues: List[QualityIssue] = []
    etype = entity.entity_type.lower()

    if not entity.name:
        issues.append(
            QualityIssue(
                source_id=entity.source_id,
                entity_key=entity.entity_key,
                issue_code="NAME_EMPTY",
                issue_message="Entity name is empty",
                severity="ERROR",
            )
        )

    if etype == "enterprise" and entity.uscc and not is_valid_uscc(entity.uscc):
        issues.append(
            QualityIssue(
                source_id=entity.source_id,
                entity_key=entity.entity_key,
                issue_code="USCC_INVALID",
                issue_message=f"USCC format invalid: {entity.uscc}",
                severity="ERROR",
            )
        )

    if not is_valid_city_code(entity.city_code):
        issues.append(
            QualityIssue(
                source_id=entity.source_id,
                entity_key=entity.entity_key,
                issue_code="CITY_CODE_INVALID",
                issue_message=f"City code invalid: {entity.city_code}",
                severity="ERROR",
            )
        )

    if entity.score < 0 or entity.score > 100:
        issues.append(
            QualityIssue(
                source_id=entity.source_id,
                entity_key=entity.entity_key,
                issue_code="SCORE_OUT_OF_RANGE",
                issue_message=f"Score out of range: {entity.score}",
                severity="ERROR",
            )
        )

    if not entity.event_date:
        issues.append(
            QualityIssue(
                source_id=entity.source_id,
                entity_key=entity.entity_key,
                issue_code="EVENT_DATE_INVALID",
                issue_message="Event date is empty or invalid",
                severity="WARN",
            )
        )

    if etype == "staff":
        masked = str(entity.raw_payload.get("person_id_no_masked", "")).strip()
        if masked and "*" not in masked:
            issues.append(
                QualityIssue(
                    source_id=entity.source_id,
                    entity_key=entity.entity_key,
                    issue_code="PII_MASK_INVALID",
                    issue_message="Staff id number is not masked",
                    severity="ERROR",
                )
            )

    return issues


def validate_batch(entities: Iterable[NormalizedEntity]) -> List[QualityIssue]:
    issues: List[QualityIssue] = []
    for entity in entities:
        issues.extend(validate_entity(entity))
    return issues
