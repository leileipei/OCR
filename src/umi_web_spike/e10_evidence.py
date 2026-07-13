from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

from .evidence import SCHEMA_VERSION, is_utc_timestamp, validate_validation_id


ALLOWED_PROTOCOLS = {"oidc", "oauth2", "cas", "saml2", "official_ticket"}


@dataclass(frozen=True)
class E10Evidence:
    schema_version: str
    validation_id: str
    recorded_at_utc: str
    protocol: str
    official_document_reference: str
    official_document_sha256: str
    login_endpoint: str
    verification_endpoint: str
    external_user_id_field: str
    department_id_field: str
    test_login_succeeded: bool
    disabled_account_rejected: bool
    logout_behavior_verified: bool

    @property
    def ready(self) -> bool:
        return (
            self.test_login_succeeded
            and self.disabled_account_rejected
            and self.logout_behavior_verified
        )

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "E10Evidence":
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("schema_version must be 1.0")
        validate_validation_id(value.get("validation_id"))
        if not is_utc_timestamp(value.get("recorded_at_utc")):
            raise ValueError("recorded_at_utc must be an ISO-8601 UTC timestamp")
        raw_protocol = value.get("protocol")
        if not isinstance(raw_protocol, str) or not raw_protocol.strip():
            raise ValueError("protocol is required and must be a string")
        protocol = raw_protocol.lower()
        if protocol not in ALLOWED_PROTOCOLS:
            raise ValueError(f"unsupported or unsafe protocol: {protocol}")
        for key in (
            "official_document_reference",
            "login_endpoint",
            "verification_endpoint",
            "external_user_id_field",
            "department_id_field",
        ):
            field_value = value.get(key)
            if not isinstance(field_value, str) or not field_value.strip():
                raise ValueError(f"{key} is required and must be a string")
        digest = value.get("official_document_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("official_document_sha256 must be a lowercase SHA-256 digest")
        for key in (
            "test_login_succeeded",
            "disabled_account_rejected",
            "logout_behavior_verified",
        ):
            if not isinstance(value.get(key), bool):
                raise ValueError(f"{key} must be a JSON boolean")
        for key in ("login_endpoint", "verification_endpoint"):
            parsed = urlparse(value[key])
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError(f"{key} must use https and include a network location")
        derived_ready = all(
            value[key]
            for key in (
                "test_login_succeeded",
                "disabled_account_rejected",
                "logout_behavior_verified",
            )
        )
        if not isinstance(value.get("ready"), bool):
            raise ValueError("ready is required and must be a JSON boolean")
        if value["ready"] is not derived_ready:
            raise ValueError("ready must match the three derived verification results")
        return cls(**{field: value[field] for field in cls.__dataclass_fields__})

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["ready"] = self.ready
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
