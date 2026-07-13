from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse


ALLOWED_PROTOCOLS = {"oidc", "oauth2", "cas", "saml2", "official_ticket"}


@dataclass(frozen=True)
class E10Evidence:
    protocol: str
    official_document_reference: str
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
        return cls(**{field: value[field] for field in cls.__dataclass_fields__})

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["ready"] = self.ready
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
