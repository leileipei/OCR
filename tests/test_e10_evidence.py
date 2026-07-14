import json
import hashlib
from pathlib import Path

import pytest

from umi_web_spike.e10_evidence import E10Evidence


OFFICIAL_DOCUMENT = Path(__file__).resolve()

VALID = {
    "schema_version": "1.0",
    "validation_id": "run-20260713-001",
    "recorded_at_utc": "2026-07-13T04:05:06Z",
    "protocol": "oidc",
    "official_document_reference": "E10 客户开放平台/统一身份接口文档版本 10",
    "official_document_path": str(OFFICIAL_DOCUMENT),
    "official_document_sha256": hashlib.sha256(OFFICIAL_DOCUMENT.read_bytes()).hexdigest(),
    "login_endpoint": "https://oa.example.internal/sso/authorize",
    "verification_endpoint": "https://oa.example.internal/sso/userinfo",
    "external_user_id_field": "user_id",
    "department_id_field": "department_id",
    "test_login_succeeded": True,
    "disabled_account_rejected": True,
    "logout_behavior_verified": True,
    "ready": True,
}


def test_accepts_complete_official_evidence():
    evidence = E10Evidence.from_dict(VALID)
    assert evidence.ready is True


def test_rejects_database_or_cookie_integration():
    for protocol in ("database", "shared_cookie", "html_scraping"):
        value = {**VALID, "protocol": protocol}
        try:
            E10Evidence.from_dict(value)
        except ValueError as error:
            assert "unsupported or unsafe protocol" in str(error)
        else:
            raise AssertionError(f"unsafe protocol accepted: {protocol}")


def test_requires_stable_user_and_department_identifiers():
    value = {**VALID, "external_user_id_field": ""}
    try:
        E10Evidence.from_dict(value)
    except ValueError as error:
        assert "external_user_id_field" in str(error)
    else:
        raise AssertionError("missing stable user id was accepted")


@pytest.mark.parametrize(
    "field",
    (
        "official_document_reference",
        "login_endpoint",
        "verification_endpoint",
        "external_user_id_field",
        "department_id_field",
    ),
)
@pytest.mark.parametrize("invalid_value", (None, 123))
def test_required_text_fields_reject_null_and_non_strings(field, invalid_value):
    value = {**VALID, field: invalid_value}

    with pytest.raises(ValueError, match=field):
        E10Evidence.from_dict(value)


@pytest.mark.parametrize(
    "field",
    (
        "test_login_succeeded",
        "disabled_account_rejected",
        "logout_behavior_verified",
    ),
)
def test_verification_results_must_be_json_booleans(field):
    value = {**VALID, field: "false"}

    with pytest.raises(ValueError, match=field):
        E10Evidence.from_dict(value)


def test_ready_is_required_boolean_and_must_match_derived_tests():
    for value in (
        {key: item for key, item in VALID.items() if key != "ready"},
        {**VALID, "ready": "true"},
        {**VALID, "ready": False},
        {**VALID, "test_login_succeeded": False, "ready": True},
    ):
        with pytest.raises(ValueError, match="ready"):
            E10Evidence.from_dict(value)


@pytest.mark.parametrize("digest", (None, "short", "G" * 64))
def test_official_document_requires_valid_sha256(digest):
    with pytest.raises(ValueError, match="official_document_sha256"):
        E10Evidence.from_dict({**VALID, "official_document_sha256": digest})


def test_official_document_sha256_is_recomputed_from_real_file(tmp_path):
    document = tmp_path / "official.pdf"
    document.write_bytes(b"official-v1")
    value = {
        **VALID,
        "official_document_path": str(document.resolve()),
        "official_document_sha256": hashlib.sha256(b"different").hexdigest(),
    }
    with pytest.raises(ValueError, match="does not match"):
        E10Evidence.from_dict(value)


@pytest.mark.parametrize("path", ("relative.pdf", "/definitely/missing/e10.pdf"))
def test_official_document_path_must_be_absolute_existing_file(path):
    with pytest.raises(ValueError, match="official_document_path"):
        E10Evidence.from_dict({**VALID, "official_document_path": path})


@pytest.mark.parametrize("field", ("login_endpoint", "verification_endpoint"))
def test_https_endpoints_require_a_network_location(field):
    value = {**VALID, field: "https:///sso/endpoint"}

    with pytest.raises(ValueError, match=field):
        E10Evidence.from_dict(value)


def test_write_json_creates_parent_and_writes_utf8_ready_boolean(tmp_path):
    evidence = E10Evidence.from_dict(VALID)
    output = tmp_path / "nested" / "e10.json"

    evidence.write_json(output)

    raw = output.read_bytes()
    assert "E10 客户开放平台" in raw.decode("utf-8")
    payload = json.loads(raw)
    assert payload["ready"] is True
    assert isinstance(payload["ready"], bool)
