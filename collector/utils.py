from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict


USCC_REGEX = re.compile(r"^[0-9A-Z]{18}$")
# 老的组织机构代码：9 位（8 位代码 + 1 位校验位），允许数字和字母（可能含 "-"）
ORG_CODE_REGEX = re.compile(r"^[0-9A-Z]{8,9}[0-9A-Z]?$")
CITY_CODE_REGEX = re.compile(r"^\d{6}$")


def stable_hash(payload: Dict[str, Any]) -> str:
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def normalize_uscc(uscc: str | None) -> str:
    if not uscc:
        return ""
    return uscc.strip().upper()


def is_valid_uscc(uscc: str) -> bool:
    # 接受 18 位 USCC，或 8-10 位老组织机构代码（过渡期大量企业仍使用）。
    return bool(USCC_REGEX.match(uscc) or ORG_CODE_REGEX.match(uscc))


def is_valid_city_code(code: str) -> bool:
    return bool(CITY_CODE_REGEX.match(code))


def parse_date(date_text: str | None) -> str:
    if not date_text:
        return ""

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(date_text, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def risk_from_score(score: int) -> str:
    if score >= 90:
        return "LOW"
    if score >= 75:
        return "MEDIUM"
    return "HIGH"

